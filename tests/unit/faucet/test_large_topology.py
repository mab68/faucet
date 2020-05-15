#!/usr/bin/env python3

"""Unit tests run as PYTHONPATH=../../.. python3 ./test_large_topology.py."""

# Copyright (C) 2015 Research and Innovation Advanced Network New Zealand Ltd.
# Copyright (C) 2015--2019 The Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import random
import unittest

import mininet
from mininet.topo import Topo

import networkx
from networkx.generators.atlas import graph_atlas_g

from valve_test_lib import ValveTestBases
from clib.config_generator import FaucetFakeOFTopoGenerator

import sys

class ValveNetworkTest(ValveTestBases.ValveTestNetwork):
    """Test an auto-generated path topology and FakeOFNetwork packet traversal"""

    NUM_DPS = 2
    NUM_VLANS = 1
    NUM_HOSTS = 1
    SWITCH_TO_SWITCH_LINKS = 1

    def setUp(self):
        """Setup auto-generated network topology and trigger stack ports"""
        host_links = {}
        host_vlans = {}
        for dp_i in range(self.NUM_DPS):
            host_links[dp_i] = [dp_i]
            host_vlans[dp_i] = [0]
        network_graph = networkx.path_graph(self.NUM_DPS)
        switch_links = list(network_graph.edges()) * self.SWITCH_TO_SWITCH_LINKS
        switch_vlans = {edge: None for edge in switch_links}
        dp_options = {}
        for dp_i in network_graph.nodes():
            dp_options[dp_i] = {
                'hardware': 'GenericTFM'
            }
            if dp_i == 0:
                dp_options[dp_i]['stack'] = {'priority': 1}
        self.topo = FaucetFakeOFTopoGenerator(
            '', '', '',
            host_links, host_vlans, switch_links, link_vlans,
            start_port=1, port_order=list(range(4)), get_serialno=self.get_serialno)
        self.CONFIG = self.topo.get_config(
            self.NUM_VLANS, dp_options=dp_options)
        self.setup_valves(self.CONFIG)
        self.trigger_stack_ports()

    def test_network(self):
        """Test packet output to the adjacent switch"""
        bcast_match = {
            'in_port': 1,
            'eth_src': '00:00:00:00:00:12',
            'eth_dst': mac.BROADCAST_STR,
            'ipv4_src': '10.1.0.1',
            'ipv4_dst': '10.1.0.2',
            'vlan_vid': 0
        }
        self.assertTrue(self.network.is_output(bcast_match, 0x1, 0x2, 1, 0))


class ValveLoopNetworkTest(ValveTestBases.ValveTestNetwork):
    """Test an auto-generated loop topology and FakeOFNetwork packet traversal"""

    NUM_DPS = 3
    NUM_VLANS = 1
    NUM_HOSTS = 1
    SWITCH_TO_SWITCH_LINKS = 2

    def setUp(self):
        """Setup auto-generated network topology and trigger stack ports"""
        host_links = {}
        host_vlans = {}
        for dp_i in range(self.NUM_DPS):
            host_links[dp_i] = [dp_i]
            host_vlans[dp_i] = [0]
        network_graph = networkx.cycle_graph(self.NUM_DPS)
        switch_links = list(network_graph.edges()) * self.SWITCH_TO_SWITCH_LINKS
        switch_vlans = {edge: None for edge in switch_links}
        dp_options = {}
        for dp_i in network_graph.nodes():
            dp_options[dp_i] = {
                'hardware': 'GenericTFM'
            }
            if dp_i == 0:
                dp_options[dp_i]['stack'] = {'priority': 1}
        self.topo = FaucetFakeOFTopoGenerator(
            '', '', '',
            host_links, host_vlans, switch_links, link_vlans,
            start_port=1, port_order=list(range(4)), get_serialno=self.get_serialno)
        self.CONFIG = self.topo.get_config(
            self.NUM_VLANS, dp_options=dp_options)
        self.setup_valves(self.CONFIG)
        self.trigger_stack_ports()

    def test_network(self):
        """Test packet output to the adjacent switch in a loop topology"""
        bcast_match = {
            'in_port': 1,
            'eth_src': '00:00:00:00:00:12',
            'eth_dst': mac.BROADCAST_STR,
            'ipv4_src': '10.1.0.1',
            'ipv4_dst': '10.1.0.2',
            'vlan_vid': 0
        }
        self.assertTrue(self.network.is_output(bcast_match, 0x1, 0x3, 1, 0))
        self.assertTrue(self.network.is_output(bcast_match, 0x1, 0x2, 1, 0))
        port = self.valves_manager.valves[0x1].dp.ports[3]
        reverse_port = port.stack['port']
        self.trigger_stack_ports([port, reverse_port])
        self.assertTrue(self.network.is_output(bcast_match, 0x1, 0x3, 1, 0))
        self.assertTrue(self.network.is_output(bcast_match, 0x1, 0x2, 1, 0))


class LargeValveTopologyTest(ValveTestBases.ValveTestNetwork):
    """Test FakeOFNetwork packet traversal with all topologies imported from the networkx atlas"""

    topo = None
    CONFIG = None

    NUM_DPS = 2
    NUM_VLANS = 2
    NUM_HOSTS = 2
    SWITCH_TO_SWITCH_LINKS = 1

    def setUp(self):
        """Ignore, to call set_up with a different network topologies"""

    def set_up(self, network_graph):
        """
        Args:
            network_graph (networkx.Graph): Topology for the network
        """
        host_links = {}
        host_vlans = {}
        host_n = 0
        for dp in network_graph.nodes():
           for _ in range(self.NUM_HOSTS):
               host_links[host_n] = [dp]
               host_vlans[host_n] = list(range(self.NUM_VLANS))
               host_n += 1
        switch_links = list(network_graph.edges())
        link_vlans = {edge: list(range(self.NUM_VLANS)) for edge in switch_links}
        dp_options = {}
        for dp in network_graph.nodes():
            dp_options[dp] = {
                'hardware': 'GenericTFM'
            }
            if dp == 0:
               dp_options[dp]['stack'] = {'priority': 1}
        self.topo = FaucetFakeOFTopoGenerator(
            '', '', '',
            host_links, host_vlans, switch_links, link_vlans,
            start_port=random.randint(1,100),
            port_order=random.sample(range(1,len(switch_links)+1), len(switch_links)),
            get_serialno=self.get_serialno)
        self.CONFIG = self.topo.get_config(
            self.NUM_VLANS, dp_options=dp_options)
        self.setup_valves(self.CONFIG)


def test_generator(func_graph):
    """Return the function that will start the testing for a graph"""
    def test(self):
        """Test topology"""
        self.set_up(func_graph)
    return test


if __name__ == '__main__':
    GRAPHS = {}
    GRAPH_ATLAS = graph_atlas_g()
    count = 0
    for graph in GRAPH_ATLAS:
        if (not graph or len(graph.nodes()) < 2 or not networkx.is_connected(graph)):
            continue
        test_name = 'test_%s' % graph.name
        test_func = test_generator(graph)
        setattr(LargeValveTopologyTest, test_name, test_func)
        if count >= 1:
            break
        count += 1
    unittest.main()
