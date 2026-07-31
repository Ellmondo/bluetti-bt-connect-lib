import asyncio
import logging
from typing import Any, Callable, List

from ..base_devices import BluettiDevice, BaseDeviceV1, BaseDeviceV2
from ..bluetooth import DeviceReader, DeviceReaderConfig
from ..devices import DEVICE_NAME_RE
from ..fields import FieldName

_LOGGER = logging.getLogger(__name__)


class DeviceRecognizerResult:
    def __init__(self, name: str, iot_version: int, sn: int | None = None):
        self.name = name
        self.iot_version = iot_version
        self.sn = sn
        self.full_name = name + str(sn)


async def recognize_device(
    mac: str,
    future_builder_method: Callable[[], asyncio.Future[Any]],
) -> DeviceRecognizerResult | None:
    # Since we don't know the type we use the base device
    bluetti_devices: List[BluettiDevice] = [
        BaseDeviceV2(),
        BaseDeviceV1(),
    ]

    for bluetti_device in bluetti_devices:
        device_reader = DeviceReader(
            mac,
            bluetti_device,
            future_builder_method,
            DeviceReaderConfig(timeout=15),
        )

        # We only need 6 registers to get the device type
        data = await device_reader.read(
            bluetti_device.get_device_type_registers(),
        )

        if data is None:
            continue

        type_data = data.get(FieldName.DEVICE_TYPE.value)

        if type_data is None:
            _LOGGER.error("No data in device type type_data")
            continue

        if not isinstance(type_data, str):
            _LOGGER.error("Invalid data in device type type_data")
            continue

        if type_data == "":
            continue

        if DEVICE_NAME_RE.match(type_data + "12345678") is None:
            _LOGGER.warning("Device has populated type_data with trash data")
            continue

        data = await device_reader.read(
            bluetti_device.get_device_sn_registers(),
        )

        if data is None:
            return DeviceRecognizerResult(
                type_data,
                bluetti_device.get_iot_version(),
                "000000000000",
            )

        sn_data = data.get(FieldName.DEVICE_SN.value)

        if not isinstance(sn_data, int) or sn_data == "":
            return DeviceRecognizerResult(
                type_data,
                bluetti_device.get_iot_version(),
                "000000000000",
            )

        return DeviceRecognizerResult(
            type_data,
            bluetti_device.get_iot_version(),
            sn_data,
        )

    return None
