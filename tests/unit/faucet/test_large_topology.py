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

class LargeValveTopologyTest(ValveTestBases.ValveTestNetwork):
    """ """

    topo = None
    serial = 0
    CONFIG = None
    N_VLANS = 2
    N_HOSTS = 2

    def get_serialno(self, *_args, **_kwargs):
        self.serial += 1
        return self.serial

    def setUp(self):
        pass

    def set_up(self, network_graph):
        """
        Args:
            network_graph (networkx.Graph):
        """
        host_links = {}
        host_vlans = {}
        host_n = 0
        host_links = {0: [0], 1: [1]}
        host_vlans = {0: 0, 1: 1}
        #for dp in network_graph.nodes():
        #    for _ in range(self.N_HOSTS):
        #        host_links[host_n] = [dp]
        #        host_vlans[host_n] = list(range(self.N_VLANS))
        #        host_n += 1
        switch_links = list(network_graph.edges())
        link_vlans = {edge: list(range(self.N_VLANS)) for edge in switch_links}
        dp_options = {}
        for dp in network_graph.nodes():
            dp_options[dp] = {'hardware': 'GenericTFM'}
            if dp == 0:
                dp_options[dp]['stack'] = {'priority': 1}
        self.topo = FaucetFakeOFTopoGenerator(
            '', '', '',
            host_links, host_vlans, switch_links, link_vlans,
            start_port=random.randint(1,100),
            port_order=random.sample(range(1,len(switch_links)+1), len(switch_links)),
            get_serialno=self.get_serialno)
        self.CONFIG = self.topo.get_config(
            self.N_VLANS, dp_options=dp_options)
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
    for graph in GRAPH_ATLAS:
        if (not graph or len(graph.nodes()) < 2 or not networkx.is_connected(graph)):
            continue
        test_name = 'test_%s' % graph.name
        test_func = test_generator(graph)
        setattr(LargeValveTopologyTest, test_name, test_func)
    unittest.main()
