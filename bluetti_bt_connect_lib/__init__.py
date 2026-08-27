"""Bluetti BT Lib exports."""

__version__ = "1.5.0"
"""Single source of truth for the package version.

setup.py reads this when LIB_VERSION is not set, so an install straight from
git reports a real version rather than falling back to 0.0.0. The release
workflow checks the git tag against it and refuses to publish on a mismatch.
"""

from .base_devices import BluettiDevice
from .bluetooth import (
    DeviceReader,
    DeviceReaderConfig,
    DeviceWriter,
    DeviceRecognizerResult,
    recognize_device,
)
from .enums import *
from .fields import DeviceField, FieldName, FieldUnit, get_unit
from .utils.device_builder import build_device
