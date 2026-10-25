"""Time-control schedule writes, the 2029 switch and BMS battery current/power."""

import asyncio
import struct
import unittest
from datetime import time

import crcmod.predefined

from bluetti_bt_connect_lib import DeviceReader, FieldName
from bluetti_bt_connect_lib.bluetooth import DeviceReaderConfig, WriteOutcome
from bluetti_bt_connect_lib.devices import DEVICES
from bluetti_bt_connect_lib.fields import PackPowerField, ScheduleAction, SwitchField
from bluetti_bt_connect_lib.schedule import (
    ScheduleError,
    SchedulePeriod,
    decode_schedule,
    encode_schedule,
    validate_schedule,
)
from bluetti_bt_connect_lib.utils.bleak_client_mock import ClientMockNoEncryption

from slave_fields_test import TwoSlaveMock

modbus_crc = crcmod.predefined.mkCrcFun("modbus")

CHARGE = ScheduleAction.CHARGE
DISCHARGE = ScheduleAction.DISCHARGE

# The schedule on the real unit (2026-10-05): charge 11:01-13:59,
# discharge 18:00-21:00, the rest off.
REAL = [
    SchedulePeriod(CHARGE, time(11, 1), time(13, 59)),
    SchedulePeriod(DISCHARGE, time(18, 0), time(21, 0)),
]
REAL_WORDS = [1, 0x0B01, 0x0D3B, 2, 0x1200, 0x1500] + [0] * 12


class WriteMock(ClientMockNoEncryption):
    """Answers function 6 and 16 writes the way the device does."""

    def __init__(self, echo_quantity=None):
        super().__init__()
        self.frames = []
        self.echo_quantity = echo_quantity

    async def write_gatt_char(self, char_specifier, data, response=None):
        function = data[1]
        if function == 6:
            self.frames.append(bytes(data))
            await self._callback(char_specifier, bytes(data))
            return
        if function == 16:
            self.frames.append(bytes(data))
            address, quantity = struct.unpack_from("!HH", data, 2)
            reply = bytearray(8)
            reply[0] = data[0]
            reply[1] = 16
            struct.pack_into(
                "!HH", reply, 2, address, self.echo_quantity or quantity
            )
            struct.pack_into("<H", reply, 6, modbus_crc(bytes(reply[:6])))
            await self._callback(char_specifier, bytes(reply))
            return
        return await super().write_gatt_char(char_specifier, data, response)


def reader(mock):
    return DeviceReader(
        "00:11:00:11:00:11",
        DEVICES["EP2000"](),
        asyncio.Future,
        DeviceReaderConfig(timeout=5),
        ble_client=mock,
    )


class TestEncode(unittest.TestCase):
    def test_real_schedule_round_trips(self):
        self.assertEqual(encode_schedule(REAL), REAL_WORDS)
        data = struct.pack("!18H", *REAL_WORDS)
        self.assertEqual(decode_schedule(data), REAL)

    def test_sorted_earliest_first(self):
        self.assertEqual(encode_schedule(list(reversed(REAL))), REAL_WORDS)

    def test_empty_schedule_clears_all_slots(self):
        self.assertEqual(encode_schedule([]), [0] * 18)

    def test_touching_periods_are_fine(self):
        validate_schedule([
            SchedulePeriod(CHARGE, time(11, 0), time(14, 0)),
            SchedulePeriod(ScheduleAction.STANDBY, time(14, 0), time(18, 0)),
        ])

    def test_six_periods_max(self):
        periods = [
            SchedulePeriod(CHARGE, time(h, 0), time(h, 30)) for h in range(7)
        ]
        with self.assertRaises(ScheduleError):
            encode_schedule(periods)
        encode_schedule(periods[:6])

    def test_refused(self):
        bad = {
            "overlap": [
                SchedulePeriod(CHARGE, time(11, 0), time(14, 0)),
                SchedulePeriod(DISCHARGE, time(13, 0), time(15, 0)),
            ],
            "end before start": [SchedulePeriod(CHARGE, time(22, 0), time(6, 0))],
            "zero length": [SchedulePeriod(CHARGE, time(9, 0), time(9, 0))],
            "off": [SchedulePeriod(ScheduleAction.OFF, time(9, 0), time(10, 0))],
        }
        for case, periods in bad.items():
            with self.assertRaises(ScheduleError, msg=case):
                encode_schedule(periods)

    def test_decode_skips_off_and_unknown(self):
        data = struct.pack("!9H", 0, 0, 0, 9, 0x0100, 0x0200, 3, 0x0000, 0x0630)
        self.assertEqual(
            decode_schedule(data),
            [SchedulePeriod(ScheduleAction.STANDBY, time(0, 0), time(6, 48))],
        )


