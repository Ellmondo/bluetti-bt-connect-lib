# bluetti-bt-connect-lib 2.0.4

## EP2000

- **Pack temperature** (`pack_temperature`, register 6115). Reported in
  **°F**, exactly as the device sends it, with the unit declared so Home
  Assistant converts it to each user's own unit. Signed.

  The unit was settled in bluetti-community/bluetti-registers#42. Over an
  idle day the raw value tracked a nearby air sensor at about 1.7 per °C and
  stayed a few degrees below it in shade. That fits °F; °C + 40 would have
  needed the idle pack to run warmer than the air. It also matches a Modbus
  TCP reading against a thermal camera on another EP2000, and BLUETTI's
  documented -40..160 range. 6115 now rides in the normal grouped pack read.

- **Connected devices** (`connected_devices`), counted from the battery's
  own node list at 21002. It replaces `total_node_count` (21001), which was
  always 0 and was never a count. The count reads four entries, so a system
  with more than four devices reports four.

- **Removed:** the raw probe registers 6007 and 6115 from 2.0.2. 6115 became
  the pack temperature; 6007 holds the same value on a single-pack system.

## Node list

`parse_node_list()` and `Node` decode the NODE_INFO block: one 8-word entry
per device, with its Modbus slave address, 64-bit serial and model code.
`DeviceReader.read_nodes()` reads it. Decoded against a real system:

| slave | model | device |
|---|---|---|
| 0 | 3004 | EBOX - the settings controller that writes go to |
| 1 | 1004 | EP2000 inverter |
| 41 | 4001 | HV800 battery pack |

## Raw reads at other slaves

`DeviceReader.read_raw(address, count, slave=1)` can now read at another
slave address. It is still function 3 only. Choosing which slaves are
safe to ask is left to the caller; the integration only allows slaves that
appear in the node list.
