"""Setup for pypi package"""

import os
import codecs
from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))

with codecs.open(os.path.join(here, "README.md"), encoding="utf-8") as fh:
    long_description = "\n" + fh.read()

VERSION = os.getenv("LIB_VERSION")
DESCRIPTION = "Bluetti BT Connect - Bluetooth library for Bluetti power stations (fork of bluetti-bt-lib by Patrick762)"

# Setting up
setup(
    name="bluetti-bt-connect-lib",
    version=VERSION,
    author="Ellmondo",
    author_email="<CHANGE_ME@example.com>",  # TODO: replace with your contact email
    description=DESCRIPTION,
    long_description_content_type="text/markdown",
    long_description=long_description,
    url="https://github.com/Ellmondo/bluetti-bt-connect-lib",
    packages=find_packages(),
    install_requires=[
        "async_timeout",
        "asyncio",
        "bleak",
        "bleak_retry_connector",
        "crcmod",
        "logging",
    ],
    keywords=[],
    entry_points={
        "console_scripts": [
            "bluetti-scan = bluetti_bt_connect_lib.scripts.bluetti_scan:start",
            "bluetti-detect = bluetti_bt_connect_lib.scripts.bluetti_detect:start",
            "bluetti-read = bluetti_bt_connect_lib.scripts.bluetti_read:start",
            "bluetti-readall = bluetti_bt_connect_lib.scripts.bluetti_readall:start",
            "bluetti-write = bluetti_bt_connect_lib.scripts.bluetti_write:start",
            "bluetti-parse = bluetti_bt_connect_lib.scripts.bluetti_parse:start",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
    ],
)
