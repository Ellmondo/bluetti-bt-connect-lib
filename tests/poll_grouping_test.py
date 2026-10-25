"""EP2000 poll size: wider merged reads, the slow-poll tier and refused ranges."""

import asyncio
import struct
import unittest

import crcmod.predefined

from bluetti_bt_connect_lib import DeviceReader
from bluetti_bt_connect_lib.bluetooth import DeviceReaderConfig
from bluetti_bt_connect_lib.devices import DEVICES

from slave_fields_test import TwoSlaveMock

modbus_crc = crcmod.predefined.mkCrcFun("modbus")


def _groups(registers):
    return [(r.slave, r.starting_address, r.quantity) for r in registers]


class RefusingMock(TwoSlaveMock):
    """Refuses (exception 0x02) any read at `slave` that covers `address`."""

    def __init__(self, slave, address):
        super().__init__()
        self.refuse = (slave, address)

    async def write_gatt_char(self, char_specifier, data, response=None):
        slave = data[0]
        _, start, size = struct.unpack_from("!BxHH", data)
        if (slave, True) == (self.refuse[0], start <= self.refuse[1] < start + size):
            self.requests.append((slave, start, size))
            frame = bytearray([slave, 0x83, 0x02, 0, 0])
            struct.pack_into("<H", frame, 3, modbus_crc(bytes(frame[:3])))
            await self._callback(char_specifier, bytes(frame))
            return
        await super().write_gatt_char(char_specifier, data, response)


def reader(mock, slow_poll_seconds=600):
    return DeviceReader(
        "00:11:00:11:00:11",
        DEVICES["EP2000"](),
        asyncio.Future,
        DeviceReaderConfig(timeout=5, slow_poll_seconds=slow_poll_seconds),
        ble_client=mock,
    )


class TestGroups(unittest.TestCase):
    def setUp(self):
        self.device = DEVICES["EP2000"]()
        self.fast = _groups(self.device.get_polling_registers())
        self.slow = _groups(self.device.get_slow_polling_registers())

    def test_request_counts(self):
        # 28 requests a poll before 2.0.12.
        self.assertEqual(len(self.fast), 13)
        self.assertEqual(len(self.slow), 6)

    def test_sizes_and_never_read_ranges(self):
        for slave, start, quantity in self.fast + self.slow:
            end = start + quantity - 1
            self.assertLessEqual(quantity, 100)
            # The WiFi password starts at 12018.
            self.assertFalse(start <= 12018 <= end, (slave, start, quantity))
            # The advanced-settings password, 2200-2203.
            self.assertFalse(start <= 2203 and end >= 2200, (slave, start, quantity))

    def test_slow_tier(self):
        self.assertIn((1, 21002, 32), self.slow)  # connected devices
        self.assertIn((1, 12002, 16), self.slow)  # WiFi name
        self.assertIn((1, 1112, 19), self.slow)  # inverter firmware
        self.assertIn((0, 11014, 2), self.slow)  # IoT firmware
        # Cloud connection and WiFi signal stay on every poll.
        self.assertIn((0, 11018, 9), self.fast)

    def test_wide_groups_have_a_conservative_fallback(self):
        home = next(
            r for r in self.device.get_polling_registers()
            if (r.slave, r.starting_address) == (0, 103)
        )
        self.assertEqual(
            _groups(home.fallback), [(0, 103, 4), (0, 122, 32), (0, 154, 11), (0, 174, 1)]
        )

    def test_other_devices_keep_the_default_grouping(self):
        for model in ("AC300", "EP600", "AC200L"):
            device = DEVICES[model]()
            self.assertEqual(device.max_register_gap, 8, model)
            self.assertEqual(device.get_slow_polling_registers(), [], model)


class TestSlowPoll(unittest.IsolatedAsyncioTestCase):
    async def test_read_first_then_reused(self):
        mock = TwoSlaveMock()
        mock.set(1, 6152, struct.pack("!3H", 224, 112, 7))
        r = reader(mock)

        first = await r.read()
        first_requests = list(mock.requests)
        mock.requests.clear()
        second = await r.read()

        self.assertIn((1, 6152, 3), first_requests)
        self.assertNotIn((1, 6152, 3), mock.requests)
        self.assertEqual(len(mock.requests), 13)
        # The last values are still reported, so nothing goes unavailable.
        for data in (first, second):
            self.assertEqual(data["active_cell_count"], 224)
            self.assertIn("connected_devices", data)
            self.assertIn("firmware_arm", data)

    async def test_read_again_when_due(self):
        mock = TwoSlaveMock()
        r = reader(mock, slow_poll_seconds=0)
        await r.read()
        mock.requests.clear()
        await r.read()
        self.assertIn((1, 6152, 3), mock.requests)


class TestRefusedRange(unittest.IsolatedAsyncioTestCase):
    async def test_split_once_and_remembered(self):
        # Pretend 1295 (between the 1290 and 1300 fields) is not served.
        mock = RefusingMock(1, 1295)
        mock.set(1, 1313, struct.pack("!H", 1234))
        r = reader(mock)

        data = await r.read()
        self.assertIn((1, 1290, 38), mock.requests)
        self.assertIn((1, 1290, 1), mock.requests)
        self.assertIn((1, 1300, 2), mock.requests)
        self.assertIn((1, 1313, 15), mock.requests)
        self.assertIn((1, 1290, 38), r.rejected_groups)
        self.assertIn("total_self_consumption", data)

        mock.requests.clear()
        await r.read()
        self.assertNotIn((1, 1290, 38), mock.requests)
        self.assertIn((1, 1290, 1), mock.requests)


if __name__ == "__main__":
    unittest.main()
