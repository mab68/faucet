#!/usr/bin/env python

"""Unit tests run as PYTHONPATH=../../.. python3 ./test_valve.py."""

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


import copy
import unittest
from ryu.lib import mac
from ryu.lib.packet import slow
from ryu.ofproto import ether
from ryu.ofproto import ofproto_v1_3 as ofp
from ryu.ofproto import ofproto_v1_3_parser as parser
from faucet import valve_of
from faucet import valve_packet
from valve_test_lib import (
    CONFIG, DP1_CONFIG, FAUCET_MAC, GROUP_DP1_CONFIG, IDLE_DP1_CONFIG,
    ValveTestBases)

from fakeoftable import CONTROLLER_PORT


class ValveTestCase(ValveTestBases.ValveTestBig):
    """Run complete set of basic tests."""


class ValveFuzzTestCase(ValveTestBases.ValveTestSmall):
    """Test unknown ports/VLANs."""

    CONFIG = """
dps:
    s1:
%s
        interfaces:
            p1:
                number: 1
                native_vlan: 0x100
""" % DP1_CONFIG

    def setUp(self):
        self.setup_valve(self.CONFIG)

    def test_fuzz_vlan(self):
        """Test unknown VIDs/ports."""
        for _ in range(0, 3):
            for i in range(0, 64):
                self.rcv_packet(1, i, {
                    'eth_src': self.P1_V100_MAC,
                    'eth_dst': self.P2_V200_MAC,
                    'ipv4_src': '10.0.0.2',
                    'ipv4_dst': '10.0.0.3',
                    'vid': i})
            for i in range(0, 64):
                self.rcv_packet(i, 0x100, {
                    'eth_src': self.P1_V100_MAC,
                    'eth_dst': self.P2_V200_MAC,
                    'ipv4_src': '10.0.0.2',
                    'ipv4_dst': '10.0.0.3',
                    'vid': 0x100})
        # pylint: disable=no-member
        # pylint: disable=no-value-for-parameter
        cache_info = valve_packet.parse_packet_in_pkt.cache_info()
        self.assertGreater(cache_info.hits, cache_info.misses, msg=cache_info)


class ValveOFErrorTestCase(ValveTestBases.ValveTestSmall):
    """Test decoding of OFErrors."""

    def setUp(self):
        self.setup_valve(CONFIG)

    def test_oferror_parser(self):
        """Test OF error parser works"""
        for type_code, error_tuple in valve_of.OFERROR_TYPE_CODE.items():
            self.assertTrue(isinstance(type_code, int))
            type_str, error_codes = error_tuple
            self.assertTrue(isinstance(type_str, str))
            for error_code, error_str in error_codes.items():
                self.assertTrue(isinstance(error_code, int))
                self.assertTrue(isinstance(error_str, str))
        test_err = parser.OFPErrorMsg(
            datapath=None, type_=ofp.OFPET_FLOW_MOD_FAILED, code=ofp.OFPFMFC_UNKNOWN)
        self.valve.oferror(test_err)
        test_unknown_type_err = parser.OFPErrorMsg(
            datapath=None, type_=666, code=ofp.OFPFMFC_UNKNOWN)
        self.valve.oferror(test_unknown_type_err)
        test_unknown_code_err = parser.OFPErrorMsg(
            datapath=None, type_=ofp.OFPET_FLOW_MOD_FAILED, code=666)
        self.valve.oferror(test_unknown_code_err)


