#!/usr/bin/env python3
"""Verify register grouping against a real device.

Grouping changes how registers are fetched, not what they mean, so the thing
worth proving is that the grouped read returns the same values as the
one-request-per-field read it replaced - on your actual hardware, not a mock.

Method: read the device three times.

    A  ungrouped   (one request per field, the old behaviour)
    B  grouped     (the new behaviour)
    C  ungrouped   (again)

Power, voltage and current move constantly, so a plain A-vs-B diff would be
full of meaningless differences. Instead, any field that differs between A and
C is volatile by definition, and gets excluded from the strict comparison. Every
field that held still across A and C *must* match in B - a mismatch there is a
real bug, not the sun going behind a cloud.

Run it from the repo root so it tests the working tree rather than whatever is
installed:

    cd ~/git/bluetti-bt-connect-lib
    source ~/bluetti-venv/bin/activate
    python verify_grouping.py --mac <address> --type EP2000

Get <address> from `bluetti-scan`. On Linux it is a MAC; on macOS CoreBluetooth
hands out a per-host UUID instead, so use whatever scan prints on the machine
you are running this from.

Nothing here writes to the device - it only reads.
"""

import argparse
import asyncio
import logging
import time

from bluetti_bt_connect_lib.bluetooth.device_reader import (
    DeviceReader,
    DeviceReaderConfig,
)
from bluetti_bt_connect_lib.fields import WriteableStringField
from bluetti_bt_connect_lib.utils.device_builder import build_device


def build(dev_type: str, gap):
    """Build a device with grouping set to `gap` (None disables it)."""
    device = build_device(dev_type + "12345678")

    if device is None:
        raise SystemExit(f"Unsupported powerstation type: {dev_type}")

    # Mirror what BluettiDevice.__init__ does, with a different gap.
    device.max_register_gap = gap
    device.polling_registers = device._group_registers(
        [f for f in device.fields if not isinstance(f, WriteableStringField)]
    )

    return device


