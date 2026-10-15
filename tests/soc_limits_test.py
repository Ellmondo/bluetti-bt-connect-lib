"""EP2000 battery SOC limits (2022 low, 2023 high): writable in 1% steps."""

import asyncio
import struct
import unittest

from bluetti_bt_connect_lib.bluetooth import DeviceReader, DeviceReaderConfig, WriteOutcome
from bluetti_bt_connect_lib.devices import DEVICES
from bluetti_bt_connect_lib.fields import (
    FieldName,
    SocLimitField,
    check_soc_limits,
)

from bluetti_bt_connect_lib.utils.bleak_client_mock import ClientMockNoEncryption


class SlaveRecordingMock(ClientMockNoEncryption):
    """Echoes single-register writes (as the device does) and records them."""

    def __init__(self):
        super().__init__()
        self.writes = []
        self.slaves = []

    async def write_gatt_char(self, char_specifier, data, response=None):
        if data[1] != 6:
            return await super().write_gatt_char(char_specifier, data, response)
        address, value = struct.unpack_from("!HH", data, 2)
        self.writes.append((address, value))
        self.slaves.append(data[0])
        await self._callback(char_specifier, bytes(data))


def ep2000_reader(mock):
    return DeviceReader(
        "00:11:00:11:00:11",
        DEVICES["EP2000"](),
        asyncio.Future,
        DeviceReaderConfig(timeout=5),
        ble_client=mock,
    )


class TestField(unittest.TestCase):
    def setUp(self):
        self.field = SocLimitField(FieldName.BATTERY_SOC_RANGE_START, 2022)

    def test_every_reading_from_0_to_100_is_reported(self):
        for value in (0, 3, 13, 87, 100):
            self.assertEqual(self.field.parse(struct.pack("!H", value)), value)
            self.assertTrue(self.field.in_range(value))
        self.assertFalse(self.field.in_range(101))

    def test_writes_in_single_percent_steps(self):
        for value in (5, 13, 87, 100, 13.0):
            self.assertTrue(self.field.allowed_write_type(value), value)

    def test_writes_outside_5_to_100_are_refused(self):
        for value in (0, 4, 101, 13.5, True, "13", None):
            self.assertFalse(self.field.allowed_write_type(value), value)

    def test_ep2000_fields_are_numbers_not_sensors(self):
        device = DEVICES["EP2000"]()
        numbers = {f.name: f for f in device.get_number_fields()}
        sensors = {f.name for f in device.get_sensor_fields()}
        for name, address in (
            (FieldName.BATTERY_SOC_RANGE_START, 2022),
            (FieldName.BATTERY_SOC_RANGE_END, 2023),
        ):
            self.assertIn(name.value, numbers)
            self.assertNotIn(name.value, sensors)
            self.assertEqual(numbers[name.value].address, address)
            self.assertEqual((numbers[name.value].min, numbers[name.value].max), (5, 100))

    def test_other_devices_keep_read_only_sensors(self):
        for model in ("EP600", "EP500", "AC300"):
            names = {f.name for f in DEVICES[model]().get_number_fields()}
            self.assertNotIn(FieldName.BATTERY_SOC_RANGE_START.value, names, model)


class TestPairCheck(unittest.TestCase):
    def test_valid_pairs(self):
        self.assertIsNone(check_soc_limits(10, 100))
        self.assertIsNone(check_soc_limits(13, 87))
        self.assertIsNone(check_soc_limits(50, 55))

    def test_gap_too_small_or_crossed(self):
        self.assertIn("at least 5%", check_soc_limits(50, 54))
        self.assertIsNotNone(check_soc_limits(60, 40))

    def test_out_of_range(self):
        self.assertIsNotNone(check_soc_limits(4, 100))
        self.assertIsNotNone(check_soc_limits(10, 101))


class TestWrite(unittest.IsolatedAsyncioTestCase):
    async def test_low_limit_goes_to_the_ebox_as_one_register(self):
        mock = SlaveRecordingMock()
        result = await ep2000_reader(mock).write(
            FieldName.BATTERY_SOC_RANGE_START.value, 13
        )
        self.assertEqual(result.outcome, WriteOutcome.ACCEPTED)
        self.assertEqual(mock.writes, [(2022, 13)])
        self.assertEqual(mock.slaves, [0])

    async def test_high_limit(self):
        mock = SlaveRecordingMock()
        result = await ep2000_reader(mock).write(
            FieldName.BATTERY_SOC_RANGE_END.value, 87
        )
        self.assertEqual(result.outcome, WriteOutcome.ACCEPTED)
        self.assertEqual(mock.writes, [(2023, 87)])

    async def test_out_of_range_never_reaches_the_device(self):
        mock = SlaveRecordingMock()
        for value in (0, 4, 101):
            result = await ep2000_reader(mock).write(
                FieldName.BATTERY_SOC_RANGE_START.value, value
            )
            self.assertEqual(result.outcome, WriteOutcome.FAILED)
            self.assertEqual(result.detail, "value out of range")
        self.assertEqual(mock.writes, [])

    async def test_grid_limits_are_range_checked_too(self):
        mock = SlaveRecordingMock()
        result = await ep2000_reader(mock).write(
            FieldName.MAX_GRID_EXPORT_POWER.value, 9000
        )
        self.assertEqual(result.outcome, WriteOutcome.FAILED)
        self.assertEqual(mock.writes, [])


if __name__ == "__main__":
    unittest.main()
