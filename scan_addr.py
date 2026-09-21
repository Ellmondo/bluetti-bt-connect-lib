#!/usr/bin/env python3
"""List nearby BLE devices and their addresses, so you can find the EP2000/EBOX.

On macOS the 'address' is a CoreBluetooth UUID - that's what probe_*.py --mac
wants here. Bluetti units advertise names like EP2000..., EBOX..., BLUETTI...

    cd ~/git/bluetti-bt-connect-lib && source ~/bluetti-venv/bin/activate
    python scan_addr.py
"""
import asyncio
from bleak import BleakScanner


async def main():
    print("Scanning 10s ...\n")
    devices = await BleakScanner.discover(timeout=10.0)
    rows = sorted(devices, key=lambda d: (d.name is None, (d.name or "").lower()))
    likely = []
    for d in rows:
        name = d.name or "(no name)"
        mark = ""
        up = (d.name or "").upper()
        if any(up.startswith(p) for p in ("EP", "EBOX", "BLUETTI", "PBOX", "AC", "EL", "PR")):
            mark = "  <-- looks like a Bluetti"
            likely.append((name, d.address))
        print(f"{d.address}   {name}{mark}")
    print()
    if likely:
        print("Likely Bluetti device(s):")
        for name, addr in likely:
            print(f'  python probe_writepath.py --mac {addr}    # {name}')
    else:
        print("No obvious Bluetti name seen. Make sure 'Hold Bluetooth "
              "connection' is OFF in HA so the unit is advertising, and that "
              "you're close to it.")


if __name__ == "__main__":
    asyncio.run(main())
