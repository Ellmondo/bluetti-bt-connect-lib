# bluetti-bt-connect-lib 2.0.6

## Fixed: EP2000 pack temperature is °C + 40, not °F

`pack_temperature` (6115) is now decoded as **raw − 40, in °C**. This is
how BLUETTI's own app decodes it: the pack item block's average temperature,
and the same for 6007, the cell NTCs and the inverter's temperatures. 2.0.4
read it as °F based on a fit against air temperature, and the vendor decoding
replaces that. A raw 66 now reads 26 °C, where 2.0.4 showed 18.9 °C.

New field type `OffsetIntField` (raw + a fixed offset) carries it.

## New: fields read from another slave

A field can now be read from a slave other than 1 with `.at_slave(n)`:

```python
SInt32Field(FieldName.HOME_LOAD_POWER, 142).at_slave(0)
```

Reads are grouped per slave and never mixed in one request. A response is
only matched against fields of the slave that answered, so the same address
can be read from two slaves side by side. `ReadableRegisters.slave` and
`BluettiDevice.parse(..., slave=)` carry it through. With `raw=True`, results
from a slave other than 1 are keyed `(slave, address)`.

## New: EP2000 home data from the EBOX (slave 0)

The inverter (slave 1) leaves most of the home data block at 0. The EBOX
(slave 0) fills it in. Read from there, all in one request (142, 23
registers):

| field | register | unit |
|---|---|---|
| `home_load_power` | 142 (s32) | W |
| `home_consumption_energy` | 152 (u32 ×0.1) | kWh |
| `solar_energy` | 154 (u32 ×0.1) | kWh |
| `grid_import_energy` | 156 (u32 ×0.1) | kWh |
| `grid_export_energy` | 158 (u32 ×0.1) | kWh |
| `self_sufficiency` | 164 | % |

The layout comes from BLUETTI's app. The energy totals were checked against
the app's lifetime statistics on a real system. They are 32-bit, low word
first, so they keep counting past 6553.5 kWh.

This also brings back the consumption and grid feed-in totals that 2.0.5
removed: they were 0 because they were being read from the inverter.