class ValveLACPTestCase(ValveTestBases.ValveTestSmall):
    """Test LACP."""

    CONFIG = """
dps:
    s1:
%s
        lacp_timeout: 5
        interfaces:
            p1:
                number: 1
                native_vlan: v100
                lacp: 1
            p2:
                number: 2
                native_vlan: v200
                tagged_vlans: [v100]
            p3:
                number: 3
                tagged_vlans: [v100, v200]
            p4:
                number: 4
                tagged_vlans: [v200]
            p5:
                number: 5
                tagged_vlans: [v300]
vlans:
    v100:
        vid: 0x100
    v200:
        vid: 0x200
    v300:
        vid: 0x300
""" % DP1_CONFIG

    def setUp(self):
        self.setup_valve(self.CONFIG)
        self.activate_all_ports()

    def test_lacp(self):
        """Test LACP comes up."""
        test_port = 1
        labels = self.port_labels(test_port)
        self.assertEqual(
            1, int(self.get_prom('port_lacp_state', labels=labels)))
        self.assertFalse(
            self.valve.dp.ports[1].non_stack_forwarding())
        self.rcv_packet(test_port, 0, {
            'actor_system': '0e:00:00:00:00:02',
            'partner_system': FAUCET_MAC,
            'eth_dst': slow.SLOW_PROTOCOL_MULTICAST,
            'eth_src': '0e:00:00:00:00:02',
            'actor_state_synchronization': 1})
        self.assertEqual(
            3, int(self.get_prom('port_lacp_state', labels=labels)))
        self.assertTrue(
            self.valve.dp.ports[1].non_stack_forwarding())
        self.learn_hosts()
        self.verify_expiry()

    def test_lacp_flap(self):
        """Test LACP handles state 0->1->0."""
        test_port = 1
        labels = self.port_labels(test_port)
        self.assertEqual(
            1, int(self.get_prom('port_lacp_state', labels=labels)))
        self.assertFalse(
            self.valve.dp.ports[1].non_stack_forwarding())
        self.rcv_packet(test_port, 0, {
            'actor_system': '0e:00:00:00:00:02',
            'partner_system': FAUCET_MAC,
            'eth_dst': slow.SLOW_PROTOCOL_MULTICAST,
            'eth_src': '0e:00:00:00:00:02',
            'actor_state_synchronization': 1})
        self.assertEqual(
            3, int(self.get_prom('port_lacp_state', labels=labels)))
        self.assertTrue(
            self.valve.dp.ports[1].non_stack_forwarding())
        self.learn_hosts()
        self.verify_expiry()
        self.rcv_packet(test_port, 0, {
            'actor_system': '0e:00:00:00:00:02',
            'partner_system': FAUCET_MAC,
            'eth_dst': slow.SLOW_PROTOCOL_MULTICAST,
            'eth_src': '0e:00:00:00:00:02',
            'actor_state_synchronization': 0})
        self.assertEqual(
            5, int(self.get_prom('port_lacp_state', labels=labels)))
        self.assertFalse(
            self.valve.dp.ports[1].non_stack_forwarding())

    def test_lacp_timeout(self):
        """Test LACP comes up and then times out."""
        test_port = 1
        labels = self.port_labels(test_port)
        self.assertEqual(
            1, int(self.get_prom('port_lacp_state', labels=labels)))
        self.assertFalse(
            self.valve.dp.ports[1].non_stack_forwarding())
        self.rcv_packet(test_port, 0, {
            'actor_system': '0e:00:00:00:00:02',
            'partner_system': FAUCET_MAC,
            'eth_dst': slow.SLOW_PROTOCOL_MULTICAST,
            'eth_src': '0e:00:00:00:00:02',
            'actor_state_synchronization': 1})
        self.assertEqual(
            3, int(self.get_prom('port_lacp_state', labels=labels)))
        self.assertTrue(
            self.valve.dp.ports[1].non_stack_forwarding())
        future_now = self.mock_time(10)
        expire_ofmsgs = self.valve.state_expire(future_now, None)
        self.assertTrue(expire_ofmsgs)
        self.assertEqual(
            1, int(self.get_prom('port_lacp_state', labels=labels)))
        self.assertFalse(
            self.valve.dp.ports[1].non_stack_forwarding())


