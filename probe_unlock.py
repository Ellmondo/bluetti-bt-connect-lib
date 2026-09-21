#!/usr/bin/env python3
"""Test whether writing the Bluetooth password to register 7 makes a protected
write actually persist.

The theory (from decompiling the Bluetti app): protected settings - grid
export/import limits, working mode, expert params - are *echoed* by the device
but silently reverted unless the session has first authenticated by writing the
unit's Bluetooth settings password to register 7 (Modbus function 16). The
official app does this on entering the settings menus; the fork never has.

This script does an A/B test:

  * WITH unlock (default): connect, write the password to register 7, then do
    the protected write in the same session. Reconnect a few seconds later and
    read the value back.
  * WITHOUT unlock (--no-unlock): the same protected write and read-back, but
    no register-7 auth first - the fork's current behaviour.

Run it both ways. If the value sticks with unlock and reverts without, the
register-7 auth was the missing step.

Nothing here is destructive beyond the one setting you choose to write, and you
can put it straight back. Read-only if you omit --value.

Before running, hand the device over: turn OFF the "Hold Bluetooth connection"
switch in Home Assistant (the EP2000 accepts one central at a time).

Usage:

    cd ~/git/bluetti-bt-connect-lib
    source ~/bluetti-venv/bin/activate

    # just read the current value, no write
    python probe_unlock.py --mac <addr> --field max_grid_export_power

    # WITH unlock (blank password - the default when no BT password is set)
    python probe_unlock.py --mac <addr> --field max_grid_export_power --value 1500

    # WITH a specific password (read it from the Bluetti app if one is set)
    python probe_unlock.py --mac <addr> --field max_grid_export_power --value 1500 --password 1234

    # control run: same write, NO register-7 auth
    python probe_unlock.py --mac <addr> --field max_grid_export_power --value 1500 --no-unlock

Get <addr> from `bluetti-scan`. On macOS it is a CoreBluetooth UUID.
"""

import argparse
import asyncio
import logging
import sys

from bluetti_bt_connect_lib.bluetooth import DeviceReader, DeviceReaderConfig
from bluetti_bt_connect_lib.registers import ReadableRegisters
from bluetti_bt_connect_lib.utils.device_builder import build_device


def make_future():
    return asyncio.get_running_loop().create_future()


async def read_one(reader, field):
    """Read a single field's current value, or None if it could not be read."""
    result = await reader.read(only_registers=[ReadableRegisters(field.address, field.size)])
    if not result:
        return None
    return result.get(field.name)


async def run(args):
    device = build_device(args.type + "0000000000000")
    if device is None:
        raise SystemExit(f"Unsupported powerstation type: {args.type}")

    matches = [f for f in device.fields if f.name == args.field]
    if not matches:
        names = ", ".join(sorted(f.name for f in device.fields if f.is_writeable()))
        raise SystemExit(
            f"Unknown field '{args.field}'.\nWriteable fields: {names}"
        )
    field = matches[0]

    use_unlock = not args.no_unlock
    config = DeviceReaderConfig(
        timeout=args.timeout,
        unlock_password=(args.password if use_unlock else None),
    )
    reader = DeviceReader(args.mac, device, make_future, config)

    print(f"\nField      : {field.name}  (register {field.address})")
    print(f"Unlock     : {'yes' if use_unlock else 'NO (control run)'}"
          + (f"  password={args.password!r}" if use_unlock else ""))

    print("\nReading current value ...")
    before = await read_one(reader, field)
    print(f"  before   : {before}")

    if args.value is None:
        print("\nNo --value given, nothing written. Read-only run complete.")
        return 0

    print(f"\nWriting {field.name} = {args.value} "
          f"({'unlock then write, one session' if use_unlock else 'no unlock'}) ...")
    result = await reader.write(field.name, args.value)
    print(f"  result   : {result}")

    print(f"\nWaiting {args.readback}s, then reconnecting to read it back ...")
    await asyncio.sleep(args.readback)
    after = await read_one(reader, field)
    print(f"  after    : {after}")

    print("\n--- verdict ---")
    if after is None:
        print("Could not read the value back - inconclusive (try again).")
    elif after == args.value:
        print(f"PERSISTED: value is {after} after reconnect."
              + ("  Register-7 unlock worked." if use_unlock else
                 "  It stuck even WITHOUT unlock - auth may not be the gate."))
    else:
        print(f"REVERTED: wrote {args.value}, device now reports {after}."
              + ("  Unlock did not help - try a real password, or emsCtrlMode."
                 if use_unlock else
                 "  As expected without unlock - now try again without --no-unlock."))

    print(
        '\nTurn the "Hold Bluetooth connection" switch back on in Home '
        "Assistant when done, or wait for it to resume."
    )
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("-m", "--mac", required=True, help="Device address (see `bluetti-scan`)")
    p.add_argument("-t", "--type", default="EP2000", help="Device type (default EP2000)")
    p.add_argument("-f", "--field", default="max_grid_export_power",
                   help="Writeable field name (default max_grid_export_power)")
    p.add_argument("-v", "--value", type=int, help="Value to write (omit to just read)")
    p.add_argument("-p", "--password", default="",
                   help="Bluetooth settings password (default blank = unit with no password)")
    p.add_argument("--no-unlock", action="store_true",
                   help="Control run: do NOT authenticate register 7 first")
    p.add_argument("--readback", type=float, default=5.0,
                   help="Seconds to wait before reading the value back (default 5)")
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--debug", action="store_true", help="Verbose library logging")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
