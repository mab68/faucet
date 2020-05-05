#!/usr/bin/env python3

"""Unit tests for Mininet Topologies in mininet_test_topo"""

from unittest import TestCase, main

import networkx

from clib.mininet_test_topo_generator import FaucetTopoGenerator
from clib.mininet_test_util import flat_test_name
from clib.config_generator import FaucetFakeOFTopoGenerator


class FaucetStringOfDPSwitchTopoTest(TestCase):
    """Tests for FaucetStringOfDPSwitchTopoTest"""

    serial = 0
    maxDiff = None
    dpids = ['1', '2', '3']
    vlan_vids = [100]

    def get_serialno(self, *_args, **_kwargs):
        """"Return mock serial number"""
        self.serial += 1
        return self.serial

    def string_of_dp_args(self, **kwargs):
        """Return default topo constructor params"""
        defaults = dict(
            ovs_type='user',
            ports_sock=None,
            dpids=self.dpids,
            test_name=flat_test_name(self.id()),
            get_serialno=self.get_serialno)
        defaults.update(kwargs)
        return defaults

    def test_string_of_dp_sanity(self):
        """FaucetTopoGenerator sanity test"""

        # Create a basic string topo
        n_dps = len(self.dpids)
        n_tagged = 2
        n_untagged = 2
        peer_link = FaucetTopoGenerator.peer_link
        host_links, host_vlans = FaucetTopoGenerator.tagged_untagged_hosts(
            n_dps, n_tagged, n_untagged)
        dp_links = FaucetTopoGenerator.dp_links_networkx_graph(
            networkx.path_graph(n_dps), n_dp_links=2)
        args = self.string_of_dp_args(
            dp_links=dp_links,
            host_links=host_links,
            host_vlans=host_vlans,
            vlan_vids=self.vlan_vids,
            start_port=1)
        topo = FaucetTopoGenerator(**args)

        # Verify switch ports
        ports = {dpid: topo.dpid_ports(dpid) for dpid in self.dpids}

        self.assertEqual(
            ports,
            # 4 host ports and 2/4/2 peer links, respectively
            {
                '1': [1, 2, 3, 4, 5, 6],
                '2': [1, 2, 3, 4, 5, 6, 7, 8],
                '3': [1, 2, 3, 4, 5, 6]
            },
            "switch ports are incorrect")

        # Verify peer links
        peer_links = {dpid: topo.dpid_peer_links(dpid) for dpid in self.dpids}

        self.assertEqual(
            peer_links,
            # Should be linked to previous and next switch
            {
                '1': [
                    peer_link(port=5, peer_dpid='2', peer_port=5),
                    peer_link(port=6, peer_dpid='2', peer_port=6)
                ],
                '2': [
                    peer_link(port=5, peer_dpid='1', peer_port=5),
                    peer_link(port=6, peer_dpid='1', peer_port=6),
                    peer_link(port=7, peer_dpid='3', peer_port=5),
                    peer_link(port=8, peer_dpid='3', peer_port=6)
                ],
                '3': [
                    peer_link(port=5, peer_dpid='2', peer_port=7),
                    peer_link(port=6, peer_dpid='2', peer_port=8)
                ]
            },
            "peer links are incorrect")

    def test_hw_remap(self):
        """Test remapping of attachment bridge port numbers to hw port numbers"""
        # Create a basic string topo
        peer_link = FaucetTopoGenerator.peer_link
        switch_map = {1:'p1', 2:'p2', 3:'p3', 4:'p4', 5:'p5', 6:'p6'}
        n_dps = len(self.dpids)
        n_tagged = 2
        n_untagged = 2
        host_links, host_vlans = FaucetTopoGenerator.tagged_untagged_hosts(
            n_dps, n_tagged, n_untagged)
        dp_links = FaucetTopoGenerator.dp_links_networkx_graph(
            networkx.path_graph(n_dps), n_dp_links=2)
        args = self.string_of_dp_args(
            dp_links=dp_links,
            host_links=host_links,
            host_vlans=host_vlans,
            vlan_vids=self.vlan_vids,
            start_port=5,
            hw_dpid='1',
            switch_map=switch_map)
        topo = FaucetTopoGenerator(**args)

        # Verify switch ports
        switch_ports = {dpid: topo.dpid_ports(dpid) for dpid in self.dpids}

        self.assertEqual(
            switch_ports,
            # 4 host ports and 2/4/2 peer links, respectively
            {
                # "Hardware" switch should start at 1
                '1': [1, 2, 3, 4, 5, 6],
                # Software switches start at start_port
                '2': [5, 6, 7, 8, 9, 10, 11, 12],
                '3': [5, 6, 7, 8, 9, 10]
            },
            "switch ports are incorrect")

        # Verify peer links
        peer_links = {dpid: topo.dpid_peer_links(dpid) for dpid in self.dpids}

        self.assertEqual(
            peer_links,
            # Should be linked to previous and next switch
            {
                '1': [
                    peer_link(port=5, peer_dpid='2', peer_port=9),
                    peer_link(port=6, peer_dpid='2', peer_port=10)
                ],
                '2': [
                    peer_link(port=9, peer_dpid='1', peer_port=5),
                    peer_link(port=10, peer_dpid='1', peer_port=6),
                    peer_link(port=11, peer_dpid='3', peer_port=9),
                    peer_link(port=12, peer_dpid='3', peer_port=10)
                ],
                '3': [
                    peer_link(port=9, peer_dpid='2', peer_port=11),
                    peer_link(port=10, peer_dpid='2', peer_port=12)
                ]
            },
            "peer links are incorrect")


