"""DeviceReader.read_raw: one-off reads of arbitrary registers."""

import asyncio
import struct
import unittest

import crcmod.predefined

from bluetti_bt_connect_lib import DeviceReader, RawReadOutcome
from bluetti_bt_connect_lib.base_devices import BluettiDevice
from bluetti_bt_connect_lib.bluetooth import device_reader
from bluetti_bt_connect_lib.fields import FieldName, UIntField
from bluetti_bt_connect_lib.utils.bleak_client_mock import ClientMockNoEncryption

modbus_crc = crcmod.predefined.mkCrcFun("modbus")


class ScriptedClientMock(ClientMockNoEncryption):
    def __init__(self, refused=(), silent=()):
        super().__init__()
        self.refused = set(refused)
        self.silent = set(silent)
        self.requests = []

    async def write_gatt_char(self, char_specifier, data, response=None):
        slave, function, address, size = struct.unpack_from("!BBHH", data)
        self.requests.append((slave, function, address, size))

        if any(address <= a < address + size for a in self.silent):
            return

        if any(address <= a < address + size for a in self.refused):
            frame = bytearray(5)
            frame[0], frame[1], frame[2] = 1, 0x83, 0x02
            struct.pack_into("<H", frame, -2, modbus_crc(frame[:-2]))
            await self._callback(char_specifier, frame)
            return

        await self._callback(char_specifier, await self._get_register(address, size))


class TestReadRaw(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._timeout = device_reader.RESPONSE_TIMEOUT
        self._grace = device_reader.LATE_REPLY_GRACE
        device_reader.RESPONSE_TIMEOUT = 0.1
        device_reader.LATE_REPLY_GRACE = 0

    def tearDown(self):
        device_reader.RESPONSE_TIMEOUT = self._timeout
        device_reader.LATE_REPLY_GRACE = self._grace

    def _reader(self, mock):
        device = BluettiDevice(fields=[UIntField(FieldName.PACK_SOH, 6114)])
        return DeviceReader("00:11:00:11:00:11", device, asyncio.Future, ble_client=mock)

    async def test_reads_block_as_words(self):
        mock = ScriptedClientMock()
        mock.add_r_int(1700, 2300)
        mock.add_r_int(1701, 0xFFFE)
        mock.add_r_int(1702, 7)

        result = await self._reader(mock).read_raw(1700, 3)

        self.assertEqual(result.outcome, RawReadOutcome.OK)
        self.assertEqual(result.words, [2300, 0xFFFE, 7])
        # Strictly a read: function 3 at slave 1, exactly what was asked.
        self.assertEqual(mock.requests, [(1, 3, 1700, 3)])

        d = result.as_dict()
        self.assertEqual(d["outcome"], "ok")
        self.assertEqual(d["registers"][1], {
            "address": 1701, "value": 65534, "signed": -2, "hex": "0xfffe",
        })

    async def test_refusal_is_reported_not_raised(self):
        mock = ScriptedClientMock(refused=[5800])
        result = await self._reader(mock).read_raw(5800, 3)

        self.assertEqual(result.outcome, RawReadOutcome.REFUSED)
        self.assertEqual(result.exception_code, 0x02)
        self.assertEqual(result.words, [])
        self.assertEqual(result.as_dict()["exception_code"], "0x02")

    async def test_silence_is_reported_not_raised(self):
        mock = ScriptedClientMock(silent=[1900])
        result = await self._reader(mock).read_raw(1900, 2)

        self.assertEqual(result.outcome, RawReadOutcome.NO_REPLY)

    async def test_polling_still_works_after_a_silent_raw_read(self):
        mock = ScriptedClientMock(silent=[1900])
        mock.add_r_int(6114, 97)
        reader = self._reader(mock)

        await reader.read_raw(1900, 2)
        data = await reader.read()

        self.assertEqual(data[FieldName.PACK_SOH.value], 97)

    async def test_limits(self):
        reader = self._reader(ScriptedClientMock())

        for address, count in [(100, 0), (100, 33), (-1, 1), (65535, 2)]:
            with self.assertRaises(ValueError):
                await reader.read_raw(address, count)

        # Upper bound accepted (the mock only models 20000 registers, so the
        # reply itself is not checked here).
        await reader.read_raw(65535, 1)

    async def test_waits_for_the_polling_lock(self):
        mock = ScriptedClientMock()
        reader = self._reader(mock)

        async with reader.polling_lock:
            task = asyncio.create_task(reader.read_raw(100, 1))
            await asyncio.sleep(0.05)
            self.assertFalse(task.done())
            self.assertEqual(mock.requests, [])

        result = await task
        self.assertEqual(result.outcome, RawReadOutcome.OK)


if __name__ == "__main__":
    unittest.main()
