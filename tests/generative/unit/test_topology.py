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

#import mininet
#from mininet.topo import Topo

import networkx
from networkx.generators.atlas import graph_atlas_g

from clib.valve_test_lib import ValveTestBases
from clib.config_generator import FaucetFakeOFTopoGenerator


class ValveTopologyRestartTest(ValveTestBases.ValveTestNetwork):
    """Test auto-generated topology, warm starting to a different topology then reverting"""

    topo = None

    NUM_DPS = 2
    NUM_VLANS = 1
    NUM_HOSTS = 1
    SWITCH_TO_SWITCH_LINKS = 1

    def setUp(self):
        """Ignore, to call set_up with different network topologies"""

    def set_up(self, network_list):
        """
        Args:
            network_list (list): List of networkx graphs
        """
        self.topo, self.CONFIG = self.create_topo_config(network_list[0])
        self.setup_valves(self.CONFIG)
        self.validate_warmstarts(network_list)

    def validate_warmstarts(self, network_list):
        """Test warm/cold-start changing topology"""
        for network_graph in network_list:
            if network_graph is network_list[0]:
                # Ignore the first one because we are already that network
                continue
            _, new_config = self.create_topo_config(network_graph)
            self.update_and_revert_config(self.CONFIG, new_config, 'warm')

    @staticmethod
    def test_generator(network_list):
        """Return the function that will start the testing for a graph"""
        def test(self):
            """Test topology"""
            self.set_up(network_list)
        return test


class ValveTopologyTableTest(ValveTestBases.ValveTestNetwork):
    """Test FakeOFNetwork packet traversal with all topologies imported from the networkx atlas"""

    topo = None

    NUM_DPS = 2
    NUM_VLANS = 1
    NUM_HOSTS = 1
    SWITCH_TO_SWITCH_LINKS = 1

    def setUp(self):
        """Ignore, to call set_up with different network topologies"""

    def set_up(self, network_graph):
        """
        Args:
            network_graph (networkx.Graph): Topology for the network
        """
        self.topo, self.CONFIG = self.create_topo_config(network_graph)
        self.setup_valves(self.CONFIG)

    # TODO: Verify table traversals
    #   Verify all hosts can reach each other via flooding rules

    @staticmethod
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
        GRAPHS.setdefault(graph.number_of_nodes(), [])
        GRAPHS[graph.number_of_nodes()].append(graph)
        test_name = 'test_%s' % graph.name
        test_func = ValveTopologyTableTest.test_generator(graph)
        setattr(ValveTopologyTableTest, test_name, test_func)
        if count >= 1:
            break
        count += 1
    for num_dps, network_list in GRAPHS.items():
        test_name = 'test_reconfigure_topologies_%s' % num_dps
        test_func = ValveTopologyRestartTest.test_generator(network_list)
        setattr(ValveTopologyRestartTest, test_name, test_func)
    unittest.main()
