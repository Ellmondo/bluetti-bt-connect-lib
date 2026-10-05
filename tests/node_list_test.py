"""Node list decoding, pack temperature and slave-aware raw reads."""

import asyncio
import struct
import unittest

from bluetti_bt_connect_lib import DeviceReader, FieldName, RawReadOutcome, parse_node_list
from bluetti_bt_connect_lib.base_devices import BluettiDevice
from bluetti_bt_connect_lib.devices import DEVICES
from bluetti_bt_connect_lib.fields import NodeCountField, UIntField, get_unit

from raw_read_test import ScriptedClientMock

# 21002-21033 as read from a real EP2000 + EBOX + HV800 on 2026-10-04.
REAL_NODE_WORDS = [
    256, 0, 1, 64962, 19295, 589, 0, 3004,
    257, 0, 0, 39390, 4034, 589, 0, 1004,
    297, 0, 0, 20991, 46988, 590, 0, 4001,
    0, 0, 0, 0, 0, 0, 0, 0,
]


def _bytes(words):
    return b"".join(struct.pack("!H", w) for w in words)


class TestNodeList(unittest.TestCase):
    def test_real_system_decodes(self):
        nodes = parse_node_list(_bytes(REAL_NODE_WORDS))

        self.assertEqual([n.slave for n in nodes], [0, 1, 41])
        self.assertEqual([n.model for n in nodes], [3004, 1004, 4001])
        # The EBOX and EP2000 serials were known before this was decoded.
        self.assertEqual(nodes[0].serial, 2531000319426)
        self.assertEqual(nodes[1].serial, 2530000148958)
        self.assertEqual(nodes[2].serial, 2537110131199)
        self.assertEqual([n.flag for n in nodes], [1, 0, 0])

    def test_count_field(self):
        field = NodeCountField(FieldName.CONNECTED_DEVICES, 21002, entries=4)
        self.assertEqual(field.size, 32)
        self.assertEqual(field.parse(_bytes(REAL_NODE_WORDS)), 3)
        self.assertEqual(field.parse(_bytes([0] * 32)), 0)

    def test_list_stops_at_first_empty_entry(self):
        words = REAL_NODE_WORDS[:8] + [0] * 8 + REAL_NODE_WORDS[8:16] + [0] * 8
        self.assertEqual(len(parse_node_list(_bytes(words))), 1)


class TestEp2000Fields(unittest.TestCase):
    def setUp(self):
        self.device = DEVICES["EP2000"]()

    def test_pack_temperature_is_celsius_minus_40(self):
        # BLUETTI's app decodes 6115 as raw - 40 degrees C.
        self.assertEqual(get_unit(FieldName.PACK_TEMPERATURE), "°C")
        self.assertEqual(self.device.parse(6115, struct.pack("!H", 66)), {"pack_temperature": 26})
        self.assertEqual(self.device.parse(6115, struct.pack("!H", 30)), {"pack_temperature": -10})
        self.assertEqual(self.device.parse(6115, struct.pack("!H", 0)), {"pack_temperature": -40})

    def test_pack_temperature_rides_in_the_pack_group(self):
        groups = [(r.starting_address, r.quantity) for r in self.device.get_polling_registers()]
        self.assertIn((6101, 15), groups)

    def test_connected_devices_replaces_the_bogus_node_count(self):
        names = [f.name for f in self.device.fields]
        self.assertIn("connected_devices", names)
        self.assertNotIn("total_node_count", names)
        self.assertEqual(
            self.device.parse(21002, _bytes(REAL_NODE_WORDS)), {"connected_devices": 3}
        )
        groups = [(r.starting_address, r.quantity) for r in self.device.get_polling_registers()]
        self.assertIn((21002, 32), groups)


class TestSlaveReads(unittest.IsolatedAsyncioTestCase):
    def _reader(self, mock):
        device = BluettiDevice(fields=[UIntField(FieldName.PACK_SOH, 6114)])
        return DeviceReader("00:11:00:11:00:11", device, asyncio.Future, ble_client=mock)

    async def test_read_raw_at_another_slave(self):
        mock = ScriptedClientMock()
        mock.add_r_int(6115, 71)

        result = await self._reader(mock).read_raw(6115, 1, slave=41)

        self.assertEqual(result.outcome, RawReadOutcome.OK)
        self.assertEqual(mock.requests, [(41, 3, 6115, 1)])
        self.assertEqual(result.as_dict()["slave"], 41)

    async def test_slave_bounds(self):
        reader = self._reader(ScriptedClientMock())
        for slave in (-1, 248):
            with self.assertRaises(ValueError):
                await reader.read_raw(100, 1, slave=slave)

    async def test_read_nodes(self):
        mock = ScriptedClientMock()
        for i, w in enumerate(REAL_NODE_WORDS):
            mock.add_r_int(21002 + i, w)

        nodes = await self._reader(mock).read_nodes()

        self.assertEqual([n.slave for n in nodes], [0, 1, 41])
        self.assertEqual(mock.requests, [(1, 3, 21002, 32)])

    async def test_read_nodes_failure_is_none(self):
        mock = ScriptedClientMock(refused=[21002])
        self.assertIsNone(await self._reader(mock).read_nodes())


if __name__ == "__main__":
    unittest.main()
