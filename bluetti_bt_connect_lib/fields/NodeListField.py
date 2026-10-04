from dataclasses import dataclass
from typing import List

from . import DeviceField, FieldName


NODE_ENTRY_WORDS = 8
"""Words per node entry in the NODE_INFO block (21002 onwards)."""


@dataclass(frozen=True)
class Node:
    """One device in the system, as the battery's own node list records it."""

    slave: int
    """Modbus slave address the device answers on."""

    serial: int
    model: int
    """Model code: inverters below 3000, IoT/EBOX 3000s, packs 4000-4999."""

    flag: int
    """Word 2 of the entry - 1 for the EBOX on the one system decoded so far."""


def parse_node_list(data: bytes) -> List[Node]:
    """Decode NODE_INFO entries from a raw register read starting at 21002.

    Each entry is 8 words:

    | word | meaning |
    |---|---|
    | 0 | 0x01SS - SS is the slave address |
    | 1 | 0 |
    | 2 | flag |
    | 3-6 | 64-bit serial, least significant word first |
    | 7 | model code |

    Decoded against an EP2000 system whose serials were already known
    (EBOX at slave 0, EP2000 at 1, HV800 pack at 41). An entry with no model
    code is empty and ends the list.
    """

    words = [
        int.from_bytes(data[i : i + 2], "big") for i in range(0, len(data) - 1, 2)
    ]
    nodes: List[Node] = []

    for start in range(0, len(words) - NODE_ENTRY_WORDS + 1, NODE_ENTRY_WORDS):
        entry = words[start : start + NODE_ENTRY_WORDS]
        model = entry[7]

        if model == 0:
            break

        serial = entry[3] | entry[4] << 16 | entry[5] << 32 | entry[6] << 48
        nodes.append(Node(entry[0] & 0xFF, serial, model, entry[2]))

    return nodes


class NodeCountField(DeviceField):
    """How many devices the battery's node list holds.

    Reads `entries` node entries in one request, so a system with more
    devices than that reports `entries`.
    """

    def __init__(self, name: FieldName, address: int = 21002, entries: int = 4):
        super().__init__(name, address, entries * NODE_ENTRY_WORDS)

    def parse(self, data: bytes) -> int:
        return len(parse_node_list(data))
