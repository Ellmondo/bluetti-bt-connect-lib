# bluetti-bt-connect-lib 2.0.8

## Fixed: EP2000 active cell count

`active_cell_count` read register 6153, which holds the pack's number of
temperature sensors (NTCs), not cells. On a seven-B700 HV800 stack it showed
112 instead of 224. BLUETTI's app reads three counts side by side:

| register (low byte) | count | example |
|---|---|---|
| 6152 | cells | 224 |
| 6153 | temperature sensors (NTCs) | 112 |
| 6154 | battery modules (BMUs, one per B700) | 7 |

`active_cell_count` now reads 6152. A new `temperature_sensor_count` field
reads 6153. `battery_stack_count` (6154) is unchanged and is the
battery-module count. All three are read in one request.
