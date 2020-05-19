

from functools import partial
import unittest
import ipaddress
import yaml

from ryu.lib import mac
from ryu.ofproto import ofproto_v1_3 as ofp

from faucet import valves_manager
from faucet import valve_of
from faucet.port import (
    STACK_STATE_INIT, STACK_STATE_UP,
    LACP_PORT_SELECTED, LACP_PORT_UNSELECTED)

from fakeoftable import CONTROLLER_PORT

import networkx

import random

import os
import socket
import string
import shutil
import subprocess
import time

import netifaces

import mininet
from mininet.log import output
from mininet.topo import Topo

from valve_test_lib import (
    BASE_DP1_CONFIG, CONFIG, STACK_CONFIG, STACK_LOOP_CONFIG, ValveTestBases)

import sys


class ValveGraphTest(ValveTestBases.ValveTestNetwork):
    """Test an auto-generated loop topology and FakeOFNetwork packet traversal"""

    topo = None

    NUM_DPS = 3
    NUM_VLANS = 1
    NUM_HOSTS = 1
    SWITCH_TO_SWITCH_LINKS = 2

    def setUp(self):
        """ """
        sys.stderr.write('Ignoring setup\n')

    def set_up(self):
        """Setup auto-generated network topology and trigger stack ports"""
        self.topo, self.CONFIG = self.create_topo_config(networkx.cycle_graph(self.NUM_DPS))
        sys.stderr.write('Setting up\n')
        self.setup_valves(self.CONFIG)
        self.trigger_stack_ports()

    def test_network(self):
        """Test packet output to the adjacent switch in a loop topology"""
        self.set_up()
        for valve in self.valves_manager.valves.values():
            sys.stderr.write('GRAPH: %s %s %s\n' % (valve.dp, valve.dp.stack_graph.degree(), hash(tuple(sorted(valve.dp.stack_graph.degree())))))
        SWITCH_TO_SWITCH_LINKS = 2
        new_topo, new_config = self.create_topo_config(networkx.cycle_graph(self.NUM_DPS))
        self.update_and_revert_config(self.CONFIG, new_config, {new_topo.dpids_by_id[0]: 'warm'})
        for valve in self.valves_manager.valves.values():
            sys.stderr.write('GRAPH: %s %s %s\n' % (valve.dp, valve.dp.stack_graph.degree(), hash(tuple(sorted(valve.dp.stack_graph.degree())))))


if __name__ == "__main__":
    unittest.main()  # pytype: disable=module-attr