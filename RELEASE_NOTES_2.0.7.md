# bluetti-bt-connect-lib 2.0.7

Everything in this release was decoded the way BLUETTI's own app decodes it,
and checked against a real EP2000 + EBOX + HV800. All new fields are
read-only.

## EP2000

**Working mode 11.** `WorkingMode.SELF_CONSUMPTION_EXPORT` (self-consumption
with export) is now known. BLUETTI's app offers it only on the EP2000 and
EP19K. Before this, the working mode read as unknown whenever it was set.

**From the inverter (slave 1)**

| field | register | notes |
|---|---|---|
| `ems_control_mode` | 2241, low nibble | `EmsControlMode`: LOCAL 0, CLOUD 3, LOCAL_SELECTED 4, DYNAMIC_PRICING 5, VPP 7, AI 8. `CLOUD_CONTROLLED_EMS_MODES` lists 3/5/7 |
| `firmware_arm`, `firmware_dsp` | software list at 1112 | e.g. "5032.22" |

**From the EBOX (slave 0)**

| field | register | notes |
|---|---|---|
| `battery_status` | 103 | `BatteryStatus`: IDLE, CHARGING, DISCHARGING |
| `time_remaining_minutes` | 104 | minutes to full or to empty (the EBOX reports one value in both registers) |
| `active_alarms` | 122–138 | active warnings and faults as text, e.g. "B104 PV2 Voltage Low", or "None" |
| `alarm_count` | 122–138 | number of active warnings and faults |
| `inverter_status` | 161 | `InverterStatus`: OFF, OFF_GRID, GRID_BYPASS, GRID_CONNECTED, GRID_CONNECTED_CHARGING, GRID_CONNECTED_DISCHARGING, ERROR, OFF_GRID_ABNORMAL |
| `system_error` | 174, bits 5/6/7/10 | IoT, BMS, other or meter error flag |
| `ac_pv_power`, `ac_pv_l1/l2/l3_power`, `ac_pv_l1/l2/l3_voltage` | PV slots 3–5 (1226, 1234, 1242) | AC-coupled PV (for example Enphase) through the AC PV meter. Only reported for slots of type 101; 0 W without a meter |
| `time_control_enabled` | 2029 | the schedule used by Custom mode |
| `schedule_slot_1` … `_6` | 2030 + 3n | e.g. "Charge 11:01-13:59", "Discharge 18:00-21:00", "Off" |
| `max_charge_current`, `max_discharge_current` | 6011, 6012 | BMS limits, A |
| `firmware_iot` | 11014 | e.g. "9052.26" |
| `cloud_connected` | 11018, bit 6 | the EBOX's MQTT link to BLUETTI's cloud |
| `wifi_signal` | 11026 | dBm (low byte − 256) |

Alarm texts come from the app's own tables. Table B is used for high-power
inverters (register 122 = 3) and table E otherwise; see
`fields/alarm_codes.py`. A bit with no table entry is shown as `R<register>.<bit>`.

## New field types

`MaskedEnumField`, `BitMaskField`, `LowByteOffsetField`,
`FirmwareVersionField`, `U32VersionField`, `ScheduleSlotField`,
`AlarmListField` / `AlarmCountField`, `AcPvSlotField` / `AcPvTotalField`.

## Polling

The EP2000 poll grows from 20 to 28 requests. The eight new ones go to the
EBOX and cover only ranges a real unit was confirmed to serve.
