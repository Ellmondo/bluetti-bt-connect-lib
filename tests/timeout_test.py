"""The overall read/write timeout (asyncio.timeout since 2.0.14) still ends
a stuck conversation cleanly instead of raising."""

import asyncio
import unittest

from bluetti_bt_connect_lib import DeviceReader, FieldName
from bluetti_bt_connect_lib.bluetooth import DeviceReaderConfig, WriteOutcome
from bluetti_bt_connect_lib.devices import DEVICES
from bluetti_bt_connect_lib.utils.bleak_client_mock import ClientMockNoEncryption


class StuckMock(ClientMockNoEncryption):
    """Accepts every request and then never answers."""

    async def write_gatt_char(self, char_specifier, data, response=None):
        await asyncio.sleep(3600)


def reader():
    return DeviceReader(
        "00:11:00:11:00:11",
        DEVICES["EP2000"](),
        asyncio.Future,
        DeviceReaderConfig(timeout=0.2),
        ble_client=StuckMock(),
    )


class TestOverallTimeout(unittest.IsolatedAsyncioTestCase):
    async def test_read_returns_none(self):
        self.assertIsNone(await asyncio.wait_for(reader().read(), 5))

    async def test_write_reports_no_response(self):
        result = await asyncio.wait_for(
            reader().write(FieldName.BATTERY_SOC_RANGE_START.value, 20), 5
        )
        self.assertEqual(result.outcome, WriteOutcome.NO_RESPONSE)


if __name__ == "__main__":
    unittest.main()
