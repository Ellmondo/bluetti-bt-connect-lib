#!/usr/bin/env python3
"""Dump grid import/export registers at BOTH slaves, sweep nearby, and optionally
test an import write. Helps explain why Max Grid Import reads unavailable.

    source ~/bluetti-venv/bin/activate
    python probe_grid.py --mac 601401B1-73F3-EB4F-47C5-780F4E959316
    python probe_grid.py --mac <addr> --test-import 2000   # write import power=2000 @slave0, watch, restore

Turn OFF "Hold Bluetooth connection" in Home Assistant first.
"""

import argparse, asyncio, sys, time
import crcmod.predefined
from bleak import BleakScanner
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

NOTIFY_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"
crc16 = crcmod.predefined.mkCrcFun("modbus")
EXC = {0x01:"illegal function",0x02:"illegal data address",0x03:"illegal data value",
       0x04:"server device failure",0x06:"server busy"}

GRID = [
    (2207, "charge_from_grid_enabled"),
    (2213, "max_grid_import_power  (W)"),
    (2214, "max_grid_import_current(A)"),
    (2208, "grid_export_enabled"),
    (2215, "max_grid_export_power  (W)"),
    (2216, "max_grid_export_current(A)"),
    (2005, "working_mode"),
    (2241, "ems_control (8=AI on)"),
]

def framed(p): return p + crc16(p).to_bytes(2,"little")
def read_cmd(s,a,q=1): return framed(bytes([s,3])+a.to_bytes(2,"big")+q.to_bytes(2,"big"))
def write_cmd(s,a,v): return framed(bytes([s,6])+a.to_bytes(2,"big")+v.to_bytes(2,"big"))

class Conn:
    def __init__(self, c): self.c=c; self.buf=bytearray(); self.fut=None; self.want=0; self.func=0
    def on_notify(self,_,d):
        self.buf.extend(d)
        if self.fut is None or self.fut.done(): return
        if len(self.buf)>=2 and self.buf[1]==(self.func|0x80) and len(self.buf)>=5: self.fut.set_result(bytes(self.buf))
        elif len(self.buf)>=self.want: self.fut.set_result(bytes(self.buf))
    async def _txn(self,cmd,want,timeout=4.0):
        self.buf=bytearray(); self.func=cmd[1]; self.want=want
        self.fut=asyncio.get_running_loop().create_future()
        await self.c.write_gatt_char(WRITE_UUID,cmd)
        try: r=await asyncio.wait_for(self.fut,timeout=timeout)
        except asyncio.TimeoutError: return None,"no resp"
        if len(r)>=3 and r[1]==(self.func|0x80): return None,f"exc0x{r[2]:02x}"
        if r[-2:]!=crc16(r[:-2]).to_bytes(2,"little"): return None,"crc"
        return r,None
    async def read(self,a,s):
        r,e=await self._txn(read_cmd(s,a),7); return (None,e) if e else (int.from_bytes(r[3:5],"big"),None)
    async def write(self,a,v,s):
        r,e=await self._txn(write_cmd(s,a,v),8); return (None,e) if e else (int.from_bytes(r[4:6],"big"),None)

def fmt(v,e): return (f"{v}" if v is not None else f"-({e})")

async def run(args):
    print("Scanning ..."); dev=await BleakScanner.find_device_by_address(args.mac,timeout=15)
    if dev is None: raise SystemExit('Device not found. Turn OFF "Hold Bluetooth connection" in HA.')
    print("Connecting ..."); client=await establish_connection(BleakClientWithServiceCache,dev,dev.name or "Bluetti",max_attempts=5)
    conn=Conn(client); await client.start_notify(NOTIFY_UUID,conn.on_notify); print("Connected.\n")
    try:
        print(f"{'reg':>5}  {'slave1':>10}  {'slave0':>10}   field")
        print("-"*60)
        for reg,label in GRID:
            v1,e1=await conn.read(reg,1); v0,e0=await conn.read(reg,0)
            print(f"{reg:>5}  {fmt(v1,e1):>10}  {fmt(v0,e0):>10}   {label}")
        print("\n--- sweep 2209..2220 (raw, slave1 / slave0) ---")
        for reg in range(2209,2221):
            v1,e1=await conn.read(reg,1); v0,e0=await conn.read(reg,0)
            print(f"{reg:>5}  {fmt(v1,e1):>10}  {fmt(v0,e0):>10}")
        if args.test_import is not None:
            reg=2213; orig,_=await conn.read(reg,1); tv=args.test_import
            print(f"\n=== write import power {reg}={tv} @slave0 (was {orig}) ===")
            ev,ee=await conn.write(reg,tv,0); print("  write @slave0: "+(ee or f"echoed {ev}"))
            t0=time.monotonic()
            while True:
                v,_=await conn.read(reg,1); dt=time.monotonic()-t0
                print(f"  {dt:4.1f}s @slave1: {v}")
                if dt>=20: break
                await asyncio.sleep(5)
            if orig is not None: await conn.write(reg,orig,0)
            print("  restored")
    finally:
        try: await client.stop_notify(NOTIFY_UUID)
        except Exception: pass
        await client.disconnect(); print('\nDisconnected. Turn "Hold Bluetooth connection" back on in HA.')
    return 0

def main():
    p=argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("-m","--mac",required=True)
    p.add_argument("--test-import",type=int)
    return asyncio.run(run(p.parse_args()))

if __name__=="__main__": sys.exit(main())
