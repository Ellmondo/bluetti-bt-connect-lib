import asyncio
import struct
import unittest

import crcmod.predefined

from bluetti_bt_connect_lib.base_devices import BluettiDevice
from bluetti_bt_connect_lib.bluetooth import (
    DeviceReader,
    DeviceReaderConfig,
    WriteOutcome,
)
from bluetti_bt_connect_lib.fields import FieldName, SwitchField, WriteableUIntField
from bluetti_bt_connect_lib.utils.bleak_client_mock import ClientMockNoEncryption

modbus_crc = crcmod.predefined.mkCrcFun("modbus")


class WriteMock(ClientMockNoEncryption):
    """Answers a write either with an echo or with a Modbus exception.

    Real devices reply to every write. The integration has never read that
    reply, so these tests pin down what each kind of reply should mean.
    """

    def __init__(self, refuse: dict | None = None, silent: bool = False):
        super().__init__()
        self.refuse = refuse or {}
        self.silent = silent
        self.writes = []

    async def write_gatt_char(self, char_specifier, data, response=None):
        function = data[1]

        if function != 6:
            return await super().write_gatt_char(char_specifier, data, response)

        address, value = struct.unpack_from("!HH", data, 2)
        self.writes.append((address, value))

        if self.silent:
            return

        if address in self.refuse:
            await self._callback(char_specifier, self._exception(self.refuse[address]))
            return

        # Function 6 echoes the request back verbatim.
        await self._callback(char_specifier, bytes(data))

    @staticmethod
    def _exception(code: int) -> bytes:
        frame = bytearray(5)
        frame[0] = 1
        frame[1] = 0x86
        frame[2] = code
        struct.pack_into("<H", frame, -2, modbus_crc(frame[:-2]))
        return bytes(frame)


def device():
    return BluettiDevice(
        fields=[
            SwitchField(FieldName.CTRL_AC, 2011),
            WriteableUIntField(FieldName.MAX_GRID_EXPORT_POWER, 2215, min=0, max=6666),
        ]
    )


def reader(mock):
    return DeviceReader(
        "00:11:00:11:00:11",
        device(),
        asyncio.Future,
        DeviceReaderConfig(timeout=5),
        ble_client=mock,
    )


class TestWriteResult(unittest.IsolatedAsyncioTestCase):
    async def test_accepted_when_the_device_echoes(self):
        mock = WriteMock()

        result = await reader(mock).write(FieldName.MAX_GRID_EXPORT_POWER.value, 1333)

        self.assertTrue(result.accepted)
        self.assertIs(result.outcome, WriteOutcome.ACCEPTED)
        self.assertEqual(result.echoed, 1333)
        self.assertEqual(mock.writes, [(2215, 1333)])

    async def test_refused_surfaces_the_exception_code(self):
        # 0x04 is the code a device returns when it will not action a request
        # it otherwise understands - the interesting case for grid settings.
        mock = WriteMock(refuse={2215: 0x04})

        result = await reader(mock).write(FieldName.MAX_GRID_EXPORT_POWER.value, 1333)

        self.assertFalse(result.accepted)
        self.assertIs(result.outcome, WriteOutcome.REFUSED)
        self.assertEqual(result.exception_code, 0x04)
        self.assertEqual(result.exception_meaning, "Server device failure")
        self.assertIn("0x04", str(result))

    async def test_illegal_data_address_is_reported_distinctly(self):
        mock = WriteMock(refuse={2215: 0x02})

        result = await reader(mock).write(FieldName.MAX_GRID_EXPORT_POWER.value, 1333)

        self.assertEqual(result.exception_code, 0x02)
        self.assertEqual(result.exception_meaning, "Illegal data address")

    async def test_silence_is_not_reported_as_success(self):
        mock = WriteMock(silent=True)

        result = await reader(mock).write(FieldName.MAX_GRID_EXPORT_POWER.value, 1333)

        self.assertFalse(result.accepted)
        self.assertIs(result.outcome, WriteOutcome.NO_RESPONSE)

    async def test_switch_field_accepted(self):
        mock = WriteMock()

        result = await reader(mock).write(FieldName.CTRL_AC.value, True)

        self.assertTrue(result.accepted)
        self.assertEqual(mock.writes, [(2011, 1)])

    async def test_unknown_field_fails_without_touching_the_device(self):
        mock = WriteMock()

        result = await reader(mock).write("not_a_real_field", 1)

        self.assertIs(result.outcome, WriteOutcome.FAILED)
        self.assertEqual(mock.writes, [])

    async def test_non_writeable_field_fails_without_touching_the_device(self):
        from bluetti_bt_connect_lib.fields import UIntField

        read_only = BluettiDevice(fields=[UIntField(FieldName.AC_P1_POWER, 1510)])
        mock = WriteMock()
        r = DeviceReader(
            "00:11:00:11:00:11", read_only, asyncio.Future, ble_client=mock
        )

        result = await r.write(FieldName.AC_P1_POWER.value, 5)

        self.assertIs(result.outcome, WriteOutcome.FAILED)
        self.assertEqual(mock.writes, [])

    async def test_exception_code_does_not_leak_between_commands(self):
        mock = WriteMock(refuse={2215: 0x04})
        r = reader(mock)

        refused = await r.write(FieldName.MAX_GRID_EXPORT_POWER.value, 1333)
        self.assertEqual(refused.exception_code, 0x04)

        accepted = await r.write(FieldName.CTRL_AC.value, True)
        self.assertTrue(accepted.accepted)
        self.assertIsNone(accepted.exception_code)
