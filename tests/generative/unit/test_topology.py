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


import unittest
import yaml

from ryu.lib import mac
from ryu.ofproto import ofproto_v1_3 as ofp

from mininet.topo import Topo  # pylint: disable=unused-import

import networkx
from networkx.generators.atlas import graph_atlas_g

from clib.valve_test_lib import ValveTestBases

from clib.config_generator import FaucetFakeOFTopoGenerator


class ValveGenerativeBase(ValveTestBases.ValveTestNetwork):
    """Base for generating configuration files"""

    topo = None

    NUM_PORTS = 5
    NUM_DPS = 2
    NUM_VLANS = 1
    NUM_HOSTS = 1
    SWITCH_TO_SWITCH_LINKS = 1

    PORT_ORDER = [0, 1, 2, 3]
    START_PORT = 5

    serial = 0

    @staticmethod
    def create_bcast_match(in_port, in_vid=None):
        """Return bcast match"""
        bcast_match = {
            'in_port': in_port,
            'eth_dst': mac.BROADCAST_STR,
            'eth_type': 0x0800,
            'ip_proto': 1
        }
        if in_vid:
            in_vid = in_vid | ofp.OFPVID_PRESENT
            bcast_match['vlan_vid'] = in_vid
        return bcast_match

    def get_serialno(self, *_args, **_kwargs):
        """"Return mock serial number"""
        self.serial += 1
        return self.serial

    def create_topo_config(self, network_graph):
        """Return topo object and a simple stack config generated from network_graph"""
        host_links = {}
        host_vlans = {}
        dp_options = {}
        host_n = 0
        for dp_i in network_graph.nodes():
            for _ in range(self.NUM_HOSTS):
                for v_i in range(self.NUM_VLANS):
                    host_links[host_n] = [dp_i]
                    host_vlans[host_n] = v_i
                    host_n += 1
            dp_options[dp_i] = {'hardware': 'GenericTFM'}
            if dp_i == 0:
                dp_options[dp_i]['stack'] = {'priority': 1}
        switch_links = list(network_graph.edges()) * self.SWITCH_TO_SWITCH_LINKS
        link_vlans = {link: None for link in switch_links}
        topo = FaucetFakeOFTopoGenerator(
            'ovstype', 'portsock', 'testname',
            host_links, host_vlans, switch_links, link_vlans,
            start_port=self.START_PORT, port_order=self.PORT_ORDER,
            get_serialno=self.get_serialno)
        config = topo.get_config(self.NUM_VLANS, dp_options=dp_options)
        return topo, config

    def verify_traversal(self):
        """Verify broadcasts flooding reach all destination hosts"""
        _, host_port_maps, _ = self.topo.create_port_maps()
        for src_host in host_port_maps:
            for dst_host in host_port_maps:
                if src_host == dst_host:
                    continue
                src_dpid, src_port, dst_dpid, dst_port = None, None, None, None
                for switch_n, ports in host_port_maps[src_host].items():
                    src_dpid = self.topo.dpids_by_id[switch_n]
                    src_port = ports[0]
                for switch_n, ports in host_port_maps[dst_host].items():
                    dst_dpid = self.topo.dpids_by_id[switch_n]
                    dst_port = ports[0]
                match = self.create_bcast_match(src_port)
                self.network.is_output(match, int(src_dpid), int(dst_dpid), port=dst_port)


class ValveTopologyRestartTest(ValveGenerativeBase):
    """Test warm starting to a different topology then reverting"""

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
        self.validate_topology_change(network_list)

    def validate_topology_change(self, network_list):
        """Test warm/cold-start changing topology"""
        for network_graph in network_list:
            if network_graph is network_list[0]:
                # Ignore the first one because we are already that network
                continue
            self.serial = 0
            _, new_config = self.create_topo_config(network_graph)
            self.update_and_revert_config(self.CONFIG, new_config, None)


class ValveTopologyVLANTest(ValveGenerativeBase):
    """Generative testing of flowrules after warm-starting after a config host VLAN change"""

    NUM_DPS = 2
    NUM_VLANS = 2
    NUM_HOSTS = 2
    SWITCH_TO_SWITCH_LINKS = 1

    def setUp(self):
        """Ignore, to call set_up with different topologies"""

    def set_up(self, network_graph):
        """
        Args:
            network_graph (networkx.Graph): Topology for the network
        """
        self.topo, self.CONFIG = self.create_topo_config(network_graph)
        self.setup_valves(self.CONFIG)
        self.verify_vlan_change()

    def verify_vlan_change(self):
        """Change host VLAN, check restart of rules consistent"""
        _, host_port_maps, _ = self.topo.create_port_maps()
        yaml_config = yaml.safe_load(self.CONFIG)
        intf_config = yaml_config['dps'][self.topo.switches_by_id[1]]['interfaces']
        intf_config[host_port_maps[5][1][0]]['native_vlan'] = self.topo.vlan_name(0)
        new_config = yaml.dump(yaml_config)
        self.update_and_revert_config(self.CONFIG, new_config, None)


