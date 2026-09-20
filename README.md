# bluetti-bt-connect-lib

> **This is a fork** of [bluetti-bt-lib](https://github.com/Patrick762/bluetti-bt-lib) by [Patrick762](https://github.com/Patrick762), extended with additional device support, register corrections, and new writable fields for the Bluetti EP2000. All credit for the original protocol reverse-engineering, architecture, and core library design goes to Patrick762 and the project's other contributors. This fork exists to track device-specific fixes and additions on a faster iteration cycle; where possible, improvements are intended to be contributed back upstream.
>
> Original repository: https://github.com/Patrick762/bluetti-bt-lib
>
> Additional credit to [atiweb/hassio-bluetti-bt](https://github.com/atiweb/hassio-bluetti-bt), a separate fork of the original project, cross-referenced for two specific fixes: correcting `consumption_power_all`, `pv_input_power_all`, and `grid_power_all` from incorrectly-assumed 32-bit fields to plain 16-bit fields (validated against real captured data), and the pattern for proper Modbus response validation (CRC checking and exception-response detection) now used in `device_reader.py`.

Inofficial Library for basic communication to bluetti powerstations.
Core functions based on https://github.com/warhammerkid/bluetti_mqtt

## Disclaimer
This library is provided without any warranty or support by Bluetti. I do not take responsibility for any problems it may cause in all cases. Use it at your own risk.

## ⚠️ EP2000: grid/mode controls carry real risk - read before using

**AC Output, Charge From Grid, Grid Export, Working Mode, and all four grid import/export power and current limits remain writable in this build.** Before you rely on any of them, please understand what we found while investigating this device.

**The core problem:** writes into this device's grid-related register block can get a clean, protocol-valid acknowledgment from the device - and then the change does not actually take effect. This was confirmed at the raw byte level, ruling out a simple wrong-address or scaling issue. In practice this means: **you may set a limit in Home Assistant, see it accepted with no error, and the device may still be running on its old setting.** Nothing in the app or the integration will reliably tell you a write didn't stick - the failure is silent. Do not assume a control has taken effect on the device just because Home Assistant shows no error; if you change one of these settings, verify the result independently (in the Bluetti app, or against real grid behavior) before relying on it.

**Update (v1.7.0) - the mechanism, more precisely.** Further investigation narrowed this down. A BLE write is not lost, it is *staged*: it applies only when the official Bluetti app's settings screen initialises, which triggers a commit to the device over the vendor's cloud/MQTT channel. A change made while the app is already open does not apply until the app is closed and reopened. This was confirmed against Bluetti's own per-device register map (pulled from their cloud) and verified with a live oracle - our BLE read of a register agreeing exactly with the value their cloud API reports. It means the practical workaround is real: set a value in Home Assistant, then open the Bluetti app to flush it. It also means **Working Mode now writes to register 2005** (this release), which is where Bluetti actually places it - the previous mapping used 2013, which is the device *power on/off* control, so selecting a mode there was issuing a power command. Cloud control of Working Mode and Power does work in Bluetti's own official Home Assistant integration; grid import/export limits are not exposed on that cloud channel at all and remain reachable only through the app.

**Why we believe this happens:** a research pass across comparable BLE-connected solar/battery projects (EcoFlow, Renogy, Growatt, Deye/Sunsynk, Anker SOLIX, Marstek, several open-source BMS forks) found that grid-facing settings - export/import limits, working mode, grid protection - are consistently gated behind some form of vendor authentication across the entire industry, not just on Bluetti hardware: a cloud-account round-trip, a licensed BLE encryption handshake keyed to the device's serial number, or a support-issued password. The EP2000 fits this pattern - there's a genuine "Pro Mode" authentication layer here, and while we confirmed the universal technician password Bluetti documents publicly ("88888888"), simply knowing that password did not make writes persist, which points at a session or encryption-level gate underneath it that hasn't been reverse-engineered.

**Why we haven't removed these controls outright:** unlike the grid-compliance layer itself, some of these fields (notably the AC Output and Grid Export switches, and Max Grid Export Current) were live-tested and confirmed to actually take effect on this specific unit at various points during development. Reliability may vary by field, by firmware version, and possibly by unit - which is exactly why blanket trust in any of them is the wrong approach. Treat every write as unverified until you've checked its real-world effect yourself.

**Grid export and grid-protection parameters are regulated for interconnection safety in most jurisdictions** (anti-islanding, voltage/frequency ride-through). Changing them, even successfully, may have real compliance implications depending on where you live and how your system is set up. This is worth knowing regardless of whether a given write actually persists.

**If you're an advanced user or researcher**: the full research writeup and the exact register-level evidence behind the above are referenced in this version's release notes. The realistic next step for confirming or defeating the authentication gate isn't more register-guessing - it's capturing the official app's authenticated write sequence directly (Android Bluetooth HCI snoop log, or hooking the app's write call with Frida).

## Projects using this library

- [Bluetti BT Connect - Home Assistant Integration](https://github.com/Ellmondo/bluetti-bt-connect) (this fork's companion integration)
- [Original Home Assistant Integration](https://github.com/Patrick762/hassio-bluetti-bt)
- [UPS Server (NUT compatible)](https://github.com/Patrick762/nut-server-bluetti)

## Supported Powerstations and data

Validated

|Device Name|total_battery_percent|dc_input_power|ac_input_power|dc_output_power|ac_output_power|
|-----------|---------------------|--------------|--------------|---------------|---------------|
|AC70       |✅                   |✅            |✅            |✅             |✅             |
|AC180      |✅                   |✅            |✅            |✅             |✅             |
|EB3A       |✅                   |✅            |✅            |✅             |✅             |
|EP600      |✅                   |PV            |Grid          |❌             |AC Phases      |
|EP2000     |✅                   |PV            |Grid          |❌             |AC Phases, writable grid/mode fields (⚠️ see warning above)|
|Handsfree 1|✅                   |✅            |✅            |✅             |✅             |

Added and mostly validated by contributors (some are moved here from the HA Integration https://github.com/Patrick762/hassio-bluetti-bt):


|Device Name|Contributor                                                                        |total_battery_percent|dc_input_power|ac_input_power|dc_output_power|ac_output_power|
|-----------|-----------------------------------------------------------------------------------|---------------------|--------------|--------------|---------------|---------------|
|AC2A       |[@ruanmed](https://github.com/ruanmed)                                             |✅                   |✅            |✅            |✅             |✅             |
|AC50B      |[@goetzc](https://github.com/goetzc)                                               |✅                   |❌            |✅            |✅             |✅             |
|AC60       |[@mzpwr](https://github.com/mzpwr)                                                 |✅                   |✅            |✅            |✅             |✅             |
|AC60P      |[@mzpwr](https://github.com/mzpwr)                                                 |✅                   |✅            |✅            |✅             |✅             |
|AC70P      |[@matthewpucc](https://github.com/matthewpucc)                                     |✅                   |✅            |✅            |✅             |✅             |
|AC180P     |@Patrick762                                                                        |✅                   |✅            |✅            |✅             |✅             |
|AC200L     |bluetti-mqtt                                                                       |✅                   |✅            |✅            |✅             |✅             |
|AC200M     |bluetti-mqtt                                                                       |✅                   |✅            |✅            |✅             |✅             |
|AC200PL    |[@0x4E4448](https://github.com/0x4E4448)                                           |✅                   |✅            |✅            |✅             |✅             |
|AC300      |bluetti-mqtt                                                                       |✅                   |✅            |✅            |✅             |✅             |
|AC500      |bluetti-mqtt                                                                       |✅                   |✅            |✅            |✅             |✅             |
|AP300      |[@seaburger](https://github.com/seaburger), [@sidieje](https://github.com/sidieje) |✅                   |✅            |✅            |✅             |✅             |
|EL30V2     |[@dgudim](https://github.com/dgudim)                                               |✅                   |✅            |✅            |✅             |✅             |
|EL100V2    |[@seaburger](https://github.com/seaburger)                                         |✅                   |✅            |✅            |✅             |✅             |
|EP500      |bluetti-mqtt                                                                       |✅                   |✅            |✅            |✅             |✅             |
|EP500P     |bluetti-mqtt                                                                       |✅                   |✅            |✅            |✅             |✅             |
|EP760      |[@Apfuntimes](https://github.com/Apfuntimes)                                       |✅                   |PV            |Grid          |❌             |AC Phases      |
|EP800      |[@jhagenk](https://github.com/jhagenk)                                             |✅                   |❌            |❌            |❌             |❌             |
|PR30V2     |@gentoo90                                                                          |✅                   |✅            |✅            |✅             |✅             |
|PR100V2    |shares PR30V2 register layout (pending validation)                                 |✅                   |✅            |✅            |✅             |✅             |

## Controls

Validated:

|Device Name|ctrl_ac|ctrl_dc|
|-----------|-------|-------|
|EB3A       |✅     |✅     |

Added and mostly validated by contributors:
|Device Name|Contributor                                              |ctrl_ac|ctrl_dc|ctrl_ups_mode|soc_range_start|soc_range_end|
|-----------|---------------------------------------------------------|-------|-------|-------------|---------------|-------------|
|AC200L     |bluetti-mqtt, [@seaburger](https://github.com/seaburger) |✅     |✅     |✅           |❌             |❌           |
|EL30V2     |[@x3ccd4828](https://github.com/x3ccd4828)               |✅     |✅     |❌           |❌             |❌           |

## Battery pack data

|Device Name|voltage|battery_soc|cell_voltages|
|-----------|-------|-----------|-------------|
|AC300      |✅     |✅         |✅           |

## Installation

```bash
pip install bluetti-bt-connect-lib
```

## Commands for testing

Commands included in this library should only be used for testing.

### Scan for supported devices

```bash
usage: bluetti-scan [-h] [-r REGEX] [-s SCAN_TIME]

Detect bluetti devices by bluetooth name

options:
  -h, --help            show this help message and exit
  -r REGEX, --regex REGEX
                        Custom regex to match device name
  -s SCAN_TIME, --scan-time SCAN_TIME
                        How long to scan for devices (seconds)
```

Example output: `['EB3A', '00:00:00:00:00:00']`

### Detect device type by mac address

```bash
usage: bluetti-detect [-h] mac

Detect bluetti devices

positional arguments:
  mac         Mac-address of the powerstation

options:
  -h, --help  show this help message and exit
```

Example:

```bash
bluetti-detect 00:00:00:00:00:00
```

Example output: `Device type is 'EB3A' with iot version 1 and serial 0000000000000. Full name: EB3A0000000000000`

### Read device data for supported devices

```bash
usage: bluetti-read [-h] [-m MAC] [-t TYPE] [-e ENCRYPTION]

Detect bluetti devices

options:
  -h, --help            show this help message and exit
  -m MAC, --mac MAC     Mac-address of the powerstation
  -t TYPE, --type TYPE  Type of the powerstation (AC70 f.ex.)
  -e ENCRYPTION, --encryption ENCRYPTION
                        Add this if encryption is needed
```

Example:

```bash
bluetti-read -m 00:00:00:00:00:00 -t EB3A
```

Example output:
```bash
FieldName.DEVICE_TYPE: EB3A
FieldName.DEVICE_SN: 0000000000000
FieldName.BATTERY_SOC: 92%
FieldName.DC_INPUT_POWER: 0W
FieldName.AC_INPUT_POWER: 0W
FieldName.AC_OUTPUT_POWER: 0W
FieldName.DC_OUTPUT_POWER: 0W
FieldName.CTRL_AC: False
FieldName.CTRL_DC: True
FieldName.CTRL_LED_MODE: LedMode.OFF
FieldName.CTRL_POWER_OFF: False
FieldName.CTRL_ECO: False
FieldName.CTRL_ECO_TIME_MODE: EcoMode.HOURS1
FieldName.CTRL_CHARGING_MODE: ChargingMode.STANDARD
FieldName.CTRL_POWER_LIFTING: False
```

### Write to supported device

INFO: Devices with encryption are currently not supported!

```bash
usage: bluetti-write [-h] [-m MAC] [-t TYPE] [--on ON] [--off OFF] [-v VALUE] [-e ENCRYPTION] field

Write to bluetti device

positional arguments:
  field                 Field name (ctrl_dc f.ex.)

options:
  -h, --help            show this help message and exit
  -m MAC, --mac MAC     Mac-address of the powerstation
  -t TYPE, --type TYPE  Type of the powerstation (AC70 f.ex.)
  --on ON               Value to write
  --off OFF             Value to write
  -v VALUE, --value VALUE
                        Value to write (integer, see enum for value)
  -e ENCRYPTION, --encryption ENCRYPTION
                        Add this if encryption is needed
```

Example:

```bash
bluetti-write -m 00:00:00:00:00:00 -t EB3A --on on ctrl_ac
```

## Adding fields

To add new fields, you can use the `bluetti-detect` command to first find out which version of iot protocol is used and if it uses encryption.

After you got this information, you can use the `bluetti-readall` command to read every registry and save the data to a json file. You should also note all values you see in the app to later compare the data.

Here's how to use the `bluetti-readall` command:

```bash
usage: bluetti-readall [-h] [-m MAC] [-v VERSION] [-e ENCRYPTION]

Detect bluetti devices

options:
  -h, --help            show this help message and exit
  -m MAC, --mac MAC     Mac-address of the powerstation
  -v VERSION, --version VERSION
                        IoT protocol version
  -e ENCRYPTION, --encryption ENCRYPTION
                        Add this if encryption is needed
```

With the separate tool at [bluetti-bt-raw-reader](https://github.com/Patrick762/bluetti-bt-raw-reader) you can view those values in a more understandable way.

You can also share the output with me using [this form](https://forms.gle/ewp7DYigtaN3ZLc68)


To test added fields with the created json file, use `bluetti-parse`:

```bash
usage: bluetti-parse [-h] file

Parse readall output files

positional arguments:
  file        JSON file of the powerstation readall output

options:
  -h, --help  show this help message and exit
```
