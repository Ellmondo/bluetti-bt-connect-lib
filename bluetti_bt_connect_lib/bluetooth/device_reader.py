import asyncio
import logging
import async_timeout
from typing import Any, Callable, List, cast
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from ..base_devices import BluettiDevice
from ..const import NOTIFY_UUID, WRITE_UUID
from ..registers import ReadableRegisters, DeviceRegister, WriteableRegister
from ..exceptions import ModbusError, ParseError
from ..utils.privacy import mac_loggable
from .device_connection import DeviceConnection
from .write_result import WriteResult, WriteOutcome


class DeviceReaderConfig:
    def __init__(
        self,
        timeout: int = 60,
        use_encryption: bool = False,
        keep_alive_seconds: float = 0,
    ):
        self.timeout = timeout
        self.use_encryption = use_encryption
        # Encryption support was removed; kept only so callers that pass
        # this positionally (e.g. the coordinator) keep working. No effect.

        self.keep_alive_seconds = keep_alive_seconds
        """How long to hold a shared connection open after a conversation.

        Only meaningful when a DeviceConnection is supplied. Zero disconnects
        immediately, matching the old behaviour. A value comfortably longer
        than the polling interval keeps the link up between polls, removing
        connection setup from every cycle. Negative holds it indefinitely.
        """



