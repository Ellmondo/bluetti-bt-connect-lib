# bluetti-bt-connect-lib 2.0.0

**Local write control of the Bluetti EP2000 (+ EBOX) works.** The long-standing
"a write is accepted and then silently reverts" problem is solved. Settings
written over local Bluetooth - grid import/export limits, working mode, the
switches - now persist. This is the headline of 2.0.

## TL;DR

- **The fix: writes go to Modbus slave 0, not slave 1.** On this 2nd-generation
  IoT device the inverter answers on slave 1, but the authoritative settings
  controller is on slave 0. A write to slave 1 was echoed by the inverter and
  then overwritten within a few seconds from the slave-0 setpoint. Writing to
  slave 0 makes it stick. Reads stay on slave 1 (they work and reflect slave-0
  writes after a few seconds).
- **New "EMS / AI Control Mode" switch** (register 2241). When on, Bluetti's AI
  actively manages the system and overrides manual settings; off = manual control.
- **Grid import entities now appear** - their read bounds were too low and were
  silently discarding the device's real values.
- **The v1.8.0 register-7 "unlock" experiment is removed** - it was a wrong turn
  (register 7 sets the Bluetooth password; it is not a session login).

## The story (why this took a while)

Writes into the EP2000's grid/mode registers came back with a clean, protocol-
valid acknowledgement and then didn't take effect. Earlier releases suspected a
cloud/MQTT commit step, a licensed BLE encryption handshake, or a "Pro Mode"
authentication gate, because that is the industry-wide pattern for grid-facing
settings. Several hypotheses were tested on real hardware and ruled out:

- **Register 7 "unlock"** (v1.8.0) - decompiling the app showed register 7 is the
  *set Bluetooth password* action from the settings screen, not a login. Writing
  to it did nothing for persistence. Removed.
- **EMS/AI control mode alone** - turning it off helped at slave 1 briefly but the
  value still reverted; not the root cause on its own.
- **A commit pulse** (`CTRL_EVENT` 2006, `CTRL_POWER_OUTPUT_STATE_SAVE` 2226) -
  the value still reverted after sending them.
- **A slow revert** - ruled in as a symptom; the value snapped back to an enforced
  setpoint within seconds.

The decisive test wrote the same register at **slave 0** and watched it: it held,
and read back correct at slave 0, propagating to the slave-1 reading after ~5s -
exactly the delay the official app shows before it opens its settings screen. The
app itself writes settings to `getSettingsSlaveAddr()`, which returns 0 for
2nd-generation IoT devices. Mystery solved: it was the slave address all along.

## Changes since 1.7.0

### Fixed
- **Settings writes now target Modbus slave 0 on the EP2000** so they persist.
  Added a configurable `BluettiDevice.write_slave_addr` (default 1, so no other
  device changes behaviour), threaded through `DeviceRegister`,
  `WriteableRegister` and `WriteableRegisters`; EP2000 sets it to 0.
- **Max Grid Import Power / Current now read correctly.** Their bounds were capped
  at 6600 W / 40 A - values taken from an earlier, lower app setting - so the
  device's real values (8600 W / 45 A) were being discarded by range validation
  and the entities showed unavailable. Raised to 9600 W / 50 A.
- **Working Mode stays at register 2005** (corrected in 1.6/1.7 from the old 2013,
  which is the device power on/off control).

### Added
- **`ValueSwitchField`** - a switch whose on/off states are arbitrary register
  values rather than 1/0.
- **EMS / AI Control Mode** field on the EP2000 (register 2241, on=8 / off=0),
  surfaced as a switch by the integration.
- **Standalone BLE diagnostics** at the repo root (`scan_addr.py`,
  `probe_slave.py`, `probe_grid.py`, `probe_writepath.py`, `probe_commit.py`) -
  raw-Modbus tools, no library import needed, used to find and confirm the fix.

### Removed
- The register-7 "unlock" feature added in 1.8.0 (`unlock.py`, the DeviceReader
  hook and config field, and its test). It never authorised anything.

### Verified register map (EP2000, against the app's `ProtocolAddrV2`)
`2005` working mode - `2213` grid import power (W) - `2214` grid import current (A)
- `2215` grid export power (W) - `2216` grid export current (A) - `2207` charge
from grid - `2208` grid export enable - `2241` EMS/AI control (8=on).

## Upgrading

`pip install -U bluetti-bt-connect-lib` (or let the companion Home Assistant
integration pull `==2.0.0`). After changing a setting, allow a few seconds for it
to settle before trusting the read-back. For manual control, keep AI Control Mode
**off**.

## Credits

Built on [bluetti-bt-lib](https://github.com/Patrick762/bluetti-bt-lib) by
[Patrick762](https://github.com/Patrick762) and the upstream contributors, with
`bluetti_mqtt` and [atiweb/hassio-bluetti-bt](https://github.com/atiweb/hassio-bluetti-bt)
cross-referenced for specific fixes. This release's EP2000 work is device-specific
and intended to feed back upstream where it generalises.
