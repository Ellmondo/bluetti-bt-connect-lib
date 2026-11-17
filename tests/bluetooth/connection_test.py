"""The shared connection: retrying after failures, clean-up of a half-made
link, statistics, and the reader dropping a link that stopped answering."""

import asyncio
import logging
import unittest
from unittest import mock

from bleak.exc import BleakError

from bluetti_bt_connect_lib.base_devices import BluettiDevice
from bluetti_bt_connect_lib.bluetooth import (
    DeviceConnection,
    DeviceReader,
    DeviceReaderConfig,
)
from bluetti_bt_connect_lib.bluetooth import device_connection as dc
from bluetti_bt_connect_lib.fields import FieldName, UIntField
from bluetti_bt_connect_lib.utils.bleak_client_mock import ClientMockNoEncryption

ADDRESS = "00:11:00:11:00:11"


class FakeDevice:
    name = "EP20000000000000000"
    address = ADDRESS


class LinkMock(ClientMockNoEncryption):
    """A client that knows whether it is connected, and can go quiet."""

    def __init__(self, answer_requests: int | None = None, notify_error=None):
        super().__init__()
        self.is_connected = True
        self.disconnect_calls = 0
        self.cleared = False
        self.answer_requests = answer_requests
        self.notify_error = notify_error
        self.requests = 0
        self.disconnected_callback = None

    async def start_notify(self, char_specifier, callback, **kwargs):
        if self.notify_error is not None:
            raise self.notify_error
        await super().start_notify(char_specifier, callback, **kwargs)

    async def write_gatt_char(self, char_specifier, data, response=None):
        self.requests += 1
        if self.answer_requests is not None and self.requests > self.answer_requests:
            return  # stopped answering, as the EBOX does when its BLE locks up
        await super().write_gatt_char(char_specifier, data, response)

    async def disconnect(self):
        self.disconnect_calls += 1
        self.is_connected = False
        if self.disconnected_callback is not None:
            self.disconnected_callback(self)

    async def clear_cache(self):
        self.cleared = True


class Harness:
    """Patches establish_connection and the clock for one DeviceConnection."""

    def __init__(self, clients):
        self.clients = list(clients)
        self.attempts = 0
        self.now = 1000.0

    async def establish(self, _cls, _device, _name, max_attempts, disconnected_callback):
        self.attempts += 1
        client = self.clients.pop(0)
        if isinstance(client, BaseException):
            raise client
        client.disconnected_callback = disconnected_callback
        return client

    def __enter__(self):
        self._patches = [
            mock.patch.object(dc, "establish_connection", self.establish),
            mock.patch.object(dc, "_monotonic", lambda: self.now),
        ]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in self._patches:
            patch.stop()


def connection():
    return DeviceConnection(ADDRESS, device_provider=lambda: FakeDevice())


class TestRetry(unittest.IsolatedAsyncioTestCase):
    async def test_every_poll_tries_again(self):
        """No back-off: after an EBOX restart the next poll reconnects."""
        failures = [BleakError("ESP_GATT_ERROR")] * 4 + [LinkMock()]
        with Harness(failures) as h:
            conn = connection()
            for count in range(1, 5):
                self.assertFalse(await conn.ensure_connected())
                self.assertEqual(conn.consecutive_failures, count)
            self.assertEqual(h.attempts, 4)

            self.assertTrue(await conn.ensure_connected())
            self.assertEqual(h.attempts, 5)
            self.assertEqual(conn.consecutive_failures, 0)

    async def test_attempts_per_connect_unchanged(self):
        self.assertEqual(connection()._max_attempts, 10)


