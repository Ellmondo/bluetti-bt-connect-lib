import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from ..const import NOTIFY_UUID
from ..utils.privacy import mac_loggable


# A caller-supplied way of locating the device. Home Assistant can pass
# bluetooth.async_ble_device_from_address here, which answers instantly from
# its own cache and picks the best proxy path - far better than the 5-second
# scan this falls back to. The library stays free of any Home Assistant
# import by taking it as a callable.
DeviceProvider = Callable[[], Optional[BLEDevice]]



class DeviceConnection:
    """A BLE connection held open across reads and writes.

    Owns the client and the single notification subscription. Everything that
    talks to the device borrows this rather than opening its own link, which
    matters for three reasons:

    * The device accepts one central at a time. Two owners means one of them
      tears down a connection the other is mid-conversation on.
    * Connection setup dominates the cost of a poll. Holding the link removes
      it from every cycle after the first.
    * A write and the read that follows it share a session, so a write
      response can be observed instead of being discarded on disconnect.

    Notifications are dispatched to whichever caller currently holds the data
    callback, so exactly one conversation runs at a time. Callers serialise
    themselves with the shared lock; this class does not lock on their behalf.
    """

    def __init__(
        self,
        address: str,
        device_provider: DeviceProvider | None = None,
        scan_timeout: int = 5,
        max_attempts: int = 10,
    ) -> None:
        self._address = address
        self._device_provider = device_provider
        self._scan_timeout = scan_timeout
        self._max_attempts = max_attempts

        self._client: BleakClientWithServiceCache | None = None
        self._data_callback: Callable[[bytes], None] | None = None
        self._disconnect_callback: Callable[[], None] | None = None
        self._keep_alive_task: asyncio.Task | None = None

        self._consecutive_failures = 0
        self._closing = False

        self._connect_count = 0
        self._connected_since: datetime | None = None
        self._connected_at = 0.0  # _monotonic(), for log messages
        self._requests_served = 0

        self.logger = logging.getLogger(
            f"{__name__}.{mac_loggable(address).replace(':', '_')}"
        )

    @property
    def address(self) -> str:
        return self._address

    @property
    def client(self) -> BleakClientWithServiceCache | None:
        return self._client

    @property
    def is_connected(self) -> bool:
        return self._client is not None and getattr(
            self._client, "is_connected", False
        )

    @property
    def consecutive_failures(self) -> int:
        """Failed connections since the last one that succeeded."""
        return self._consecutive_failures

    @property
    def connect_count(self) -> int:
        """Successful connections made by this object."""
        return self._connect_count

    @property
    def connected_since(self) -> datetime | None:
        """When the current link was established (UTC), or None if down."""
        return self._connected_since if self.is_connected else None

    @property
    def requests_served(self) -> int:
        """Requests sent on the current link, or the last one if it is down.

        Reset when a new link is made. Logged when a link fails, so a fault
        that sets in after a certain amount of traffic shows up in the log.
        """
        return self._requests_served

    def record_request(self) -> None:
        """Count one request sent on the current link."""
        self._requests_served += 1

    def describe(self) -> str:
        """The current link's age and traffic, for log messages."""
        if self._client is None:
            return "not connected"
        return (
            f"connected {_format_duration(_monotonic() - self._connected_at)}, "
            f"{self._requests_served} requests on this connection"
        )

    def set_data_callback(self, callback: Callable[[bytes], None]) -> None:
        """Claim incoming notifications for the duration of one conversation."""
        self._data_callback = callback

    def clear_data_callback(self) -> None:
        self._data_callback = None

    def set_disconnect_callback(self, callback: Callable[[], None] | None) -> None:
        """Called when the link drops, so a caller can abandon a pending read."""
        self._disconnect_callback = callback

    async def connect(self) -> bool:
        """Locate the device, connect, and subscribe to notifications."""
        self._cancel_keep_alive()
        self._closing = False
        client: BleakClientWithServiceCache | None = None

        try:
            device = await self._find_device()

            if device is None:
                self._record_failure("device not found")
                return False

            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                device.name or "Unknown Device",
                max_attempts=self._max_attempts,
                disconnected_callback=self._on_disconnected,
            )
            self._client = client

            try:
                await client.start_notify(NOTIFY_UUID, self._on_notification)
            except BleakError as err:
                if "not found" in str(err).lower():
                    # The services cached for this device do not include the
                    # notify characteristic. Clear the cache so the next
                    # attempt reads the services from the device afresh.
                    self.logger.warning(
                        "Notify characteristic missing, clearing cached services"
                    )
                    await _quietly(client.clear_cache())
                raise

        except Exception as err:
            self._client = None
            if client is not None:
                # Connected but unusable: close the link properly rather than
                # leaving it open with nothing holding a reference to it.
                await _quietly(client.disconnect())
            self._record_failure(str(err) or type(err).__name__)
            return False

        self._consecutive_failures = 0
        self._connect_count += 1
        self._connected_since = datetime.now(timezone.utc)
        self._connected_at = _monotonic()
        self._requests_served = 0
        self.logger.debug("Connected, notifications subscribed")

        return True

    def _record_failure(self, reason: str) -> None:
        self._consecutive_failures += 1

        if self._consecutive_failures > 1:
            self.logger.warning(
                "Connection failed (%d in a row): %s",
                self._consecutive_failures,
                reason,
            )
        else:
            self.logger.warning("Connection failed: %s", reason)

    async def ensure_connected(self) -> bool:
        """Reuse the existing link, reconnecting only if it has dropped."""
        self._cancel_keep_alive()

        if self.is_connected:
            return True

        self.logger.debug("No live connection, connecting")

        return await self.connect()

    async def disconnect(self) -> None:
        """Close the link and drop all state."""
        self._cancel_keep_alive()
        self._closing = True

        client = self._client
        self._client = None

        if client is not None:
            await _quietly(client.stop_notify(NOTIFY_UUID))
            await _quietly(client.disconnect())

        self.logger.debug("Disconnected")

    def schedule_disconnect(self, after_seconds: float) -> None:
        """Release the link after an idle period.

        Zero disconnects immediately, which is the old behaviour. A positive
        value holds the link open for that long - long enough to span the
        polling interval, so the connection survives between polls, but short
        enough that the Bluetti phone app can eventually get a look in. A
        negative value holds it indefinitely.
        """
        self._cancel_keep_alive()

        if after_seconds < 0:
            self.logger.debug("Holding connection open indefinitely")
            return

        self._keep_alive_task = asyncio.ensure_future(
            self._disconnect_after(after_seconds)
        )

    async def _disconnect_after(self, delay: float) -> None:
        try:
            if delay > 0:
                await asyncio.sleep(delay)
            await self.disconnect()
        except asyncio.CancelledError:
            # A new conversation started before the timer expired - the link
            # is wanted again, so leave it up.
            pass

    def _cancel_keep_alive(self) -> None:
        if self._keep_alive_task is not None and not self._keep_alive_task.done():
            self._keep_alive_task.cancel()
        self._keep_alive_task = None

    async def _find_device(self) -> BLEDevice | None:
        """Prefer the caller's lookup, fall back to scanning."""
        if self._device_provider is not None:
            device = self._device_provider()

            if device is not None:
                self.logger.debug("Device supplied by caller")
                return device

            self.logger.debug("Caller had no device, falling back to a scan")

        self.logger.debug("Scanning for device")
        device = await BleakScanner.find_device_by_address(
            self._address, timeout=self._scan_timeout
        )

        if device is None:
            self.logger.debug("Device not found")

        return device

    def _on_disconnected(self, client) -> None:
        """bleak calls this from its own task when the link drops."""
        if client is not None and self._client is not None and client is not self._client:
            # A late callback from a link that has already been replaced.
            self.logger.debug("Earlier connection reported disconnected, ignoring")
            return

        if self._closing or self._client is None:
            self.logger.debug("Device disconnected")
        else:
            self.logger.warning("Device dropped the connection (%s)", self.describe())

        self._client = None

        if self._disconnect_callback is not None:
            self._disconnect_callback()

    async def _on_notification(self, _sender: int, data: bytearray) -> None:
        if self._data_callback is None:
            self.logger.debug("Notification with no active conversation, ignoring")
            return

        self._data_callback(bytes(data))


def _monotonic() -> float:
    """time.monotonic, behind a name tests can replace without stopping the
    event loop's own clock."""
    return time.monotonic()


def _format_duration(seconds: float) -> str:
    """12s, 5m 03s, 26h 14m."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


async def _quietly(awaitable: Awaitable) -> None:
    """Await something whose failure changes nothing for the caller."""
    try:
        await awaitable
    except Exception:
        pass
