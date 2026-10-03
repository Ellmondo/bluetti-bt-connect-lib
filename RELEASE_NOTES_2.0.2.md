# bluetti-bt-connect-lib 2.0.2

Adds two raw, read-only registers to the EP2000 to look for the battery pack
temperature, which nothing on this device has exposed so far. No other
behaviour changes.

## Why

A Modbus TCP read of an EP2000 (bluetti-community/bluetti-registers#42) shows
a pack average temperature, `b_t_avg` (51224), whose unit is in doubt - °C,
°C with an offset, or °F. Reading the same quantity over Bluetooth at the same
moment settles it. The BLUETTI app's register list points at two candidates:

| field | register | where |
|---|---|---|
| `raw_register_6007` | 6007 | pack main-info block (6000+) |
| `raw_register_6115` | 6115 | directly after pack SOH (6114) |

Both are reported **exactly as the device sends them** - no scaling, offset
or bounds - and named by address, because what they hold is not confirmed.

## How they are read safely

Neither address had been read on this device before. A device can answer an
address it does not serve with silence instead of an error, and a silent
register inside an ordinary read would time out and fail the whole poll. So
these use a new `ProbeUIntField`:

- **Never merged into grouped reads.** Each is read on its own, after
  everything else in the poll.
- **A refusal or a timeout only drops that register.** The rest of the poll is
  unaffected, and the register is not asked for again until the integration
  restarts - an unserved address costs one failed request, not one per poll.
- **A real connection failure still aborts the poll as before.**

Read-only: nothing is written to the device. Reads use slave 1, like every
other read.