class FallbackWatcher(logging.Handler):
    """Counts grouped reads the device rejected."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.rejected = []

    def emit(self, record):
        message = record.getMessage()
        if "was rejected" in message:
            self.rejected.append(message)


def instrument(reader):
    """Count how many requests actually go out over the link."""
    counter = {"requests": 0}
    original = reader._async_send_command

    async def counted(registers):
        counter["requests"] += 1
        return await original(registers)

    reader._async_send_command = counted
    return counter


async def read_once(label, address, device, timeout):
    reader = DeviceReader(
        address, device, asyncio.Future, DeviceReaderConfig(timeout=timeout)
    )
    counter = instrument(reader)

    watcher = FallbackWatcher()
    lib_logger = logging.getLogger("bluetti_bt_connect_lib")
    previous_level = lib_logger.level
    lib_logger.setLevel(logging.DEBUG)
    lib_logger.addHandler(watcher)

    print(f"  {label}: planned {len(device.get_polling_registers())} requests ...", flush=True)

    started = time.perf_counter()
    try:
        data = await reader.read()
    finally:
        lib_logger.removeHandler(watcher)
        lib_logger.setLevel(previous_level)
    elapsed = time.perf_counter() - started

    if data is None:
        raise SystemExit(f"  {label}: read failed - device unreachable or busy?")

    print(
        f"  {label}: {counter['requests']} requests sent, "
        f"{len(data)} fields, {elapsed:.1f}s"
        + (f", {len(watcher.rejected)} groups rejected" if watcher.rejected else "")
    )

    return {
        "data": data,
        "requests": counter["requests"],
        "elapsed": elapsed,
        "rejected": watcher.rejected,
    }


def plan(dev_type):
    """Print the request plan for both modes without touching the device."""
    for label, gap in (("ungrouped", None), ("grouped", 8)):
        device = build(dev_type, gap)
        registers = device.get_polling_registers()
        words = sum(r.quantity for r in registers)
        print(f"\n{label}: {len(registers)} requests, {words} registers read")
        if gap is not None:
            merged = [r for r in registers if r.members]
            print(f"  {len(merged)} of them merged, largest {max(r.quantity for r in registers)} registers")
            for r in merged:
                addresses = ", ".join(str(m.starting_address) for m in r.members)
                print(f"    addr {r.starting_address:>6} qty {r.quantity:>3}  <- {addresses}")


async def compare(address, dev_type, timeout, settle):
    print(f"\nReading {dev_type} at {address}\n")

    print("Pass 1 of 3")
    a = await read_once("ungrouped ", address, build(dev_type, None), timeout)
    await asyncio.sleep(settle)

    print("Pass 2 of 3")
    b = await read_once("grouped   ", address, build(dev_type, 8), timeout)
    await asyncio.sleep(settle)

    print("Pass 3 of 3")
    c = await read_once("ungrouped ", address, build(dev_type, None), timeout)

    # --- coverage -------------------------------------------------------
    baseline = set(a["data"]) | set(c["data"])
    grouped = set(b["data"])

    missing = sorted(baseline - grouped)
    extra = sorted(grouped - baseline)

    # --- correctness ----------------------------------------------------
    # Fields that held still across both ungrouped reads are the ones we can
    # hold the grouped read to.
    stable = sorted(
        f
        for f in set(a["data"]) & set(c["data"]) & grouped
        if a["data"][f] == c["data"][f]
    )
    volatile = sorted(
        f
        for f in set(a["data"]) & set(c["data"])
        if a["data"][f] != c["data"][f]
    )
    mismatched = [f for f in stable if b["data"][f] != a["data"][f]]

    print("\n" + "=" * 68)
    print("COVERAGE")
    print("=" * 68)
    print(f"  ungrouped returned : {len(baseline)} fields")
    print(f"  grouped returned   : {len(grouped)} fields")
    if missing:
        print(f"\n  !! {len(missing)} field(s) MISSING from the grouped read:")
        for f in missing:
            print(f"       {f}")
    if extra:
        print(f"\n  {len(extra)} field(s) only the grouped read returned:")
        for f in extra:
            print(f"       {f} = {b['data'][f]}")
    if not missing and not extra:
        print("  identical field coverage")

    print("\n" + "=" * 68)
    print("CORRECTNESS")
    print("=" * 68)
    print(f"  {len(stable)} field(s) stable across both ungrouped reads - these must match")
    print(f"  {len(volatile)} field(s) moved on their own and are excluded")
    if mismatched:
        print(f"\n  !! {len(mismatched)} MISMATCH(ES) - grouping is reading the wrong data:")
        for f in mismatched:
            print(f"       {f}: ungrouped={a['data'][f]!r}  grouped={b['data'][f]!r}")
    else:
        print("  every stable field matched")

    if volatile:
        print("\n  excluded as volatile (shown for eyeballing):")
        for f in volatile:
            got = b["data"].get(f, "<missing>")
            print(f"       {f}: {a['data'][f]} -> {got} -> {c['data'][f]}")

    print("\n" + "=" * 68)
    print("PERFORMANCE")
    print("=" * 68)
    ungrouped_requests = (a["requests"] + c["requests"]) / 2
    ungrouped_time = (a["elapsed"] + c["elapsed"]) / 2
    print(f"  requests : {ungrouped_requests:.0f} -> {b['requests']}"
          f"   ({ungrouped_requests / max(b['requests'], 1):.1f}x fewer)")
    print(f"  duration : {ungrouped_time:.1f}s -> {b['elapsed']:.1f}s"
          f"   ({ungrouped_time / max(b['elapsed'], 0.01):.1f}x faster)")

    if b["rejected"]:
        print(f"\n  {len(b['rejected'])} grouped read(s) rejected and fell back:")
        for message in b["rejected"]:
            print(f"    {message}")
        print("  (values are still correct - the fallback covered them - but these")
        print("   groups cost extra round trips. Worth lowering max_register_gap.)")

    print("\n" + "=" * 68)
    if missing or mismatched:
        print("RESULT: FAILED - see the flagged items above")
        return 1
    print("RESULT: PASSED - grouped reads match, with fewer requests")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Verify register grouping against a real Bluetti device"
    )
    parser.add_argument("-m", "--mac", help="Device address (see `bluetti-scan`)")
    parser.add_argument("-t", "--type", required=True, help="Device type, e.g. EP2000")
    parser.add_argument("--timeout", type=int, default=90, help="Per-read timeout (default 90)")
    parser.add_argument(
        "--settle",
        type=float,
        default=5.0,
        help="Seconds between reads, letting the device drop the link (default 5)",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print the request plan for both modes and exit - no device needed",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    if args.plan:
        plan(args.type)
        return 0

    if not args.mac:
        parser.error("--mac is required unless --plan is given")

    return asyncio.run(compare(args.mac, args.type, args.timeout, args.settle))


if __name__ == "__main__":
    raise SystemExit(main())