class TestHalfMadeLink(unittest.IsolatedAsyncioTestCase):
    async def test_missing_characteristic_clears_cache_and_disconnects(self):
        client = LinkMock(
            notify_error=BleakError("Characteristic 0000ff01 was not found!")
        )
        with Harness([client]):
            conn = connection()
            with self.assertLogs(conn.logger, logging.WARNING) as logs:
                self.assertFalse(await conn.connect())

        self.assertTrue(client.cleared)
        self.assertEqual(client.disconnect_calls, 1)
        self.assertIsNone(conn.client)
        self.assertEqual(conn.consecutive_failures, 1)
        # Closing the half-made link is not reported as the device dropping it.
        self.assertFalse(any("dropped" in line for line in logs.output))

    async def test_other_notify_error_disconnects_without_clearing(self):
        client = LinkMock(notify_error=BleakError("Not connected"))
        with Harness([client]):
            conn = connection()
            self.assertFalse(await conn.connect())

        self.assertFalse(client.cleared)
        self.assertEqual(client.disconnect_calls, 1)


class TestStats(unittest.IsolatedAsyncioTestCase):
    async def test_counts(self):
        first, second = LinkMock(), LinkMock()
        with Harness([first, second]):
            conn = connection()
            self.assertIsNone(conn.connected_since)
            await conn.ensure_connected()
            self.assertEqual(conn.connect_count, 1)
            self.assertIsNotNone(conn.connected_since)

            conn.record_request()
            conn.record_request()
            self.assertEqual(conn.requests_served, 2)

            await conn.disconnect()
            self.assertIsNone(conn.connected_since)
            self.assertEqual(conn.requests_served, 2)

            await conn.ensure_connected()
            self.assertEqual(conn.connect_count, 2)
            self.assertEqual(conn.requests_served, 0)

    async def test_unexpected_drop_is_a_warning(self):
        client = LinkMock()
        with Harness([client]):
            conn = connection()
            await conn.ensure_connected()
            with self.assertLogs(conn.logger, logging.WARNING) as logs:
                client.is_connected = False
                conn._on_disconnected(client)
        self.assertIn("dropped the connection", logs.output[0])
        self.assertIsNone(conn.client)

    async def test_late_callback_from_old_link_ignored(self):
        old, new = LinkMock(), LinkMock()
        with Harness([old, new]):
            conn = connection()
            await conn.ensure_connected()
            old.is_connected = False
            await conn.ensure_connected()
            conn._on_disconnected(old)
            self.assertIs(conn.client, new)


def device():
    return BluettiDevice(fields=[UIntField(FieldName.BATTERY_SOC, 102)])


def reader(conn):
    return DeviceReader(
        ADDRESS,
        device(),
        asyncio.Future,
        DeviceReaderConfig(timeout=30, keep_alive_seconds=-1),
        connection=conn,
    )


class TestReaderOnSharedConnection(unittest.IsolatedAsyncioTestCase):
    async def test_requests_counted_and_link_kept(self):
        client = LinkMock()
        client.add_r_int(102, 55)
        with Harness([client]):
            conn = connection()
            r = reader(conn)
            data = await r.read()
            self.assertEqual(data[FieldName.BATTERY_SOC.value], 55)
            self.assertEqual(conn.requests_served, 1)
            await r.read()
            self.assertEqual(conn.requests_served, 2)
            self.assertEqual(client.disconnect_calls, 0)

    async def test_silence_drops_link_and_logs_context(self):
        client = LinkMock(answer_requests=1)
        client.add_r_int(102, 55)
        with Harness([client]), mock.patch(
            "bluetti_bt_connect_lib.bluetooth.device_reader.RESPONSE_TIMEOUT", 0.05
        ):
            conn = connection()
            r = reader(conn)
            self.assertIsNotNone(await r.read())

            with self.assertLogs(r.logger, logging.WARNING) as logs:
                self.assertIsNone(await r.read())

        self.assertEqual(client.disconnect_calls, 1)
        self.assertIsNone(conn.client)
        line = logs.output[0]
        self.assertIn("read 102+1 at slave 1", line)
        self.assertIn("2 requests on this connection", line)
        self.assertIn("dropping the connection", line)

    async def test_failed_connection_not_logged_twice(self):
        """The connection warns; the reader no longer adds an error."""
        with Harness([BleakError("one")]):
            conn = connection()
            r = reader(conn)
            with self.assertNoLogs(r.logger, level=logging.WARNING):
                self.assertIsNone(await r.read())


if __name__ == "__main__":
    unittest.main()
