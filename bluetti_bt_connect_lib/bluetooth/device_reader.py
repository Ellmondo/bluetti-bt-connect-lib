import asyncio
import logging
import async_timeout
from typing import Any, Callable, List, cast
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from ..base_devices import BluettiDevice
from ..const import NOTIFY_UUID, WRITE_UUID
from ..registers import ReadableRegisters, DeviceRegister
from ..exceptions import ModbusError, ParseError
from ..utils.privacy import mac_loggable


class DeviceReaderConfig:
    def __init__(self, timeout: int = 60, use_encryption: bool = False):
        self.timeout = timeout
        self.use_encryption = use_encryption
        # Encryption support was removed; kept only so callers that pass
        # this positionally (e.g. the coordinator) keep working. No effect.


class DeviceReader:
    def __init__(
        self,
        mac: str,
        bluetti_device: BluettiDevice,
        future_builder_method: Callable[[], asyncio.Future[Any]],
        config: DeviceReaderConfig = DeviceReaderConfig(),
        lock: asyncio.Lock = asyncio.Lock(),
        ble_client: BleakClient | None = None,
    ):
        self.mac = mac
        self.bluetti_device = bluetti_device
        self.create_future = future_builder_method
        self.config = config
        self.polling_lock = lock

        self.ble_client = ble_client
        """Used for unittests"""

        self.logger = logging.getLogger(
            f"{__name__}.{mac_loggable(mac).replace(':', '_')}"
        )

        self.device = None
        self.client = None

        self.has_notifier = False
        self.current_registers = None
        self.notify_response = bytearray()
        self.notify_future: asyncio.Future[Any] | None = None

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
                    self.logger.debug("Searching for device")

                    if self.ble_client:
                        self.device = None
                    else:
                        self.device = await BleakScanner.find_device_by_address(
                            self.mac, timeout=5
                        )

                        if self.device is None:
                            self.logger.error("Device not found")
                            return

                    self.logger.debug("Connecting to device")

                    if self.ble_client:
                        self.client = self.ble_client
                    else:
                        self.client = await establish_connection(
                            BleakClientWithServiceCache,
                            self.device,
                            self.device.name or "Unknown Device",
                            max_attempts=10,
                        )

                    self.logger.debug("Connected to device")

                    if not self.has_notifier:
                        await self.client.start_notify(
                            NOTIFY_UUID, self._notification_handler
                        )
                        self.has_notifier = True

                    self.logger.debug("Notification handler setup complete")

                    for register in registers:
                        body = register.parse_response(
                            await self._async_send_command(register)
                        )

                        self.logger.debug("Raw data: %s", body)

                        if raw:
                            d = {}
                            d[register.starting_address] = body
                            parsed_data.update(d)
                            continue

                        parsed = self.bluetti_device.parse(
                            register.starting_address, body
                        )

                        self.logger.debug("Parsed data: %s", parsed)

                        parsed_data.update(parsed)

                    for pack in range(1, self.bluetti_device.max_packs + 1):
                        body = register.parse_response(
                            await self._async_send_command(
                                self.bluetti_device.get_pack_selector(pack),
                            )
                        )

                        # We need to wait for the powerstation to populate all registers
                        await asyncio.sleep(3)

                        for register in pack_registers:
                            body = register.parse_response(
                                await self._async_send_command(register)
                            )

                            self.logger.debug("Raw data: %s", body)

                            if raw:
                                d = {}
                                d[register.starting_address] = body
                                parsed_data.update(d)
                                continue

                            parsed = self.bluetti_device.parse(
                                register.starting_address,
                                body,
                                pack_num=pack,
                            )

                            self.logger.debug("Parsed data: %s", parsed)

                            parsed_data.update(parsed)

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
                if self.has_notifier:
                    try:
                        await self.client.stop_notify(NOTIFY_UUID)
                        self.logger.debug("Stopped notifier")
                    except:
                        # Ignore errors here
                        pass
                    self.has_notifier = False
                if self.client:
                    await self.client.disconnect()
                    self.logger.debug("Disconnected from device")

            if not parsed_data:
                return None

            return parsed_data

    async def _async_send_command(self, registers: DeviceRegister) -> bytes:
        """Send command and return response"""
        self.current_registers = registers
        self.notify_response = bytearray()
        self.notify_future = self.create_future()

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
        """Handle bt data."""
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
            self.notify_future.set_exception(
                ModbusError(
                    f"Device returned a Modbus exception response for {self.current_registers}"
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
