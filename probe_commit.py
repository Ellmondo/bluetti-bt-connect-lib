#!/usr/bin/env python3
"""Find what makes a protected write PERSIST (not just get echoed).

A plain write is echoed and reads back correct for a few seconds, then the
device can revert it on its next control cycle. The official app sends a commit
pulse after settings changes - CTRL_EVENT (register 2006) = 1. This tests
whether that commit is what makes the change stick.

For each strategy it writes a test value, WATCHES the register for ~45s
(reading every few seconds, so a slow revert is caught), reports whether it
held the whole window, then restores the original.

    source ~/bluetti-venv/bin/activate
    python probe_commit.py --mac 601401B1-73F3-EB4F-47C5-780F4E959316
    python probe_commit.py --mac <addr> --reg 2005 --value 4   # working mode

Turn OFF "Hold Bluetooth connection" in Home Assistant first.
"""

import argparse
import asyncio
import sys
import time

import crcmod.predefined
from bleak import BleakScanner
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"

crc16 = crcmod.predefined.mkCrcFun("modbus")

CTRL_EVENT = 2006                    # commit pulse (=1)
CTRL_POWER_OUTPUT_STATE_SAVE = 2226  # save pulse (=1)

EXC = {0x01: "illegal function", 0x02: "illegal data address",
       0x03: "illegal data value", 0x04: "server device failure", 0x06: "server busy"}


def framed(p): return p + crc16(p).to_bytes(2, "little")
def read_cmd(s, a, q=1): return framed(bytes([s, 3]) + a.to_bytes(2, "big") + q.to_bytes(2, "big"))
def write_cmd(s, a, v): return framed(bytes([s, 6]) + a.to_bytes(2, "big") + v.to_bytes(2, "big"))


class Conn:
    def __init__(self, client):
        self.client = client
        self.buf = bytearray(); self.fut = None; self.want = 0; self.func = 0

    def on_notify(self, _, data):
        self.buf.extend(data)
        if self.fut is None or self.fut.done():
            return
        if len(self.buf) >= 2 and self.buf[1] == (self.func | 0x80) and len(self.buf) >= 5:
            self.fut.set_result(bytes(self.buf))
        elif len(self.buf) >= self.want:
            self.fut.set_result(bytes(self.buf))

    async def _txn(self, cmd, want, timeout=5.0):
        self.buf = bytearray(); self.func = cmd[1]; self.want = want
        self.fut = asyncio.get_running_loop().create_future()
        await self.client.write_gatt_char(WRITE_UUID, cmd)
        try:
            resp = await asyncio.wait_for(self.fut, timeout=timeout)
        except asyncio.TimeoutError:
            return None, "no response"
        if len(resp) >= 3 and resp[1] == (self.func | 0x80):
            return None, f"refused 0x{resp[2]:02x} ({EXC.get(resp[2], '?')})"
        if resp[-2:] != crc16(resp[:-2]).to_bytes(2, "little"):
            return None, "bad CRC"
        return resp, None

    async def read(self, addr, slave=1):
        r, e = await self._txn(read_cmd(slave, addr), 7)
        return (None, e) if e else (int.from_bytes(r[3:5], "big"), None)

    async def write(self, addr, val, slave=1):
        r, e = await self._txn(write_cmd(slave, addr, val), 8)
        return (None, e) if e else (int.from_bytes(r[4:6], "big"), None)


async def observe(conn, reg, want, seconds, interval):
    traj = []; held = True; t0 = time.monotonic()
    while True:
        v, e = await conn.read(reg)
        dt = time.monotonic() - t0
        traj.append((round(dt, 1), v))
        if v != want:
            held = False
        if dt >= seconds:
            break
        await asyncio.sleep(interval)
    return traj, held


async def strategy(conn, name, reg, testval, orig, commit, seconds, interval):
    print(f"\n--- {name}")
    ev, ee = await conn.write(reg, testval)
    print(f"    write {reg}={testval}: " + (ee or f"echoed {ev}"))
    if commit is not None:
        cv, ce = await conn.write(*commit)
        print(f"    commit {commit[0]}={commit[1]}: " + (ce or f"echoed {cv}"))
    traj, held = await observe(conn, reg, testval, seconds, interval)
    print("    trajectory: " + "  ".join(f"{t}s:{v}" for t, v in traj))
    print("    => " + ("HELD the whole window ***" if held else "REVERTED"))
    await conn.write(reg, orig)
    if commit is not None:
        await conn.write(*commit)
    await asyncio.sleep(3)
    chk, _ = await conn.read(reg)
    print(f"    restored to {orig}: now {chk}")
    return held


async def run(args):
    print("Scanning ...")
    dev = await BleakScanner.find_device_by_address(args.mac, timeout=15)
    if dev is None:
        raise SystemExit('Device not found. Turn OFF "Hold Bluetooth connection" in HA.')
    print("Connecting ...")
    client = await establish_connection(BleakClientWithServiceCache, dev, dev.name or "Bluetti", max_attempts=5)
    conn = Conn(client)
    await client.start_notify(NOTIFY_UUID, conn.on_notify)
    print("Connected.\n")
    reg = args.reg
    try:
        orig, err = await conn.read(reg)
        print(f"register {reg}: {orig}" + (f"  ({err})" if err else ""))
        if orig is None:
            raise SystemExit("Could not read the register.")
        testval = args.value if args.value is not None else orig + 100
        if testval == orig:
            testval = orig + 1
        print(f"Test value {testval} (original {orig}); watching {args.observe}s each.\n")
        results = {}
        results["plain write (no commit)"] = await strategy(
            conn, "plain write, then watch (control)", reg, testval, orig, None, args.observe, args.interval)
        results["write + CTRL_EVENT(2006)=1"] = await strategy(
            conn, "write + CTRL_EVENT commit", reg, testval, orig, (CTRL_EVENT, 1), args.observe, args.interval)
        results["write + STATE_SAVE(2226)=1"] = await strategy(
            conn, "write + POWER_OUTPUT_STATE_SAVE commit", reg, testval, orig, (CTRL_POWER_OUTPUT_STATE_SAVE, 1), args.observe, args.interval)
        print("\n================ SUMMARY ================")
        for k, v in results.items():
            print(f"  {'HELD    ' if v else 'reverted'}  {k}")
        winners = [k for k, v in results.items() if v]
        print("\n" + ("Persisting method: " + "; ".join(winners) if winners
              else "Nothing held for the full window - the revert is something else."))
    finally:
        try:
            await client.stop_notify(NOTIFY_UUID)
        except Exception:
            pass
        await client.disconnect()
        print('\nDisconnected. Turn "Hold Bluetooth connection" back on in HA.')
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("-m", "--mac", required=True)
    p.add_argument("-r", "--reg", type=int, default=2215)
    p.add_argument("-v", "--value", type=int)
    p.add_argument("--observe", type=float, default=45.0)
    p.add_argument("--interval", type=float, default=5.0)
    args = p.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
