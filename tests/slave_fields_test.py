"""Fields read from a slave other than 1: grouping, parsing and a full poll."""

import asyncio
import struct
import unittest

from bluetti_bt_connect_lib import DeviceReader, FieldName
from bluetti_bt_connect_lib.base_devices import BluettiDevice
from bluetti_bt_connect_lib.devices import DEVICES
from bluetti_bt_connect_lib.fields import SInt32Field, SIntField, UIntField, get_unit
from bluetti_bt_connect_lib.utils.bleak_client_mock import ClientMockNoEncryption


def _u32(value):
    """32-bit value as the device sends it: low word first."""
    return struct.pack("!HH", value & 0xFFFF, (value >> 16) & 0xFFFF)


class TwoSlaveMock(ClientMockNoEncryption):
    """Serves a separate register map per slave address."""

    def __init__(self):
        super().__init__()
        self.maps = {1: self._bytemap, 0: bytearray(0x20000)}
        self.requests = []

    def set(self, slave, register, data: bytes):
        self.maps[slave][register * 2 : register * 2 + len(data)] = data

    async def write_gatt_char(self, char_specifier, data, response=None):
        slave = data[0]
        _, address, size = struct.unpack_from("!BxHH", data)
        self.requests.append((slave, address, size))
        self._bytemap = self.maps[slave]
        await self._callback(char_specifier, await self._get_register(address, size))


class TestGrouping(unittest.TestCase):
    def test_slaves_are_never_mixed_in_one_request(self):
        device = BluettiDevice(
            fields=[
                SIntField(FieldName.CONSUMPTION_POWER_ALL, 142),
                SInt32Field(FieldName.HOME_LOAD_POWER, 142).at_slave(0),
                UIntField(FieldName.SELF_SUFFICIENCY, 164).at_slave(0),
            ]
        )
        groups = [(r.slave, r.starting_address, r.quantity) for r in device.get_polling_registers()]
        self.assertEqual(groups, [(1, 142, 1), (0, 142, 2), (0, 164, 1)])

    def test_ep2000_reads_the_home_block_from_the_ebox(self):
        device = DEVICES["EP2000"]()
        groups = [(r.slave, r.starting_address, r.quantity) for r in device.get_polling_registers()]
        covered = set()
        for slave, start, quantity in groups:
            if slave == 0:
                covered.update(range(start, start + quantity))
        # Every home-block register the EBOX fields need is read from slave 0.
        for register in (142, 143, 152, 153, 154, 155, 156, 157, 158, 159, 164):
            self.assertIn(register, covered)
        # Slave 1 first, the EBOX block after it.
        self.assertEqual(groups[0][0], 1)
        self.assertEqual(groups[-1][0], 0)
        # The inverter's own 142-146 read is unchanged.
        self.assertIn((1, 142, 5), groups)

    def test_parse_only_matches_fields_of_the_answering_slave(self):
        device = DEVICES["EP2000"]()
        block = bytearray(46)  # 142..164
        block[0:4] = _u32(1162)
        from_ebox = device.parse(142, bytes(block), slave=0)
        self.assertEqual(from_ebox[FieldName.HOME_LOAD_POWER.value], 1162)
        self.assertNotIn(FieldName.CONSUMPTION_POWER_ALL.value, from_ebox)

        from_inverter = device.parse(142, bytes(block[:10]), slave=1)
        self.assertIn(FieldName.CONSUMPTION_POWER_ALL.value, from_inverter)
        self.assertNotIn(FieldName.HOME_LOAD_POWER.value, from_inverter)

    def test_units(self):
        self.assertEqual(get_unit(FieldName.HOME_LOAD_POWER), "W")
        self.assertEqual(get_unit(FieldName.SELF_SUFFICIENCY), "%")
        for name in (
            FieldName.HOME_CONSUMPTION_ENERGY,
            FieldName.SOLAR_ENERGY,
            FieldName.GRID_IMPORT_ENERGY,
            FieldName.GRID_EXPORT_ENERGY,
        ):
            self.assertEqual(get_unit(name), "kWh")


class TestPollAcrossSlaves(unittest.IsolatedAsyncioTestCase):
    async def test_real_values_from_both_slaves(self):
        mock = TwoSlaveMock()
        # Slave 1: the inverter's view, where the totals read 0.
        mock.set(1, 142, struct.pack("!h", 0))
        mock.set(1, 6115, struct.pack("!H", 66))
        # Slave 0: the EBOX, values from a real read on 2026-10-05.
        mock.set(0, 142, _u32(1162))
        mock.set(0, 152, _u32(37396))
        mock.set(0, 154, _u32(23284))
        mock.set(0, 156, _u32(51642))
        mock.set(0, 158, _u32(5111))
        mock.set(0, 164, struct.pack("!H", 64))

        reader = DeviceReader(
            "00:11:00:11:00:11", DEVICES["EP2000"](), asyncio.Future, ble_client=mock
        )
        data = await reader.read()

        self.assertIsNotNone(data)
        self.assertEqual(data["home_load_power"], 1162)
        self.assertEqual(data["home_consumption_energy"], 3739.6)
        self.assertEqual(data["solar_energy"], 2328.4)
        self.assertEqual(data["grid_import_energy"], 5164.2)
        self.assertEqual(data["grid_export_energy"], 511.1)
        self.assertEqual(data["self_sufficiency"], 64)
        self.assertEqual(data["consumption_power_all"], 0)
        self.assertEqual(data["pack_temperature"], 26)
        self.assertTrue(any(slave == 0 for slave, _, _ in mock.requests))

    async def test_totals_past_16_bits_decode(self):
        # Grid import passes 6553.5 kWh (65535 raw) within weeks.
        mock = TwoSlaveMock()
        mock.set(0, 156, _u32(70001))
        reader = DeviceReader(
            "00:11:00:11:00:11", DEVICES["EP2000"](), asyncio.Future, ble_client=mock
        )
        data = await reader.read()
        self.assertEqual(data["grid_import_energy"], 7000.1)


if __name__ == "__main__":
    unittest.main()