class FaucetTopoTest(TestCase):
    """ """

    serial = 0

    START_PORT = 5
    PORT_ORDER = [0, 1, 2, 3]

    class FakeExtendedHost:
        """Fake class for a mininet extended host"""
        pass

    def get_serialno(self, *_args, **_kwargs):
        """"Return mock serial number"""
        self.serial += 1
        return self.serial

    def test_port_order(self):
        """Test port order extension & port order option"""
        port_order = [3, 2, 1, 0]
        extended = FaucetFakeOFTopoGenerator.extend_port_order(port_order, max_length=8)
        self.assertEqual(extended, [3, 2, 1, 0, 7, 6, 5, 4])
        port_order = [1, 2, 3, 4, 0]
        extended = FaucetFakeOFTopoGenerator.extend_port_order(port_order, max_length=10)
        self.assertEqual(extended, [1, 2, 3, 4, 0, 6, 7, 8, 9, 5])
        host_links = {0: [0], 1: [1]}
        host_vlans = {0: 0, 1: 0}
        switch_links = [(0, 1)]
        link_vlans = {(0, 1): [0]}
        port_order = [3, 2, 1, 0]
        expected_ports = [self.START_PORT + port for port in port_order]
        topo = FaucetFakeOFTopoGenerator(
            '', '', '',
            host_links, host_vlans, switch_links, link_vlans,
            start_port=self.START_PORT, port_order=port_order,
            get_serialno=self.get_serialno)
        s1_name = topo.switches_by_id[0]
        s1_ports = list(topo.ports[s1_name].keys())
        self.assertEqual(s1_ports, expected_ports[:2])
        s2_name = topo.switches_by_id[1]
        s2_ports = list(topo.ports[s2_name].keys())
        self.assertEqual(s2_ports, expected_ports[:2])

    def test_start_port(self):
        """Test the topology start port parameter option"""
        start_port = 55
        host_links = {0: [0], 1: [1]}
        host_vlans = {0: 0, 1: 0}
        switch_links = [(0, 1)]
        link_vlans = {(0, 1): [0]}
        port_order = [3, 2, 1, 0]
        expected_ports = [start_port + port for port in port_order]
        topo = FaucetFakeOFTopoGenerator(
            '', '', '',
            host_links, host_vlans, switch_links, link_vlans,
            start_port=start_port, port_order=port_order,
            get_serialno=self.get_serialno)
        s1_name = topo.switches_by_id[0]
        self.assertEqual(topo.ports[s1_name].keys(), expected_ports[:2])
        s2_name = topo.switches_by_id[1]
        self.assertEqual(topo.ports[s2_name].keys(), expected_ports[:2])

    def test_hw_build(self):
        """Test the topology is built with hardware requirements"""
        host_links = {0: [0], 1: [1]}
        host_vlans = {0: 0, 1: 0}
        switch_links = [(0, 1)]
        link_vlans = {(0, 1): [0]}
        hw_dpid = 0x123
        hw_ports = {1:'p1', 2:'p2', 3:'p3', 4:'p4', 5:'p5', 6:'p6'}
        topo = FaucetFakeOFTopoGenerator(
            '', '', '',
            host_links, host_vlans, switch_links, link_vlans,
            hw_dpid=hw_dpid, hw_ports=hw_ports,
            start_port=self.START_PORT, port_order=self.PORT_ORDER,
            get_serialno=self.get_serialno)
        self.assertEqual(topo.dpids_by_id[0], hw_dpid)
        self.assertEqual(topo.ports[topo.switches_by_id[0]].keys(), [1, 2])

    def test_no_links(self):
        """Test single switch topology"""
        host_links = {0: [0]}
        host_vlans = {0: 0}
        switch_links = {}
        link_vlans = {}
        topo = FaucetFakeOFTopoGenerator(
            '', '', '',
            host_links, host_vlans, switch_links, link_vlans,
            start_port=self.START_PORT, port_order=self.PORT_ORDER,
            get_serialno=self.get_serialno)
        self.assertEqual(len(topo.hosts), 1)
        self.assertEqual(len(topo.switches), 1)
        self.assertEqual(len(topo.links()), 1)
        host_name = topo.hosts_by_id[0]
        switch_name = topo.switches_by_id[0]
        self.assertEqual((switch_name, host_name), topo.links()[0])

    def test_build(self):
        """Test the topology is built correctly"""
        host_links = {0: [0], 1: [1]}
        host_vlans = {0: 0, 1: [0, 1]}
        switch_links = [(0, 1), (0, 1), (0, 1)]
        link_vlans = {(0, 1): [0, 1], (0, 1): 0, (0, 1): None}
        topo = FaucetFakeOFTopoGenerator(
            '', '', '',
            host_links, host_vlans, switch_links, link_vlans,
            start_port=self.START_PORT, port_order=self.PORT_ORDER,
            get_serialno=self.get_serialno)

    def test_host_options(self):
        """Test the topology correctly provides mininet host options"""
        host_options = {0: {'inNamespace': True, 'ip': '127.0.0.1'}, 1: {'cls': self.FakeExtendedHost}}
        host_links = {0: [0], 1: [0]}
        host_vlans = {0: 0, 1: None}
        switch_links = []
        link_vlans = {}
        topo = FaucetFakeOFTopoGenerator(
            '', '', '',
            host_links, host_vlans, switch_links, link_vlans,
            host_options=host_options,
            start_port=self.START_PORT, port_order=self.PORT_ORDER,
            get_serialno=self.get_serialno)
        for host_id, opts in host_options.items():
            info = topo.nodeInfo(topo.hosts_by_id[host_id])
            for key, value in opts.items():
                self.assertIn(key, info)
                self.assertEqual(value, info[key])


if __name__ == "__main__":
    main()
