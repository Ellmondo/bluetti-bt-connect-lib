import asyncio
import struct
import unittest

import crcmod.predefined

from bluetti_bt_connect_lib.base_devices import BaseDeviceV1, BluettiDevice
from bluetti_bt_connect_lib import DeviceReader
from bluetti_bt_connect_lib.fields import FieldName, UIntField
from bluetti_bt_connect_lib.utils.bleak_client_mock import ClientMockNoEncryption

modbus_crc = crcmod.predefined.mkCrcFun("modbus")


class RejectingClientMock(ClientMockNoEncryption):
    """Mock that refuses any read whose range covers a forbidden register.

    Real devices reject a whole read when it spans an address they don't
    implement, which is the failure mode grouped reads have to survive.
    """

    def __init__(self, forbidden):
        super().__init__()
        self.forbidden = forbidden
        self.requests = []

    async def write_gatt_char(self, char_specifier, data, response=None):
        cmd = struct.unpack_from("!HHHH", data)
        address, size = cmd[1], cmd[2]

        self.requests.append((address, size))

        if any(address <= f < address + size for f in self.forbidden):
            await self._callback(char_specifier, self._exception_frame())
            return

        await self._callback(char_specifier, await self._get_register(address, size))

    @staticmethod
    def _exception_frame():
        """A Modbus 'illegal data address' exception response."""
        frame = bytearray(5)
        frame[0] = 1
        frame[1] = 0x83  # READ (0x03) + 0x80
        frame[2] = 0x02
        struct.pack_into("<H", frame, -2, modbus_crc(frame[:-2]))
        return frame


class TestGroupedReadFallback(unittest.IsolatedAsyncioTestCase):
    def _device(self):
        return BluettiDevice(
            fields=[
                UIntField(FieldName.AC_P1_POWER, 100),
                UIntField(FieldName.AC_P2_POWER, 104),
                UIntField(FieldName.AC_P3_POWER, 108),
            ],
            max_register_gap=8,
        )

    async def test_grouped_read_is_a_single_request(self):
        mock = RejectingClientMock(forbidden=[])
        mock.add_r_int(100, 11)
        mock.add_r_int(104, 22)
        mock.add_r_int(108, 33)

        reader = DeviceReader(
            "00:11:00:11:00:11", self._device(), asyncio.Future, ble_client=mock
        )

        data = await reader.read()

        self.assertEqual(mock.requests, [(100, 9)])
        self.assertEqual(data.get(FieldName.AC_P1_POWER.value), 11)
        self.assertEqual(data.get(FieldName.AC_P2_POWER.value), 22)
        self.assertEqual(data.get(FieldName.AC_P3_POWER.value), 33)

    async def test_rejected_group_falls_back_to_individual_reads(self):
        # 102 sits in the gap between fields, so only the merged read
        # touches it. Every field is still individually readable.
        mock = RejectingClientMock(forbidden=[102])
        mock.add_r_int(100, 11)
        mock.add_r_int(104, 22)
        mock.add_r_int(108, 33)

        reader = DeviceReader(
            "00:11:00:11:00:11", self._device(), asyncio.Future, ble_client=mock
        )

        data = await reader.read()

        self.assertEqual(mock.requests, [(100, 9), (100, 1), (104, 1), (108, 1)])
        self.assertEqual(data.get(FieldName.AC_P1_POWER.value), 11)
        self.assertEqual(data.get(FieldName.AC_P2_POWER.value), 22)
        self.assertEqual(data.get(FieldName.AC_P3_POWER.value), 33)

    async def test_one_bad_field_does_not_lose_its_neighbours(self):
        # The rejected address is a real field this time, so it can never be
        # read - but the fields grouped with it must still come through.
        mock = RejectingClientMock(forbidden=[104])
        mock.add_r_int(100, 11)
        mock.add_r_int(108, 33)

        reader = DeviceReader(
            "00:11:00:11:00:11", self._device(), asyncio.Future, ble_client=mock
        )

        data = await reader.read()

        self.assertEqual(data.get(FieldName.AC_P1_POWER.value), 11)
        self.assertIsNone(data.get(FieldName.AC_P2_POWER.value))
        self.assertEqual(data.get(FieldName.AC_P3_POWER.value), 33)


class TestDeviceReader(unittest.IsolatedAsyncioTestCase):
    def __init__(self, methodName="runTest"):
        super().__init__(methodName)
        self.ble_mock = ClientMockNoEncryption()

        # Device type
        self.ble_mock.add_r_str(10, "AC300", 6)
        # Serial
        self.ble_mock.add_r_sn(17, 2300000000000)
        # DC input power
        self.ble_mock.add_r_int(36, 10)
        # AC input power
        self.ble_mock.add_r_int(37, 8)
        # AC output power
        self.ble_mock.add_r_int(38, 9)
        # AC output power
        self.ble_mock.add_r_int(39, 7)
        # SOC
        self.ble_mock.add_r_int(43, 78)

    async def test_read_all_correct(self):
        device = BaseDeviceV1()
        reader = DeviceReader(
            "00:11:00:11:00:11",
            device,
            asyncio.Future,
            ble_client=self.ble_mock,
        )

        data = await reader.read()

        self.assertEqual(data.get(FieldName.DEVICE_TYPE.value), "AC300")
        self.assertEqual(data.get(FieldName.DEVICE_SN.value), 2300000000000)
        self.assertEqual(data.get(FieldName.DC_INPUT_POWER.value), 10)
        self.assertEqual(data.get(FieldName.AC_INPUT_POWER.value), 8)
        self.assertEqual(data.get(FieldName.AC_OUTPUT_POWER.value), 9)
        self.assertEqual(data.get(FieldName.DC_OUTPUT_POWER.value), 7)
        self.assertEqual(data.get(FieldName.BATTERY_SOC.value), 78)

    async def test_read_soc_wrong(self):
        # SOC
        self.ble_mock.add_r_int(43, 1234)

        device = BaseDeviceV1()
        reader = DeviceReader(
            "00:11:00:11:00:11",
            device,
            asyncio.Future,
            ble_client=self.ble_mock,
        )

        data = await reader.read()

        self.assertIsNone(data.get(FieldName.BATTERY_SOC.value))
