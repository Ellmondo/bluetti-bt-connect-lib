#!/usr/bin/env python3
"""Find out WHY a protected write is accepted then reverted, by testing the
things the official app does that the fork does not.

From decompiling the app, a settings write is a plain Modbus function-6 to the
register - identical to the fork - with two differences that could explain the
revert:

  * slave address: the app writes to getSettingsSlaveAddr(), which for some
    devices is 0 (2nd-gen IoT) or a sub-node address, not the 1 the fork
    hardcodes.
  * EMS control mode (register 2241): value 8 = "EMS/AI control on". When the
    EMS is actively managing the system it can overwrite manual writes. The
    right setting for manual control may be 8, or may be 0 - so we test both.

This script connects once and runs an A/B matrix on ONE register: for each
strategy it writes a test value, waits, reads it back, and reports whether it
stuck - then restores the original value. Whichever strategy PERSISTS is the
missing step.

Raw Modbus frames, so the slave address is free (the fork's classes are locked
to slave 1). Read-only if you pass --dry (just reads current values).

Before running: turn OFF "Hold Bluetooth connection" in Home Assistant so the
device is free.

    cd ~/git/bluetti-bt-connect-lib && source ~/bluetti-venv/bin/activate
    python probe_writepath.py --mac <addr>                 # tests 2215 (grid export power)
    python probe_writepath.py --mac <addr> --reg 2005 --value 4   # working mode -> backup
    python probe_writepath.py --mac <addr> --dry          # read-only snapshot

Get <addr> from `bluetti-scan`. On macOS it is a CoreBluetooth UUID.
"""

import argparse
import asyncio
import sys

import crcmod.predefined
from bleak import BleakScanner
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from bluetti_bt_connect_lib.const import NOTIFY_UUID, WRITE_UUID

crc16 = crcmod.predefined.mkCrcFun("modbus")

EMS_CTRL_MODE = 2241     # ProtocolAddrV2.EMS_CTRL_MODE_SET ; 8 = EMS/AI on, 0 = off
CTRL_EVENT = 2006        # ProtocolAddrV2.CTRL_EVENT ; tried as a "commit" pulse

EXC = {
    0x01: "illegal function", 0x02: "illegal data address",
    0x03: "illegal data value", 0x04: "server device failure",
    0x05: "acknowledge (busy)", 0x06: "server busy",
}


def framed(payload: bytes) -> bytes:
    return payload + crc16(payload).to_bytes(2, "little")


def read_cmd(slave, addr, qty=1):
    return framed(bytes([slave, 3]) + addr.to_bytes(2, "big") + qty.to_bytes(2, "big"))


def write_cmd(slave, addr, val):
    return framed(bytes([slave, 6]) + addr.to_bytes(2, "big") + val.to_bytes(2, "big"))


class Conn:
    """One request / one reply over the notify characteristic."""

    def __init__(self, client):
        self.client = client
        self.buf = bytearray()
        self.fut = None
        self.want = 0
        self.func = 0

    def on_notify(self, _, data):
        self.buf.extend(data)
        if self.fut is None or self.fut.done():
            return
        exc = len(self.buf) >= 2 and self.buf[1] == (self.func | 0x80)
        if exc and len(self.buf) >= 5:
            self.fut.set_result(bytes(self.buf))
        elif len(self.buf) >= self.want:
            self.fut.set_result(bytes(self.buf))

    async def _txn(self, cmd, want, timeout=5.0):
        self.buf = bytearray()
        self.func = cmd[1]
        self.want = want
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

    async def read(self, slave, addr):
        resp, err = await self._txn(read_cmd(slave, addr), want=7)
        if err:
            return None, err
        return int.from_bytes(resp[3:5], "big"), None

    async def write(self, slave, addr, val):
        resp, err = await self._txn(write_cmd(slave, addr, val), want=8)
        if err:
            return None, err
        echoed = int.from_bytes(resp[4:6], "big")
        return echoed, None


async def restore_ems(conn, slave, original):
    if original is None:
        return
    await conn.write(slave, EMS_CTRL_MODE, original)
    await asyncio.sleep(1.0)


