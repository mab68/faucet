#!/usr/bin/env python3

"""Run AFL repeatedly with externally supplied generated config from STDIN."""


import logging
import tempfile
import os
import sys

import afl

from faucet import config_parser as cp

LOGNAME = 'FAUCETLOG'


def create_config_file(config):
    """Returns the config file name for a created configuration file"""
    tmpdir = tempfile.mkdtemp()
    conf_file_name = os.path.join(tmpdir, 'faucet.yaml')
    with open(conf_file_name, 'w') as conf_file:
        conf_file.write(config)
    return conf_file_name


logging.disable(logging.CRITICAL)
while afl.loop(10000):  # pylint: disable=c-extension-no-member
    sys.stdin.seek(0)
    file_name = create_config_file(sys.stdin.buffer.read())
    try:
        cp.dp_parser(file_name, LOGNAME)
    except cp.InvalidConfigError:
        pass
os._exit(0)  # pylint: disable=protected-access