class DeviceReader:
    def __init__(
        self,
        mac: str,
        bluetti_device: BluettiDevice,
        future_builder_method: Callable[[], asyncio.Future[Any]],
        config: DeviceReaderConfig = DeviceReaderConfig(),
        lock: asyncio.Lock = asyncio.Lock(),
        ble_client: BleakClient | None = None,
        connection: DeviceConnection | None = None,
    ):
        self.mac = mac
        self.bluetti_device = bluetti_device
        self.create_future = future_builder_method
        self.config = config
        self.polling_lock = lock

        self.ble_client = ble_client
        """Used for unittests"""

        self.connection = connection
        """A connection shared with anything else that talks to this device.

        When supplied, the reader borrows it instead of opening its own link,
        and leaves it open afterwards for `keep_alive_seconds`. That is what
        lets a write and its confirmation share a session, and stops a write
        from tearing down a connection a poll is using.

        When None the reader behaves exactly as before: connect, read,
        disconnect.
        """

        self.logger = logging.getLogger(
            f"{__name__}.{mac_loggable(mac).replace(':', '_')}"
        )

        self.device = None
        self.client = None

        self.has_notifier = False
        self.current_registers = None
        self.notify_response = bytearray()
        self.notify_future: asyncio.Future[Any] | None = None

        self.last_exception_code: int | None = None
        """Exception code from the most recent command, if the device refused
        it. Cleared at the start of every command."""

    async def read(
        self, only_registers: List[ReadableRegisters] | None = None, raw: bool = False
    ) -> dict | None:

        registers = self.bluetti_device.get_polling_registers()
        pack_registers = self.bluetti_device.get_pack_polling_registers()

        if only_registers is not None:
            registers = only_registers
            pack_registers = []

        parsed_data: dict = {}

        self.logger.debug("Reading device registers")

        async with self.polling_lock:
            try:
                async with async_timeout.timeout(self.config.timeout):
                    if not await self._open():
                        return None

                    for register in registers:
                        parsed_data.update(await self._read_registers(register, raw))

                    for pack in range(1, self.bluetti_device.max_packs + 1):
                        # Selecting a pack is a write - it returns no register
                        # data of its own, so there is nothing here to parse.
                        await self._async_send_command(
                            self.bluetti_device.get_pack_selector(pack),
                        )

                        # We need to wait for the powerstation to populate all registers
                        await asyncio.sleep(3)

                        for register in pack_registers:
                            parsed_data.update(
                                await self._read_registers(register, raw, pack_num=pack)
                            )

            except TimeoutError:
                self.logger.warning("Timeout")
                return None
            except BleakError as err:
                self.logger.warning("Bleak error: %s", err)
                return None
            except BaseException as err:
                self.logger.warning("Unknown error %s", err)
                return None
            finally:
                await self._close()

            if not parsed_data:
                return None

            return parsed_data

    async def write(self, field: str, value: Any) -> WriteResult:
        """Write one field and report what the device said about it.

        The Modbus write function answers every request - echoing the value
        on success, or returning an exception frame with a reason. Sending a
        write and disconnecting without reading that answer, which is what
        DeviceWriter does, discards the only trustworthy signal about whether
        a setting actually took.

        This sends the write on the same connection and notification handler
        the reader already uses, so the answer arrives where it can be seen.
        """

        known = [f.name for f in self.bluetti_device.fields]

        if field not in known:
            self.logger.error("Field not supported: %s", field)
            return WriteResult(
                WriteOutcome.FAILED, field, value, detail="field not supported"
            )

        command = self.bluetti_device.build_write_command(field, value)

        if command is None:
            self.logger.error("Field is not writeable: %s", field)
            return WriteResult(
                WriteOutcome.FAILED, field, value, detail="field is not writeable"
            )

        async with self.polling_lock:
            try:
                async with async_timeout.timeout(self.config.timeout):
                    if not await self._open():
                        return WriteResult(
                            WriteOutcome.FAILED, field, value, detail="not connected"
                        )

                    self.logger.debug("Writing %s = %s", field, value)

                    response = await self._async_send_command(command)

                    return self._interpret_write(field, value, command, response)
            except (TimeoutError, asyncio.TimeoutError):
                self.logger.warning("Timeout writing %s", field)
                return WriteResult(WriteOutcome.NO_RESPONSE, field, value)
            except BleakError as err:
                self.logger.warning("Bleak error writing %s: %s", field, err)
                return WriteResult(
                    WriteOutcome.FAILED, field, value, detail=f"bleak error: {err}"
                )
            except BaseException as err:
                self.logger.warning("Unknown error writing %s: %s", field, err)
                return WriteResult(
                    WriteOutcome.FAILED, field, value, detail=str(err)
                )
            finally:
                await self._close()

    def _interpret_write(
        self, field: str, value: Any, command: DeviceRegister, response: bytes
    ) -> WriteResult:
        """Turn a raw write response into a verdict."""

        # _async_send_command swallows Modbus exceptions and returns empty
        # bytes, having already recorded the code.
        if not response:
            code = self.last_exception_code

            if code is not None:
                result = WriteResult(
                    WriteOutcome.REFUSED, field, value, exception_code=code
                )
                self.logger.warning("Write refused - %s", result)
                return result

            self.logger.warning("No response writing %s", field)
            return WriteResult(WriteOutcome.NO_RESPONSE, field, value)

        if isinstance(command, WriteableRegister):
            echoed = int.from_bytes(command.parse_response(response), "big")

            if echoed == command.value:
                self.logger.debug("Write accepted: %s = %s", field, echoed)
                return WriteResult(
                    WriteOutcome.ACCEPTED, field, value, echoed=echoed
                )

            result = WriteResult(
                WriteOutcome.MISMATCHED, field, value, echoed=echoed
            )
            self.logger.warning("%s", result)
            return result

        # Multi-register writes echo address and quantity rather than a value,
        # so a well-formed response is the whole confirmation available.
        self.logger.debug("Multi-register write acknowledged: %s", field)
        return WriteResult(WriteOutcome.ACCEPTED, field, value)

    @property
    def is_connected(self) -> bool:
        """Whether a live GATT connection is currently held open."""
        if self.connection is not None:
            return self.connection.is_connected

        return self.client is not None and getattr(self.client, "is_connected", False)

    async def _open(self) -> bool:
        """Get a usable client and notification subscription."""

        if self.connection is not None:
            if not await self.connection.ensure_connected():
                self.logger.error("Shared connection unavailable")
                return False

            self.client = self.connection.client
            self.connection.set_data_callback(self._handle_data)
            self.connection.set_disconnect_callback(self._abandon_pending)
            self.logger.debug("Using shared connection")
            return True

        self.logger.debug("Searching for device")

        if self.ble_client:
            self.device = None
            self.client = self.ble_client
        else:
            self.device = await BleakScanner.find_device_by_address(
                self.mac, timeout=5
            )

            if self.device is None:
                self.logger.error("Device not found")
                return False

            self.logger.debug("Connecting to device")
            self.client = await establish_connection(
                BleakClientWithServiceCache,
                self.device,
                self.device.name or "Unknown Device",
                max_attempts=10,
            )

        self.logger.debug("Connected to device")

        if not self.has_notifier:
            await self.client.start_notify(NOTIFY_UUID, self._notification_handler)
            self.has_notifier = True
            self.logger.debug("Notification handler setup complete")

        return True

    async def _close(self) -> None:
        """Release the connection, or hand it back if it is shared."""

        if self.connection is not None:
            self.connection.clear_data_callback()
            self.connection.set_disconnect_callback(None)
            self.connection.schedule_disconnect(self.config.keep_alive_seconds)
            return

        if self.has_notifier:
            try:
                await self.client.stop_notify(NOTIFY_UUID)
                self.logger.debug("Stopped notifier")
            except Exception:
                pass
            self.has_notifier = False

        if self.client:
            await self.client.disconnect()
            self.logger.debug("Disconnected from device")

    def _abandon_pending(self) -> None:
        """Fail a waiting command when the link drops underneath it."""
        if self.notify_future is not None and not self.notify_future.done():
            self.notify_future.set_exception(
                BleakError("Disconnected while awaiting a response")
            )

    async def _read_registers(
        self,
        register: ReadableRegisters,
        raw: bool,
        pack_num: int | None = None,
    ) -> dict:
        """Read one register request, falling back to its members on failure.

        A merged request spans the unused registers between the fields it
        covers, so a single address the device refuses to serve can make it
        reject the whole range. When that happens, read the individual fields
        the request was merged from one at a time, so one bad register only
        costs its own field rather than every field grouped with it.
        """

        response = await self._async_send_command(register)

        if response:
            return self._parse_registers(register, response, raw, pack_num)

        # An atomic read has nothing to fall back to.
        if len(register.members) <= 1:
            return {}

        self.logger.debug(
            "Grouped read %s was rejected - falling back to %d individual reads",
            register,
            len(register.members),
        )

        parsed_data: dict = {}

        for member in register.members:
            member_response = await self._async_send_command(member)

            if not member_response:
                continue

            parsed_data.update(
                self._parse_registers(member, member_response, raw, pack_num)
            )

        return parsed_data

    def _parse_registers(
        self,
        register: ReadableRegisters,
        response: bytes,
        raw: bool,
        pack_num: int | None = None,
    ) -> dict:
        """Turn one register response into parsed field values."""

        body = register.parse_response(response)

        self.logger.debug("Raw data: %s", body)

        if raw:
            return {register.starting_address: body}

        parsed = self.bluetti_device.parse(
            register.starting_address, body, pack_num=pack_num
        )

        self.logger.debug("Parsed data: %s", parsed)

        return parsed

    async def _async_send_command(self, registers: DeviceRegister) -> bytes:
        """Send command and return response"""
        self.current_registers = registers
        self.notify_response = bytearray()
        self.notify_future = self.create_future()
        self.last_exception_code = None

        command_bytes = bytes(registers)

        try:
            await self.client.write_gatt_char(WRITE_UUID, command_bytes)

            self.logger.debug("Request sent (%s)", registers)

            res = await asyncio.wait_for(self.notify_future, timeout=5)

            self.logger.debug("Got response")

            return cast(bytes, res)
        except (BleakError, asyncio.TimeoutError):
            # Connection-level failures - re-raise so the caller can abort
            # cleanly and disconnect, rather than continuing to attempt
            # further register reads on an already-broken connection.
            self.logger.warning("Error while reading data")
            raise
        except ModbusError as err:
            # Device explicitly rejected this register - log and move on.
            self.logger.debug("Modbus exception for %s: %s", registers, err)
        except ParseError as err:
            # Failed CRC validation - log and move on.
            self.logger.debug("Parse error for %s: %s", registers, err)
        except Exception:
            self.logger.warning("Error while reading data")

        return bytes()

    async def _notification_handler(self, _: int, data: bytearray):
        """Notification callback for a connection this reader owns."""
        self._handle_data(bytes(data))

    def _handle_data(self, data: bytes) -> None:
        """Accumulate a response and resolve the waiting command.

        Reached either directly from bleak on a standalone connection, or
        from DeviceConnection when the link is shared. Identical either way.
        """
        self.logger.debug("Got new data (%d bytes)", len(data))

        self.notify_response.extend(data)

        if self.notify_future is None or self.notify_future.done():
            return

        if self.current_registers is None:
            return

        expected_size = self.current_registers.response_size()

        # A Modbus exception response is shorter than a normal response,
        # so check for it independently rather than gating on full length -
        # an exception frame will never reach the "normal" expected_size.
        if len(
            self.notify_response
        ) != expected_size and self.current_registers.is_exception_response(
            self.notify_response
        ):
            # Byte 2 carries the reason the device refused. Keep it: for a
            # write it is the difference between "out of range" and "the
            # device will not let you set this", and it is the only place
            # that distinction is ever stated.
            if len(self.notify_response) >= 3:
                self.last_exception_code = self.notify_response[2]

            self.notify_future.set_exception(
                ModbusError(
                    f"Device returned a Modbus exception response for "
                    f"{self.current_registers} "
                    f"(code 0x{self.last_exception_code:02x})"
                    if self.last_exception_code is not None
                    else f"Device returned a Modbus exception response for {self.current_registers}"
                )
            )
            return

        # Responses can arrive across multiple BLE fragments - wait for
        # the full expected length before validating/resolving.
        if len(self.notify_response) < expected_size:
            return

        if not self.current_registers.is_valid_response(self.notify_response):
            self.logger.debug(
                "CRC validation failed for %s: %s",
                self.current_registers,
                self.notify_response.hex(),
            )
            self.notify_future.set_exception(
                ParseError("Response failed CRC validation")
            )
            return

        self.notify_future.set_result(self.notify_response)
