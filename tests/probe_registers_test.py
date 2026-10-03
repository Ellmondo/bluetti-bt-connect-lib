"""Probe registers: unconfirmed addresses that must never fail a poll."""

import asyncio
import struct
import unittest

import crcmod.predefined

from bluetti_bt_connect_lib import DeviceReader
from bluetti_bt_connect_lib.base_devices import BluettiDevice
from bluetti_bt_connect_lib.bluetooth import device_reader
from bluetti_bt_connect_lib.devices import DEVICES
from bluetti_bt_connect_lib.fields import FieldName, ProbeUIntField, UIntField
from bluetti_bt_connect_lib.utils.bleak_client_mock import ClientMockNoEncryption

modbus_crc = crcmod.predefined.mkCrcFun("modbus")


class ScriptedClientMock(ClientMockNoEncryption):
    """Refuses some addresses with an exception frame, ignores others."""

    def __init__(self, refused=(), silent=()):
        super().__init__()
        self.refused = set(refused)
        self.silent = set(silent)
        self.requests = []

    async def write_gatt_char(self, char_specifier, data, response=None):
        _, address, size, _ = struct.unpack_from("!HHHH", data)
        self.requests.append((address, size))

        if any(address <= a < address + size for a in self.silent):
            return  # no reply at all

        if any(address <= a < address + size for a in self.refused):
            frame = bytearray(5)
            frame[0], frame[1], frame[2] = 1, 0x83, 0x02
            struct.pack_into("<H", frame, -2, modbus_crc(frame[:-2]))
            await self._callback(char_specifier, frame)
            return

        await self._callback(char_specifier, await self._get_register(address, size))


def _device():
    return BluettiDevice(
        fields=[
            UIntField(FieldName.PACK_VOLTAGE, 6111),
            UIntField(FieldName.PACK_SOH, 6114),
            ProbeUIntField(FieldName.RAW_REGISTER_6115, 6115),
            ProbeUIntField(FieldName.RAW_REGISTER_6007, 6007),
        ],
        max_register_gap=8,
    )


class TestProbeRegisters(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._timeout = device_reader.RESPONSE_TIMEOUT
        self._grace = device_reader.LATE_REPLY_GRACE
        device_reader.RESPONSE_TIMEOUT = 0.1
        device_reader.LATE_REPLY_GRACE = 0

    def tearDown(self):
        device_reader.RESPONSE_TIMEOUT = self._timeout
        device_reader.LATE_REPLY_GRACE = self._grace

    def _reader(self, mock):
        return DeviceReader(
            "00:11:00:11:00:11", _device(), asyncio.Future, ble_client=mock
        )

    @staticmethod
    def _mock(**kwargs):
        mock = ScriptedClientMock(**kwargs)
        mock.add_r_int(6111, 7546)
        mock.add_r_int(6114, 97)
        mock.add_r_int(6115, 59)
        mock.add_r_int(6007, 99)
        return mock

    def test_probes_are_not_grouped(self):
        device = _device()
        self.assertEqual(
            [(r.starting_address, r.quantity) for r in device.get_polling_registers()],
            [(6111, 4)],
        )
        self.assertEqual(
            [(r.starting_address, r.quantity) for r in device.get_optional_registers()],
            [(6007, 1), (6115, 1)],
        )

    async def test_probes_read_raw_after_everything_else(self):
        mock = self._mock()
        data = await self._reader(mock).read()

        self.assertEqual(mock.requests, [(6111, 4), (6007, 1), (6115, 1)])
        self.assertEqual(data[FieldName.RAW_REGISTER_6115.value], 59)
        self.assertEqual(data[FieldName.RAW_REGISTER_6007.value], 99)
        self.assertEqual(data[FieldName.PACK_SOH.value], 97)

    async def test_refused_probe_is_dropped_and_not_asked_again(self):
        mock = self._mock(refused=[6007])
        reader = self._reader(mock)

        data = await reader.read()
        self.assertNotIn(FieldName.RAW_REGISTER_6007.value, data)
        self.assertEqual(data[FieldName.RAW_REGISTER_6115.value], 59)
        self.assertEqual(data[FieldName.PACK_VOLTAGE.value], 7546)

        mock.requests.clear()
        await reader.read()
        self.assertEqual(mock.requests, [(6111, 4), (6115, 1)])

    async def test_silent_probe_does_not_fail_the_poll(self):
        mock = self._mock(silent=[6007])
        reader = self._reader(mock)

        data = await reader.read()
        self.assertIsNotNone(data)
        self.assertEqual(data[FieldName.PACK_SOH.value], 97)
        self.assertEqual(data[FieldName.RAW_REGISTER_6115.value], 59)

        mock.requests.clear()
        data = await reader.read()
        self.assertEqual(mock.requests, [(6111, 4), (6115, 1)])
        self.assertEqual(data[FieldName.PACK_SOH.value], 97)

    async def test_silent_ordinary_register_still_fails_the_poll(self):
        # Unchanged behaviour: for a normal field, silence means the link is
        # gone, and the poll is abandoned.
        mock = self._mock(silent=[6111])
        self.assertIsNone(await self._reader(mock).read())

    def test_ep2000_probes(self):
        device = DEVICES["EP2000"]()
        self.assertEqual(
            [r.starting_address for r in device.get_optional_registers()],
            [6007, 6115],
        )
        polled = [
            (r.starting_address, r.starting_address + r.quantity)
            for r in device.get_polling_registers()
        ]
        for start, end in polled:
            self.assertFalse(start <= 6115 < end, "6115 must not be grouped")
            self.assertFalse(start <= 6007 < end, "6007 must not be grouped")


if __name__ == "__main__":
    unittest.main()
