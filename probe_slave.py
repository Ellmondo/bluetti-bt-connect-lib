#!/usr/bin/env python3
"""Test whether protected settings must be written to Modbus slave 0.

The device echoes writes at slave 1 (the inverter) but keeps snapping the value
back to an enforced setpoint - so the real setpoint lives elsewhere. The app
writes settings to getSettingsSlaveAddr(), which is 0 for 2nd-generation IoT
devices. This writes at slave 0 and checks whether the value then persists
(reading back at both slave 0 and slave 1).

    source ~/bluetti-venv/bin/activate
    python probe_slave.py --mac 601401B1-73F3-EB4F-47C5-780F4E959316
    python probe_slave.py --mac <addr> --reg 2005 --value 4   # working mode

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

def framed(p): return p + crc16(p).to_bytes(2,"little")
def read_cmd(s,a,q=1): return framed(bytes([s,3])+a.to_bytes(2,"big")+q.to_bytes(2,"big"))
def write_cmd(s,a,v): return framed(bytes([s,6])+a.to_bytes(2,"big")+v.to_bytes(2,"big"))

class Conn:
    def __init__(self, client):
        self.client=client; self.buf=bytearray(); self.fut=None; self.want=0; self.func=0
    def on_notify(self,_,data):
        self.buf.extend(data)
        if self.fut is None or self.fut.done(): return
        if len(self.buf)>=2 and self.buf[1]==(self.func|0x80) and len(self.buf)>=5:
            self.fut.set_result(bytes(self.buf))
        elif len(self.buf)>=self.want:
            self.fut.set_result(bytes(self.buf))
    async def _txn(self,cmd,want,timeout=4.0):
        self.buf=bytearray(); self.func=cmd[1]; self.want=want
        self.fut=asyncio.get_running_loop().create_future()
        await self.client.write_gatt_char(WRITE_UUID,cmd)
        try: resp=await asyncio.wait_for(self.fut,timeout=timeout)
        except asyncio.TimeoutError: return None,"no response"
        if len(resp)>=3 and resp[1]==(self.func|0x80): return None,f"refused 0x{resp[2]:02x} ({EXC.get(resp[2],'?')})"
        if resp[-2:]!=crc16(resp[:-2]).to_bytes(2,"little"): return None,"bad CRC"
        return resp,None
    async def read(self,addr,slave):
        r,e=await self._txn(read_cmd(slave,addr),7)
        return (None,e) if e else (int.from_bytes(r[3:5],"big"),None)
    async def write(self,addr,val,slave):
        r,e=await self._txn(write_cmd(slave,addr,val),8)
        return (None,e) if e else (int.from_bytes(r[4:6],"big"),None)

async def watch(conn,reg,want,secs=20,interval=5):
    out=[]; held=True; t0=time.monotonic()
    while True:
        v1,_=await conn.read(reg,1)
        dt=time.monotonic()-t0
        out.append((round(dt,1),v1))
        if v1!=want: held=False
        if dt>=secs: break
        await asyncio.sleep(interval)
    return out,held

async def run(args):
    print("Scanning ..."); dev=await BleakScanner.find_device_by_address(args.mac,timeout=15)
    if dev is None: raise SystemExit('Device not found. Turn OFF "Hold Bluetooth connection" in HA.')
    print("Connecting ..."); client=await establish_connection(BleakClientWithServiceCache,dev,dev.name or "Bluetti",max_attempts=5)
    conn=Conn(client); await client.start_notify(NOTIFY_UUID,conn.on_notify); print("Connected.\n")
    reg=args.reg
    try:
        r1,e1=await conn.read(reg,1); r0,e0=await conn.read(reg,0)
        print(f"read {reg} @slave1: {r1}" + (f" ({e1})" if e1 else ""))
        print(f"read {reg} @slave0: {r0}" + (f" ({e0})" if e0 else ""))
        base = r1 if r1 is not None else r0
        if base is None: raise SystemExit("Could not read the register at either slave.")
        testval = args.value if args.value is not None else base+100
        if testval==base: testval=base+1
        print(f"\nTest value {testval} (current {base}).")

        print("\n=== WRITE @ SLAVE 0, then watch @slave1 for 20s ===")
        ev,ee=await conn.write(reg,testval,0)
        print(f"  write {reg}={testval} @slave0: " + (ee or f"echoed {ev}") + "  (no echo is normal for slave 0)")
        traj,held0=await watch(conn,reg,testval,20,5)
        print("  @slave1 trajectory: " + "  ".join(f"{t}s:{v}" for t,v in traj))
        r0b,_=await conn.read(reg,0); print(f"  read back @slave0: {r0b}")
        print("  => " + ("PERSISTED via slave 0 ***" if held0 else "reverted"))
        # restore via slave 0
        await conn.write(reg,base,0); await asyncio.sleep(3)

        print("\n=== control: WRITE @ SLAVE 1, watch 20s ===")
        ev,ee=await conn.write(reg,testval,1)
        print(f"  write {reg}={testval} @slave1: " + (ee or f"echoed {ev}"))
        traj,held1=await watch(conn,reg,testval,20,5)
        print("  @slave1 trajectory: " + "  ".join(f"{t}s:{v}" for t,v in traj))
        print("  => " + ("persisted" if held1 else "reverted (as before)"))
        await conn.write(reg,base,1); await asyncio.sleep(2)

        print("\n================ SUMMARY ================")
        print(f"  slave 0 write: {'PERSISTED' if held0 else 'reverted'}")
        print(f"  slave 1 write: {'persisted' if held1 else 'reverted'}")
        if held0 and not held1:
            print("\n>>> The fix is to write settings at slave 0. I'll wire a configurable settings slave into the lib.")
        elif held1:
            print("\n>>> Slave 1 held this time - persistence is device-state dependent, needs more thought.")
        else:
            print("\n>>> Neither slave held. The setpoint is enforced by something else (mode/enable).")
    finally:
        try: await client.stop_notify(NOTIFY_UUID)
        except Exception: pass
        await client.disconnect(); print('\nDisconnected. Turn "Hold Bluetooth connection" back on in HA.')
    return 0

def main():
    p=argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("-m","--mac",required=True); p.add_argument("-r","--reg",type=int,default=2215)
    p.add_argument("-v","--value",type=int)
    return asyncio.run(run(p.parse_args()))

if __name__=="__main__": sys.exit(main())