class ValveActiveLACPTestCase(ValveTestBases.ValveTestSmall):
    """Test LACP."""

    CONFIG = """
dps:
    s1:
%s
        lacp_timeout: 5
        interfaces:
            p1:
                number: 1
                native_vlan: v100
                lacp: 1
                lacp_active: True
            p2:
                number: 2
                native_vlan: v200
                tagged_vlans: [v100]
            p3:
                number: 3
                tagged_vlans: [v100, v200]
            p4:
                number: 4
                tagged_vlans: [v200]
            p5:
                number: 5
                tagged_vlans: [v300]
vlans:
    v100:
        vid: 0x100
    v200:
        vid: 0x200
    v300:
        vid: 0x300
""" % DP1_CONFIG

    def setUp(self):
        self.setup_valve(self.CONFIG)
        self.activate_all_ports()

    def test_lacp(self):
        """Test LACP comes up."""
        test_port = 1
        labels = self.port_labels(test_port)
        self.assertEqual(
            1, int(self.get_prom('port_lacp_state', labels=labels)))
        # Ensure LACP packet sent.
        ofmsgs = self.valve.fast_advertise(self.mock_time(), None)[self.valve]
        self.assertTrue(self.packet_outs_from_flows(ofmsgs))
        self.rcv_packet(test_port, 0, {
            'actor_system': '0e:00:00:00:00:02',
            'partner_system': FAUCET_MAC,
            'eth_dst': slow.SLOW_PROTOCOL_MULTICAST,
            'eth_src': '0e:00:00:00:00:02',
            'actor_state_synchronization': 1})
        self.assertEqual(
            3, int(self.get_prom('port_lacp_state', labels=labels)))
        self.learn_hosts()
        self.verify_expiry()


class ValveL2LearnTestCase(ValveTestBases.ValveTestSmall):
    """Test L2 Learning"""

    def setUp(self):
        self.setup_valve(CONFIG)

    def test_expiry(self):
        learn_labels = {
            'vid': str(0x200),
            'eth_src': self.P2_V200_MAC
        }
        self.assertEqual(
            0, self.get_prom('learned_l2_port', labels=learn_labels))
        self.learn_hosts()
        self.assertEqual(
            2.0, self.get_prom('learned_l2_port', labels=learn_labels))
        self.verify_expiry()
        self.assertEqual(
            0, self.get_prom('learned_l2_port', labels=learn_labels))


class ValveMirrorTestCase(ValveTestBases.ValveTestBig):
    """Test ACL and interface mirroring."""
    # TODO: check mirror packets are present/correct

    CONFIG = """
acls:
    mirror_ospf:
        - rule:
            nw_dst: '224.0.0.5'
            dl_type: 0x800
            actions:
                mirror: p5
                allow: 1
        - rule:
            dl_type: 0x800
            actions:
                allow: 0
        - rule:
            actions:
                allow: 1
dps:
    s1:
%s
        interfaces:
            p1:
                number: 1
                native_vlan: v100
                lldp_beacon:
                    enable: True
                    system_name: "faucet"
                    port_descr: "first_port"
                acls_in: [mirror_ospf]
            p2:
                number: 2
                native_vlan: v200
                tagged_vlans: [v100]
            p3:
                number: 3
                tagged_vlans: [v100, v200]
            p4:
                number: 4
                tagged_vlans: [v200]
            p5:
                number: 5
                output_only: True
                mirror: 4
vlans:
    v100:
        vid: 0x100
        faucet_vips: ['10.0.0.254/24']
        routes:
            - route:
                ip_dst: 10.99.99.0/24
                ip_gw: 10.0.0.1
            - route:
                ip_dst: 10.99.98.0/24
                ip_gw: 10.0.0.99
    v200:
        vid: 0x200
        faucet_vips: ['fc00::1:254/112', 'fe80::1:254/64']
        routes:
            - route:
                ip_dst: 'fc00::10:0/112'
                ip_gw: 'fc00::1:1'
            - route:
                ip_dst: 'fc00::20:0/112'
                ip_gw: 'fc00::1:99'
routers:
    router1:
        bgp:
            as: 1
            connect_mode: 'passive'
            neighbor_as: 2
            port: 9179
            routerid: '1.1.1.1'
            server_addresses: ['127.0.0.1']
            neighbor_addresses: ['127.0.0.1']
            vlan: v100
""" % DP1_CONFIG

    def setUp(self):
        self.setup_valve(self.CONFIG)


if __name__ == "__main__":
    unittest.main() # pytype: disable=module-attr