async def run(args):
    print("Scanning ...")
    dev = await BleakScanner.find_device_by_address(args.mac, timeout=15)
    if dev is None:
        raise SystemExit(
            'Device not found. Turn OFF "Hold Bluetooth connection" in Home '
            "Assistant and try again."
        )
    print("Connecting ...")
    client = await establish_connection(
        BleakClientWithServiceCache, dev, dev.name or "Bluetti", max_attempts=5
    )
    conn = Conn(client)
    await client.start_notify(NOTIFY_UUID, conn.on_notify)
    print("Connected.\n")

    reg = args.reg
    try:
        # --- snapshot ---
        orig, err = await conn.read(args.slave, reg)
        ems, ems_err = await conn.read(args.slave, EMS_CTRL_MODE)
        print(f"register {reg}          : {orig}" + (f"  ({err})" if err else ""))
        print(f"EMS_CTRL_MODE (2241)  : {ems}" + (f"  ({ems_err})" if ems_err else ""))

        if orig is None:
            raise SystemExit(f"Could not read register {reg} - aborting.")

        testval = args.value if args.value is not None else orig + 100
        if testval == orig:
            testval = orig + 1
        print(f"\nWill test writing {reg} = {testval} (original {orig}); "
              f"restores after each strategy.\n")

        if args.dry:
            print("--dry: read-only, nothing written.")
            return 0

        async def try_strategy(name, pre, slave_for_write, restore_pre=None):
            # pre: list of (addr, value) to write first; slave_for_write: slave id
            print(f"--- {name}")
            for a, v in pre:
                ev, ee = await conn.write(args.slave, a, v)
                print(f"      pre-write {a}={v}: " + (ee or f"echoed {ev}"))
            await asyncio.sleep(0.5)
            ev, ee = await conn.write(slave_for_write, reg, testval)
            print(f"      write {reg}={testval} @slave{slave_for_write}: "
                  + (ee or f"echoed {ev}"))
            await asyncio.sleep(args.wait)
            back, be = await conn.read(args.slave, reg)
            if be:
                # maybe value lives on the write slave
                back, be = await conn.read(slave_for_write, reg)
            stuck = (back == testval)
            print(f"      read back: {back}  ->  "
                  + ("PERSISTED ***" if stuck else "reverted")
                  + (f"  ({be})" if be else ""))
            # restore original
            for a, v in (restore_pre or pre):
                await conn.write(args.slave, a, v)
            await conn.write(slave_for_write, reg, orig)
            await asyncio.sleep(args.wait)
            chk, _ = await conn.read(args.slave, reg)
            print(f"      restored to {orig}: now {chk}\n")
            return stuck

        results = {}
        results["plain @slave1 (control)"] = await try_strategy(
            "plain write, slave 1 (fork's current behaviour)", [], 1)

        results["EMS off (2241=0) then write"] = await try_strategy(
            "EMS control OFF, then write", [(EMS_CTRL_MODE, 0)], 1,
            restore_pre=[(EMS_CTRL_MODE, ems if ems is not None else 0)])

        results["EMS on (2241=8) then write"] = await try_strategy(
            "EMS control ON, then write", [(EMS_CTRL_MODE, 8)], 1,
            restore_pre=[(EMS_CTRL_MODE, ems if ems is not None else 0)])

        if args.try_slave0:
            results["write @slave0"] = await try_strategy(
                "plain write, slave 0", [], 0)

        if args.try_event:
            print("--- write then CTRL_EVENT(2006)=1 commit pulse")
            ev, ee = await conn.write(1, reg, testval)
            print(f"      write {reg}={testval}: " + (ee or f"echoed {ev}"))
            await conn.write(1, CTRL_EVENT, 1)
            print("      CTRL_EVENT=1 sent")
            await asyncio.sleep(args.wait)
            back, be = await conn.read(args.slave, reg)
            stuck = (back == testval)
            print(f"      read back: {back}  ->  "
                  + ("PERSISTED ***" if stuck else "reverted"))
            await conn.write(1, reg, orig)
            results["write + CTRL_EVENT commit"] = stuck
            print()

        # restore EMS to what it was
        await restore_ems(conn, args.slave, ems)

        print("================ SUMMARY ================")
        for k, v in results.items():
            print(f"  {'PERSISTED' if v else 'reverted '}  {k}")
        winners = [k for k, v in results.items() if v]
        print()
        if winners:
            print("Missing step found:", "; ".join(winners))
        else:
            print("Nothing persisted. The gate is something else - likely the "
                  "settings slave address (try --try-slave0), a sub-device node "
                  "address, or a mode this register is locked under.")
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
    p.add_argument("-m", "--mac", required=True, help="Device address (bluetti-scan)")
    p.add_argument("-r", "--reg", type=int, default=2215,
                   help="Target register (default 2215 = grid export/feed max power)")
    p.add_argument("-v", "--value", type=int,
                   help="Test value (default: original + 100)")
    p.add_argument("-s", "--slave", type=int, default=1,
                   help="Slave address for reads/baseline (default 1)")
    p.add_argument("--wait", type=float, default=4.0,
                   help="Seconds to wait before reading back (default 4)")
    p.add_argument("--try-slave0", action="store_true",
                   help="Also test writing at slave 0")
    p.add_argument("--try-event", action="store_true",
                   help="Also test a CTRL_EVENT(2006)=1 commit pulse")
    p.add_argument("--dry", action="store_true", help="Read-only, write nothing")
    args = p.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
