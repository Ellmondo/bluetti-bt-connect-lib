# bluetti-bt-connect-lib 2.0.3

Adds `DeviceReader.read_raw(address, count)`: a one-off, read-only read of up
to 32 registers, for exploring addresses a device definition does not cover.
No change to polling or writes.

- **Read-only.** It only ever sends Modbus function 3, at the read slave.
- **Shares the polling lock and connection**, so it never interleaves with a
  poll or a write.
- **Refusal and silence are results, not exceptions.** It returns a
  `RawReadResult` whose `outcome` is `ok`, `refused` (with the Modbus
  exception code), `no_reply`, `not_connected` or `error`. Exploring means
  asking for addresses the device may not serve, and neither answer says
  anything is wrong with the link.
- `RawReadResult.as_dict()` gives each word unsigned, signed and in hex.
- Bounds are enforced: 1 to `MAX_RAW_READ_COUNT` (32) registers, within
  0-65535.

Used by bluetti-bt-connect 2.0.4's `read_registers` action.
