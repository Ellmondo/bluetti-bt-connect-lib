# bluetti-bt-connect-lib 2.0.5

## EP2000

Removed three energy totals that never reported anything on the EP2000:

| field | register |
|---|---|
| `total_ac_consumption` | 152 |
| `total_grid_feed` | 158 |
| `power_generation` | 1202 |

All three read a flat 0 through more than a week of normal running,
including days of solar generation, in Home Assistant history and in direct
register reads. They aren't scaled or offset wrongly. The registers simply
don't hold those totals on this model.

`total_ac_consumption` and `total_grid_feed` were only used by the EP2000,
so their names are gone from `FieldName`. `power_generation` stays, because
the AC2A, AC2P, EP600 and AC300 still read it from their own registers.

For kWh totals, use Home Assistant's Integral helper on the power sensors,
such as Total PV Power for solar generation.
