import asyncio
import struct
import unittest

import crcmod.predefined

from bluetti_bt_connect_lib.base_devices import BluettiDevice
from bluetti_bt_connect_lib.bluetooth import (
    DeviceReader,
    DeviceReaderConfig,
    WriteOutcome,
    encode_bt_password,
    build_unlock_command,
)
from bluetti_bt_connect_lib.fields import FieldName, WriteableUIntField
from bluetti_bt_connect_lib.utils.bleak_client_mock import ClientMockNoEncryption

modbus_crc = crcmod.predefined.mkCrcFun("modbus")


class UnlockWriteMock(ClientMockNoEncryption):
    """Records writes in order and echoes them the way a real device does.

    Function 6 echoes the request verbatim. Function 16 echoes slave, function,
    starting address and quantity (the first six bytes) plus a fresh CRC.
    """

    def __init__(self):
        super().__init__()
        self.writes = []  # list of (function, address, payload)

    async def write_gatt_char(self, char_specifier, data, response=None):
        function = data[1]

        if function == 6:
            address, value = struct.unpack_from("!HH", data, 2)
            self.writes.append((6, address, value))
            await self._callback(char_specifier, bytes(data))
            return

        if function == 16:
            address, quantity = struct.unpack_from("!HH", data, 2)
            self.writes.append((16, address, quantity))
            frame = bytearray(data[:6])
            frame += struct.pack("<H", modbus_crc(frame))
            await self._callback(char_specifier, bytes(frame))
            return

        return await super().write_gatt_char(char_specifier, data, response)


def device():
    return BluettiDevice(
        fields=[
            WriteableUIntField(FieldName.MAX_GRID_EXPORT_POWER, 2215, min=0, max=6666),
        ]
    )


def reader(mock, password):
    return DeviceReader(
        "00:11:00:11:00:11",
        device(),
        asyncio.Future,
        DeviceReaderConfig(timeout=5, unlock_password=password),
        ble_client=mock,
    )


class TestEncode(unittest.TestCase):
    def test_empty_password_is_three_zero_registers(self):
        self.assertEqual(encode_bt_password(""), [0, 0, 0])
        self.assertEqual(encode_bt_password(None), [0, 0, 0])

    def test_bytes_are_swapped_within_each_register(self):
        self.assertEqual(encode_bt_password("1234"), [0x3231, 0x3433, 0x0000])
        self.assertEqual(encode_bt_password("123456"), [0x3231, 0x3433, 0x3635])

    def test_longer_than_six_chars_is_truncated(self):
        self.assertEqual(encode_bt_password("1234567"), encode_bt_password("123456"))

    def test_command_targets_register_seven_function_sixteen(self):
        cmd = build_unlock_command("1234")
        self.assertEqual(cmd.address, 7)
        self.assertEqual(cmd.values, [0x3231, 0x3433, 0x0000])
        self.assertEqual(bytes(cmd)[1], 16)


class TestUnlockBeforeWrite(unittest.IsolatedAsyncioTestCase):
    async def test_unlock_is_sent_before_the_protected_write(self):
        mock = UnlockWriteMock()
        result = await reader(mock, "1234").write(
            FieldName.MAX_GRID_EXPORT_POWER.value, 1500
        )

        self.assertTrue(result.accepted)
        # The register-7 func-16 unlock must come first, then the func-6 write.
        self.assertEqual(
            mock.writes,
            [(16, 7, 3), (6, 2215, 1500)],
        )

    async def test_blank_password_still_unlocks(self):
        mock = UnlockWriteMock()
        await reader(mock, "").write(FieldName.MAX_GRID_EXPORT_POWER.value, 1500)
        self.assertEqual(mock.writes[0], (16, 7, 3))

    async def test_no_unlock_when_password_is_none(self):
        mock = UnlockWriteMock()
        result = await reader(mock, None).write(
            FieldName.MAX_GRID_EXPORT_POWER.value, 1500
        )
        self.assertTrue(result.accepted)
        self.assertEqual(mock.writes, [(6, 2215, 1500)])


if __name__ == "__main__":
    unittest.main()