class TestWriteSchedule(unittest.IsolatedAsyncioTestCase):
    async def test_one_function_16_write_to_the_ebox(self):
        mock = WriteMock()
        result = await reader(mock).write_schedule(REAL)
        self.assertEqual(result.outcome, WriteOutcome.ACCEPTED)
        self.assertEqual(len(mock.frames), 1)
        frame = mock.frames[0]
        slave, function, address, quantity, count = struct.unpack_from("!BBHHB", frame)
        self.assertEqual((slave, function, address, quantity, count), (0, 16, 2030, 18, 36))
        self.assertEqual(list(struct.unpack_from("!18H", frame, 7)), REAL_WORDS)

    async def test_invalid_schedule_never_reaches_the_device(self):
        mock = WriteMock()
        result = await reader(mock).write_schedule(
            [SchedulePeriod(CHARGE, time(22, 0), time(6, 0))]
        )
        self.assertEqual(result.outcome, WriteOutcome.FAILED)
        self.assertIn("after the start", result.detail)
        self.assertEqual(mock.frames, [])

    async def test_wrong_echo_is_not_accepted(self):
        mock = WriteMock(echo_quantity=17)
        result = await reader(mock).write_schedule(REAL)
        self.assertEqual(result.outcome, WriteOutcome.MISMATCHED)

    async def test_unsupported_device(self):
        mock = WriteMock()
        r = DeviceReader(
            "00:11:00:11:00:11",
            DEVICES["AC300"](),
            asyncio.Future,
            DeviceReaderConfig(timeout=5),
            ble_client=mock,
        )
        result = await r.write_schedule(REAL)
        self.assertEqual(result.detail, "schedule not supported")
        self.assertEqual(mock.frames, [])

    async def test_time_control_switch_writes_2029_at_the_ebox(self):
        mock = WriteMock()
        result = await reader(mock).write(FieldName.TIME_CONTROL_ENABLED.value, False)
        self.assertEqual(result.outcome, WriteOutcome.ACCEPTED)
        slave, function, address, value = struct.unpack_from("!BBHH", mock.frames[0])
        self.assertEqual((slave, function, address, value), (0, 6, 2029, 0))


class TestBatteryCurrentAndPower(unittest.TestCase):
    def test_power_from_real_reads(self):
        field = PackPowerField(FieldName.BATTERY_POWER_BMS, 6111)
        # Discharging (6112 = -84) and holding in backup mode (6111 = 7336, 6112 = 3).
        self.assertEqual(field.parse(struct.pack("!Hh", 7320, -84)), -6149)
        self.assertEqual(field.parse(struct.pack("!Hh", 7336, 3)), 220)

    def test_time_control_is_a_switch(self):
        device = DEVICES["EP2000"]()
        self.assertIn(
            FieldName.TIME_CONTROL_ENABLED.value,
            [f.name for f in device.get_switch_fields()],
        )
        self.assertNotIn(
            FieldName.TIME_CONTROL_ENABLED.value,
            [f.name for f in device.get_bool_fields()],
        )


class TestPoll(unittest.IsolatedAsyncioTestCase):
    async def test_current_and_power_in_the_existing_pack_read(self):
        device = DEVICES["EP2000"]()
        groups = [(r.slave, r.starting_address, r.quantity) for r in device.get_polling_registers()]
        self.assertIn((1, 6101, 17), groups)

        mock = TwoSlaveMock()
        mock.set(1, 6111, struct.pack("!Hh", 7320, -84))
        data = await DeviceReader(
            "00:11:00:11:00:11", device, asyncio.Future, ble_client=mock
        ).read()
        self.assertEqual(data["battery_current"], -8.4)
        self.assertEqual(data["battery_power_bms"], -6149)


if __name__ == "__main__":
    unittest.main()