class ValveTopologyTableTest(ValveGenerativeBase):
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
        self.verify_traversal()


class ValveTopologySpineLeafTest(ValveGenerativeBase):
    """Generative testing of Faucet with Spine & Leaf topologies"""

    topo = None
    NUM_DPS = 2
    NUM_VLANS = 1
    NUM_HOSTS = 1
    SWITCH_TO_SWITCH_LINKS = 1

    def set_up(self, topology_nodes):
        """
        Args:
            topology_nodes (tuple): (Number of spine nodes, number of leaf nodes)
        """
        self.spine_nodes, self.leaf_nodes = topology_nodes
        self.NUM_DPS = self.spine_nodes + self.leaf_nodes
        network_graph = networkx.complete_multipartite_graph(
            self.spine_nodes, self.leaf_nodes)
        self.topo, self.CONFIG = self.create_topo_config(network_graph)
        self.setup_valves(self.CONFIG)
        self.verify_traversal()


def test_generator(param):
    """Return the function that will start testing the topology/topologies"""
    def test(self):
        """Setup & test topology"""
        self.set_up(param)
    return test


def sums(length, total_sum):
    if length == 1:
        yield (total_sum,)
    else:
        for value in range(total_sum + 1):
            for permutation in sums(length - 1, total_sum - value):
                yield (value,) + permutation


if __name__ == '__main__':
    # Generate generative tests of all non-isomorphic, complete toplogies with 7 nodes or less
    GRAPHS = {}
    GRAPH_ATLAS = graph_atlas_g()
    for graph in GRAPH_ATLAS:
        if not graph or len(graph.nodes()) < 2 or not networkx.is_connected(graph):
            continue
        GRAPHS.setdefault(graph.number_of_nodes(), [])
        GRAPHS[graph.number_of_nodes()].append(graph)
        for test_class in (ValveTopologyVLANTest, ValveTopologyTableTest):
            test_name = 'test_%s' % graph.name
            test_func = test_generator(graph)
            setattr(test_class, test_name, test_func)
    for num_dps, nl in GRAPHS.items():
        chunk = 50
        batch = 1
        for test_class in (ValveTopologyRestartTest, ):
            for i in range(0, len(nl), chunk):
                test_nl = [nl[0]] + nl[i:i + chunk]
                test_name = 'test_reconfigure_topologies_%s_nodes_batch_%s' % (num_dps, batch)
                test_func = test_generator(test_nl)
                setattr(test_class, test_name, test_func)
                batch += 1

    # Iteratively generate spine & leaf networks until `MAX_SL_TESTS` stopping point
    # By testing all non-isomorphic topologies up to (and including) 7 nodes,
    #   SPINE_NODES + LEAF_NODES <= 7 are already tested
    MAX_Sl_TESTS = 5
    current_sl_nodes = 8
    current_sl_tests = 0
    # Loop until we have reached a desired number of tests
    while current_sl_tests <= MAX_Sl_TESTS:
        # Get permutations of numbers that sum to the current number of nodes
        # The current number of nodes will be split between the two partites of the topology
        for topology_nodes in sums(2, current_sl_nodes):
            if 0 in topology_nodes or topology_nodes[0] > topology_nodes[1]:
                # Ignore empty partites or inverse solutions
                continue
            test_name = 'test_%s_%s_spine_and_%s_leaf_topology' % (
                current_sl_tests, topology_nodes[0], topology_nodes[1])
            test_func = test_generator(topology_nodes)
            setattr(ValveTopologySpineLeafTest, test_name, test_func)
            current_sl_tests += 1
            if current_sl_tests > MAX_Sl_TESTS:
                break
        # Increase current number of nodes
        current_sl_nodes += 1

    # Create new tests that are copies of the previous tests but test with redundant links
    ValveTopologyVLANMultilinkTest = type(
        'ValveTopologyVLANMultilinkTest', (ValveTopologyVLANTest,), {})
    ValveTopologyVLANMultilinkTest.SWITCH_TO_SWITCH_LINKS = 2
    ValveTopologyTableMultilinkTest = type(
        'ValveTopologyTableMultilinkTest', (ValveTopologyTableTest,), {})
    ValveTopologyTableMultilinkTest.SWITCH_TO_SWITCH_LINKS = 2
    ValveTopologyRestartMultilinkTest = type(
        'ValveTopologyRestartMultilinkTest', (ValveTopologyRestartTest,), {})
    ValveTopologyRestartMultilinkTest.SWITCH_TO_SWITCH_LINKS = 2
    ValveTopologySpineLeafMultilinkTest = type(
        'ValveTopologySpineLeafMultilinkTest', (ValveTopologySpineLeafTest,), {})
    ValveTopologySpineLeafMultilinkTest.SWITCH_TO_SWITCH_LINKS = 2

    # Run unit tests
    unittest.main()
