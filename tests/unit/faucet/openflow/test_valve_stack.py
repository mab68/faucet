#!/usr/bin/env python

"""Unit tests run as PYTHONPATH=../../.. python3 ./test_valve_stack.py."""

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

from valve_test_lib import (
    BASE_DP1_CONFIG, CONFIG, STACK_CONFIG, STACK_LOOP_CONFIG, ValveTestBases)


class ValveStackMCLAGTestCase(ValveTestBases.ValveTestSmall):
    """Test stacked MCLAG"""

    CONFIG = """
dps:
    s1:
%s
        stack:
            priority: 1
        interfaces:
            1:
                description: p1
                stack:
                    dp: s2
                    port: 1
            2:
                description: p2
                native_vlan: 100
            3:
                description: p3
                native_vlan: 100
                lacp: 1
            4:
                description: p4
                native_vlan: 100
                lacp: 1
    s2:
        hardware: 'GenericTFM'
        dp_id: 0x2
        interfaces:
            1:
                description: p1
                stack:
                    dp: s1
                    port: 1
            2:
                description: p2
                native_vlan: 100
            3:
                description: p3
                native_vlan: 100
                lacp: 1
            4:
                description: p4
                native_vlan: 100
                lacp: 1
""" % BASE_DP1_CONFIG

    def setUp(self):
        """Setup basic loop config"""
        self.setup_valve(self.CONFIG)

    def get_other_valves(self, valve):
        """Return other running valves"""
        return self.valves_manager._other_running_valves(valve)  # pylint: disable=protected-access

    def test_lag_flood(self):
        """Test flooding is allowed for UP & SELECTED LAG links only"""
        self.activate_all_ports()
        main_valve = self.valves_manager.valves[0x1]
        main_other_valves = self.get_other_valves(main_valve)
        # Start with all LAG links INIT & UNSELECTED
        self.validate_flood(2, 0, 3, False, 'Flooded out UNSELECTED & INIT LAG port')
        self.validate_flood(2, 0, 4, False, 'Flooded out UNSELECTED & INIT LAG port')
        # Set UP & SELECTED one s1 LAG link
        port3 = main_valve.dp.ports[3]
        port4 = main_valve.dp.ports[4]
        self.apply_ofmsgs(main_valve.lacp_update(port4, True, 1, 1, main_other_valves))
        self.apply_ofmsgs(main_valve.lacp_update(port3, False, 1, 1, main_other_valves))
        self.validate_flood(2, 0, 3, False, 'Flooded out NOSYNC LAG port')
        self.validate_flood(2, 0, 4, True, 'Did not flood out SELECTED LAG port')
        # Set UP & SELECTED s2 LAG links
        valve = self.valves_manager.valves[0x2]
        other_valves = self.get_other_valves(valve)
        for port in valve.dp.ports.values():
            if port.lacp:
                valve.lacp_update(port, True, 1, 1, other_valves)
        self.apply_ofmsgs(main_valve.lacp_update(port4, True, 1, 1, main_other_valves))
        self.apply_ofmsgs(main_valve.lacp_update(port3, False, 1, 1, main_other_valves))
        self.validate_flood(2, 0, 3, False, 'Flooded out UNSELECTED & NOSYNC LAG port')
        self.validate_flood(2, 0, 4, False, 'Flooded out UNSELECTED LAG port')
        # Set UP & SELECTED both s1 LAG links
        self.apply_ofmsgs(main_valve.lacp_update(port3, True, 1, 1, main_other_valves))
        self.apply_ofmsgs(main_valve.lacp_update(port4, True, 1, 1, main_other_valves))
        self.validate_flood(2, 0, 3, True, 'Did not flood out SELECTED LAG port')
        self.validate_flood(2, 0, 4, False, 'Flooded out multiple LAG ports')

    def test_lag_pipeline_accept(self):
        """Test packets entering through UP & SELECTED LAG links"""
        self.activate_all_ports()
        main_valve = self.valves_manager.valves[0x1]
        main_other_valves = self.get_other_valves(main_valve)
        # Packet initially rejected
        self.validate_flood(
            3, 0, None, False, 'Packet incoming through UNSELECTED & INIT port was accepted')
        self.validate_flood(
            4, 0, None, False, 'Packet incoming through UNSELECTED & INIT port was accepted')
        # Set one s1 LAG port 4 to SELECTED & UP
        port3 = main_valve.dp.ports[3]
        port4 = main_valve.dp.ports[4]
        self.apply_ofmsgs(main_valve.lacp_update(port4, True, 1, 1, main_other_valves))
        self.apply_ofmsgs(main_valve.lacp_update(port3, False, 1, 1, main_other_valves))
        self.validate_flood(
            3, 0, None, False, 'Packet incoming through NOSYNC port was accepted')
        self.validate_flood(
            4, 0, None, True, 'Packet incoming through SELECTED port was not accepted')
        # Set UP & SELECTED s2 LAG links, set one s1 port down
        valve = self.valves_manager.valves[0x2]
        other_valves = self.get_other_valves(valve)
        for port in valve.dp.ports.values():
            if port.lacp:
                valve.lacp_update(port, True, 1, 1, other_valves)
        self.apply_ofmsgs(main_valve.lacp_update(port4, True, 1, 1, main_other_valves))
        self.apply_ofmsgs(main_valve.lacp_update(port3, False, 1, 1, main_other_valves))
        self.validate_flood(
            3, 0, None, False, 'Packet incoming through UNSELECTED & NOSYNC port was accepted')
        self.validate_flood(
            4, 0, None, False, 'Packet incoming through UNSELECTED port was accepted')
        # Set UP & SELECTED both s1 LAG links
        self.apply_ofmsgs(main_valve.lacp_update(port3, True, 1, 1, main_other_valves))
        self.apply_ofmsgs(main_valve.lacp_update(port4, True, 1, 1, main_other_valves))
        self.validate_flood(
            3, 0, None, True, 'Packet incoming through SELECTED port was not accepted')
        self.validate_flood(
            4, 0, None, True, 'Packet incoming through SELECTED port was not accepted')


class ValveStackRootExtLoopProtectTestCase(ValveTestBases.ValveTestSmall):
    """External loop protect test cases"""

    CONFIG = """
dps:
    s1:
%s
        stack:
            priority: 1
        interfaces:
            1:
                description: p1
                stack:
                    dp: s2
                    port: 1
            2:
                description: p2
                native_vlan: 100
            3:
                description: p3
                native_vlan: 100
                loop_protect_external: True
            4:
                description: p4
                native_vlan: 100
                loop_protect_external: True
    s2:
        hardware: 'GenericTFM'
        dp_id: 0x2
        interfaces:
            1:
                description: p1
                stack:
                    dp: s1
                    port: 1
            2:
                description: p2
                native_vlan: 100
            3:
                description: p3
                native_vlan: 100
                loop_protect_external: True
            4:
                description: p4
                native_vlan: 100
                loop_protect_external: True
""" % BASE_DP1_CONFIG

    def setUp(self):
        self.setup_valve(self.CONFIG)
        self.set_stack_port_up(1)

    def test_loop_protect(self):
        """test basic loop protection"""
        mcast_match = {
            'in_port': 2,
            'eth_dst': mac.BROADCAST_STR,
            'vlan_vid': 0,
            'eth_type': 0x800,
            'ipv4_dst': '224.0.0.5',
        }
        self.assertTrue(
            self.table.is_output(mcast_match, port=1),
            msg='mcast packet not flooded to non-root stack')
        self.assertTrue(
            self.table.is_output(mcast_match, port=3),
            msg='mcast packet not flooded locally on root')
        self.assertFalse(
            self.table.is_output(mcast_match, port=4),
            msg='mcast packet multiply flooded externally on root')


class ValveStackChainTest(ValveTestBases.ValveTestSmall):
    """Test base class for loop stack config"""

    CONFIG = STACK_CONFIG
    DP = 's2'
    DP_ID = 2

    def setUp(self):
        """Setup basic loop config"""
        self.setup_valve(self.CONFIG)

    def learn_stack_hosts(self):
        """Learn some hosts."""
        for _ in range(2):
            self.rcv_packet(3, 0, self.pkt_match(1, 2), dp_id=1)
            self.rcv_packet(1, 0, self.pkt_match(1, 2), dp_id=2)
            self.rcv_packet(4, 0, self.pkt_match(2, 1), dp_id=2)
            self.rcv_packet(1, 0, self.pkt_match(2, 1), dp_id=1)
            self.rcv_packet(1, 0, self.pkt_match(3, 2), dp_id=3)
            self.rcv_packet(3, 0, self.pkt_match(3, 2), dp_id=2)

    def _unicast_to(self, out_port, trace=False):
        ucast_match = {
            'in_port': 4,
            'eth_src': self.P2_V100_MAC,
            'eth_dst': self.P1_V100_MAC,
            'vlan_vid': 0,
            'eth_type': 0x800,
        }
        return self.table.is_output(ucast_match, port=out_port, trace=trace)

    def _learning_from_bcast(self, in_port):
        ucast_match = {
            'in_port': in_port,
            'eth_src': self.P1_V100_MAC,
            'eth_dst': self.BROADCAST_MAC,
            'vlan_vid': self.V100,
            'eth_type': 0x800,
        }
        return self.table.is_output(ucast_match, port=CONTROLLER_PORT)

    def validate_edge_learn_ports(self):
        """Validate the switch behavior before learning, and then learn hosts"""

        # Before learning, unicast should flood to stack root and packet-in.
        self.assertFalse(self._unicast_to(1), 'unlearned unicast to stack root')
        self.assertFalse(self._unicast_to(2), 'unlearned unicast to stack root')
        self.assertTrue(self._unicast_to(3), 'unlearned unicast away from stack root')
        self.assertTrue(self._unicast_to(CONTROLLER_PORT), 'unlearned unicast learn')
        self.assertFalse(self._learning_from_bcast(1), 'learn from stack root broadcast')
        self.assertFalse(self._learning_from_bcast(4), 'learn from access port broadcast')

        self.learn_stack_hosts()

        self.assertFalse(self._unicast_to(1), 'learned unicast to stack root')
        self.assertFalse(self._unicast_to(2), 'learned unicast to stack root')
        self.assertTrue(self._unicast_to(3), 'learned unicast away from stack root')
        self.assertFalse(self._unicast_to(CONTROLLER_PORT), 'no learn from unicast')
        self.assertFalse(self._learning_from_bcast(1), 'learn from stack root broadcast')
        self.assertFalse(self._learning_from_bcast(4), 'learn from access port broadcast')

    def test_stack_learn_edge(self):
        """Test stack learned edge"""
        self.activate_all_ports()
        self.validate_edge_learn_ports()

    def test_stack_learn_root(self):
        """Test stack learned root"""
        self.update_config(self._config_edge_learn_stack_root(True))
        self.activate_all_ports()
        self.validate_edge_learn_ports()


class ValveStackLoopTest(ValveTestBases.ValveTestSmall):
    """Test base class for loop stack config"""

    CONFIG = STACK_LOOP_CONFIG

    def setUp(self):
        """Setup basic loop config"""
        self.setup_valve(self.CONFIG)

    def validate_flooding(self, rerouted=False, portup=True):
        """Validate the flooding state of the stack"""
        vid = self.V100
        self.validate_flood(1, vid, 1, False, 'flooded out input stack port')
        self.validate_flood(1, vid, 2, portup, 'not flooded to stack root')
        self.validate_flood(1, vid, 3, portup, 'not flooded to external host')
        self.validate_flood(2, vid, 1, rerouted, 'flooded out other stack port')
        self.validate_flood(2, vid, 2, False, 'flooded out input stack port')
        self.validate_flood(2, vid, 3, True, 'not flooded to external host')
        vid = 0
        self.validate_flood(3, vid, 1, rerouted, 'flooded out inactive port')
        self.validate_flood(3, vid, 2, True, 'not flooded to stack root')
        self.validate_flood(3, vid, 3, False, 'flooded out hairpin')

    def learn_stack_hosts(self):
        """Learn some hosts."""
        for _ in range(2):
            self.rcv_packet(3, 0, self.pkt_match(1, 2), dp_id=1)
            self.rcv_packet(2, 0, self.pkt_match(1, 2), dp_id=2)
            self.rcv_packet(3, 0, self.pkt_match(2, 1), dp_id=2)
            self.rcv_packet(2, 0, self.pkt_match(2, 1), dp_id=1)


class ValveStackEdgeLearnTestCase(ValveStackLoopTest):
    """Edge learning test cases"""

    def _unicast_to(self, out_port):
        ucast_match = {
            'in_port': 3,
            'eth_src': self.P1_V100_MAC,
            'eth_dst': self.P2_V100_MAC,
            'vlan_vid': 0,
            'eth_type': 0x800,
        }
        return self.table.is_output(ucast_match, port=out_port)

    def _learning_from_bcast(self, in_port):
        bcast_match = {
            'in_port': in_port,
            'eth_src': self.P2_V100_MAC,
            'eth_dst': self.BROADCAST_MAC,
            'vlan_vid': self.V100,
            'eth_type': 0x800,
        }
        return self.table.is_output(bcast_match, port=CONTROLLER_PORT)

    def validate_edge_learn_ports(self):
        """Validate the switch behavior before learning, and then learn hosts"""

        # Before learning, unicast should flood to stack root and packet-in.
        self.assertFalse(self._unicast_to(1), 'unicast direct to edge')
        self.assertTrue(self._unicast_to(2), 'unicast to stack root')
        self.assertTrue(self._unicast_to(CONTROLLER_PORT), 'learn from unicast')

        self.assertTrue(self._learning_from_bcast(2), 'learn from stack root broadcast')

        self.learn_stack_hosts()

        self.assertFalse(self._unicast_to(CONTROLLER_PORT), 'learn from unicast')

    def test_edge_learn_edge_port(self):
        """Check the behavior of the basic edge_learn_port algorithm"""

        self.activate_all_ports()

        self.validate_edge_learn_ports()

        # After learning, unicast should go direct to edge switch.
        self.assertTrue(self._unicast_to(1), 'unicast direct to edge')
        self.assertFalse(self._unicast_to(2), 'unicast to stack root')

        # TODO: This should be False to prevent unnecessary packet-ins.
        self.assertTrue(self._learning_from_bcast(2), 'learn from stack root broadcast')

    def test_edge_learn_stack_root(self):
        """Check the behavior of learning always towards stack root"""

        self.update_config(self._config_edge_learn_stack_root(True))

        self.activate_all_ports()

        self.validate_edge_learn_ports()

        # After learning, unicast should go to stack root, and no more learning from root.
        self.assertFalse(self._unicast_to(1), 'unicast direct to edge')
        self.assertTrue(self._unicast_to(2), 'unicast to stack root')
        self.assertFalse(self._learning_from_bcast(2), 'learn from stack root broadcast')


class ValveStackRedundantLink(ValveStackLoopTest):
    """Check stack situations with a redundant link"""

    def test_loop_protect(self):
        """Basic loop protection check"""
        self.activate_all_ports()
        mcast_match = {
            'in_port': 3,
            'eth_dst': mac.BROADCAST_STR,
            'vlan_vid': 0,
            'eth_type': 0x800,
            'ipv4_dst': '224.0.0.5',
        }
        self.assertTrue(
            self.table.is_output(mcast_match, port=2),
            msg='mcast packet not flooded to root of stack')
        self.assertFalse(self.valve.dp.ports[2].non_stack_forwarding())
        self.assertFalse(
            self.table.is_output(mcast_match, port=1),
            msg='mcast packet flooded root of stack via not shortest path')
        self.deactivate_stack_port(self.valve.dp.ports[2])
        self.assertFalse(self.valve.dp.ports[2].non_stack_forwarding())
        self.assertFalse(
            self.table.is_output(mcast_match, port=2),
            msg='mcast packet flooded to root of stack via redundant path')
        self.assertFalse(self.valve.dp.ports[2].non_stack_forwarding())
        self.assertTrue(
            self.table.is_output(mcast_match, port=1),
            msg='mcast packet not flooded root of stack')
        self.assertFalse(self.valve.dp.ports[2].non_stack_forwarding())
        self.assertTrue(self.valve.dp.ports[3].non_stack_forwarding())


class ValveStackNonRootExtLoopProtectTestCase(ValveTestBases.ValveTestSmall):
    """Test non-root external loop protect"""

    CONFIG = """
dps:
    s1:
%s
        interfaces:
            1:
                description: p1
                stack:
                    dp: s2
                    port: 1
            2:
                description: p2
                native_vlan: 100
            3:
                description: p3
                native_vlan: 100
                loop_protect_external: True
            4:
                description: p4
                native_vlan: 100
                loop_protect_external: True
    s2:
        hardware: 'GenericTFM'
        dp_id: 0x2
        interfaces:
            1:
                description: p1
                stack:
                    dp: s1
                    port: 1
            2:
                description: p2
                stack:
                    dp: s3
                    port: 1
            3:
                description: p2
                native_vlan: 100
    s3:
        hardware: 'GenericTFM'
        dp_id: 0x3
        stack:
            priority: 1
        interfaces:
            1:
                description: p1
                stack:
                    dp: s2
                    port: 2
            2:
                description: p2
                native_vlan: 100
""" % BASE_DP1_CONFIG

    def setUp(self):
        self.setup_valve(self.CONFIG)
        self.set_stack_port_up(1)

    def test_loop_protect(self):
        """Test expected table outputs for external loop protect"""
        mcast_match = {
            'in_port': 2,
            'eth_dst': mac.BROADCAST_STR,
            'vlan_vid': 0,
            'eth_type': 0x800,
            'ipv4_dst': '224.0.0.5',
        }
        self.assertTrue(
            self.table.is_output(mcast_match, port=1),
            msg='mcast packet not flooded to root of stack')
        self.assertFalse(
            self.table.is_output(mcast_match, port=3),
            msg='mcast packet flooded locally on non-root')
        self.assertFalse(
            self.table.is_output(mcast_match, port=4),
            msg='mcast packet flooded locally on non-root')


class ValveRootStackTestCase(ValveTestBases.ValveTestSmall):
    """Test stacking/forwarding."""

    DP = 's3'
    DP_ID = 0x3

    def setUp(self):
        self.setup_valve(CONFIG)
        self.set_stack_port_up(5)

    def test_stack_flood(self):
        """Test packet flooding when stacking."""
        matches = [
            {
                'in_port': 1,
                'vlan_vid': 0,
                'eth_src': self.P1_V300_MAC
            }]
        self.verify_flooding(matches)


class ValveEdgeStackTestCase(ValveTestBases.ValveTestSmall):
    """Test stacking/forwarding."""

    DP = 's4'
    DP_ID = 0x4

    def setUp(self):
        self.setup_valve(CONFIG)
        self.set_stack_port_up(5)

    def test_stack_flood(self):
        """Test packet flooding when stacking."""
        matches = [
            {
                'in_port': 1,
                'vlan_vid': 0,
                'eth_src': self.P1_V300_MAC
            }]
        self.verify_flooding(matches)

    def test_no_unexpressed_packetin(self):
        """Test host learning on stack root."""
        unexpressed_vid = 0x666 | ofp.OFPVID_PRESENT
        match = {
            'vlan_vid': unexpressed_vid,
            'eth_dst': self.UNKNOWN_MAC}
        self.assertFalse(
            self.table.is_output(match, port=ofp.OFPP_CONTROLLER, vid=unexpressed_vid))


class ValveStackGraphBreakTestCase(ValveStackLoopTest):
    """Valve test for updating the stack graph."""

    def test_update_stack_graph(self):
        """Test stack graph port UP and DOWN updates"""

        self.activate_all_ports()
        self.validate_flooding(False)
        self.assertLessEqual(self.table.flow_count(), 33, 'table overflow')
        # Deactivate link between the two other switches, not the one under test.
        other_dp = self.valves_manager.valves[2].dp
        other_port = other_dp.ports[2]
        self.deactivate_stack_port(other_port)
        self.validate_flooding(rerouted=True)

    def _set_max_lldp_lost(self, new_value):
        """Set the interface config option max_lldp_lost"""
        config = yaml.load(self.CONFIG, Loader=yaml.SafeLoader)
        for dp in config['dps'].values():
            for interface in dp['interfaces'].values():
                if 'stack' in interface:
                    interface['max_lldp_lost'] = new_value
        return yaml.dump(config)

    def test_max_lldp_timeout(self):
        """Check that timeout can be increased"""

        port = self.valve.dp.ports[1]

        self.activate_all_ports()
        self.validate_flooding()

        # Deactivating the port stops simulating LLDP beacons.
        self.deactivate_stack_port(port, packets=1)

        # Should still work after only 1 interval (3 required by default)
        self.validate_flooding()

        # Wait for 3 more cycles, so should fail now.
        self.trigger_all_ports(packets=3)

        # Validate expected normal behavior with the port down.
        self.validate_flooding(portup=False)

        # Restore everything and set max_lldp_lost to 100.
        self.activate_stack_port(port)
        self.validate_flooding()
        new_config = self._set_max_lldp_lost(100)
        self.update_config(new_config, reload_expected=False)
        self.activate_all_ports()
        self.validate_flooding()

        # Like above, deactivate the port (stops LLDP beacons).
        self.deactivate_stack_port(port, packets=10)

        # After 10 packets (more than before), it should still work.
        self.validate_flooding()

        # But, after 100 more port should be down b/c limit is set to 100.
        self.trigger_all_ports(packets=100)
        self.validate_flooding(portup=False)


class ValveTestTunnel2DP(ValveTestBases.ValveTestSmall):
    """Test Tunnel ACL implementation"""

    SRC_ID = 5
    DST_ID = 2
    SAME_ID = 4
    NONE_ID = 3

    CONFIG = """
acls:
    src_acl:
        - rule:
            dl_type: 0x0800
            ip_proto: 1
            actions:
                output:
                    tunnel: {dp: s2, port: 1}
    dst_acl:
        - rule:
            dl_type: 0x0800
            ip_proto: 1
            actions:
                output:
                    tunnel: {dp: s1, port: 1}
    same_acl:
        - rule:
            dl_type: 0x0800
            ip_proto: 1
            actions:
                output:
                    tunnel: {dp: s1, port: 1}
    none_acl:
        - rule:
            dl_type: 0x0800
            ip_proto: 1
            actions:
                output:
                    tunnel: {dp: s2, port: 1}
vlans:
    vlan100:
        vid: 1
dps:
    s1:
        dp_id: 0x1
        hardware: 'GenericTFM'
        stack:
            priority: 1
        interfaces:
            1:
                name: src_tunnel_host
                native_vlan: vlan100
                acls_in: [src_acl]
            2:
                name: same_tunnel_host
                native_vlan: vlan100
                acls_in: [same_acl]
            3:
                stack: {dp: s2, port: 3}
            4:
                stack: {dp: s2, port: 4}
    s2:
        dp_id: 0x2
        hardware: 'GenericTFM'
        interfaces:
            1:
                name: dst_tunnel_host
                native_vlan: vlan100
                acls_in: [dst_acl]
            2:
                name: transit_tunnel_host
                native_vlan: vlan100
                acls_in: [none_acl]
            3:
                stack: {dp: s1, port: 3}
            4:
                stack: {dp: s1, port: 4}
"""

    def setUp(self):
        """Create a stacking config file."""
        self.setup_valve(self.CONFIG)
        self.activate_all_ports()
        for valve in self.valves_manager.valves.values():
            for port in valve.dp.ports.values():
                if port.stack:
                    self.set_stack_port_up(port.number, valve)

    def validate_tunnel(self, in_port, in_vid, out_port, out_vid, expected, msg):
        if in_vid:
            in_vid = in_vid | ofp.OFPVID_PRESENT
        bcast_match = {
            'in_port': in_port,
            'eth_dst': mac.BROADCAST_STR,
            'vlan_vid': in_vid,
            'eth_type': 0x0800,
            'ip_proto': 1
        }
        if out_vid:
            out_vid = out_vid | ofp.OFPVID_PRESENT
        if expected:
            self.assertTrue(self.table.is_output(bcast_match, port=out_port, vid=out_vid), msg=msg)
        else:
            self.assertFalse(self.table.is_output(bcast_match, port=out_port, vid=out_vid), msg=msg)

    def test_update_src_tunnel(self):
        """Test tunnel rules when encapsulating and forwarding to the destination switch"""
        valve = self.valves_manager.valves[0x1]
        port = valve.dp.ports[3]
        # Apply tunnel to ofmsgs on valve
        self.apply_ofmsgs(valve.get_tunnel_flowmods())
        # Should encapsulate and output packet towards tunnel destination s3
        self.validate_tunnel(
            1, 0, 3, self.SRC_ID, True,
            'Did not encapsulate and forward')
        # Set the chosen port down to force a recalculation on the tunnel path
        self.set_port_down(port.number)
        ofmsgs = valve.get_tunnel_flowmods()
        self.assertTrue(ofmsgs, 'No tunnel ofmsgs returned after a topology change')
        self.apply_ofmsgs(ofmsgs)
        # Should encapsulate and output packet using the new path
        self.validate_tunnel(
            1, 0, 4, self.SRC_ID, True,
            'Did not encapsulate and forward out re-calculated port')

    def test_update_same_tunnel(self):
        """Test tunnel rules when outputting to host on the same switch as the source"""
        valve = self.valves_manager.valves[0x1]
        self.apply_ofmsgs(valve.get_tunnel_flowmods())
        self.validate_tunnel(2, 0, 1, 0, True, 'Did not forward to host on same DP')

    def test_update_dst_tunnel(self):
        """Test a tunnel outputting to the correct tunnel destination"""
        valve = self.valves_manager.valves[0x1]
        port = valve.dp.ports[3]
        # Apply tunnel to ofmsgs on valve
        self.apply_ofmsgs(valve.get_tunnel_flowmods())
        # Should accept encapsulated packet and output to the destination host
        self.validate_tunnel(3, self.DST_ID, 1, 0, True, 'Did not output to host')
        # Set the chosen port down to force a recalculation on the tunnel path
        self.set_port_down(port.number)
        ofmsgs = valve.get_tunnel_flowmods()
        self.assertTrue(ofmsgs, 'No tunnel ofmsgs returned after a topology change')
        self.apply_ofmsgs(ofmsgs)
        # Should ccept encapsulated packet and output using the new path
        self.validate_tunnel(4, self.DST_ID, 1, 0, True, 'Did not output to host')

    def test_update_none_tunnel(self):
        """Test tunnel on a switch not using a tunnel ACL"""
        valve = self.valves_manager.valves[0x1]
        self.apply_ofmsgs(valve.get_tunnel_flowmods())
        # Should drop any packets received from the tunnel
        self.validate_tunnel(
            5, self.NONE_ID, None, None, False,
            'Should not output a packet')
        self.validate_tunnel(
            6, self.NONE_ID, None, None, False,
            'Should not output a packet')


class ValveTestTransitTunnel(ValveTestBases.ValveTestSmall):
    """Test tunnel ACL implementation"""

    TRANSIT_ID = 2

    CONFIG = """
acls:
    transit_acl:
         - rule:
            dl_type: 0x0800
            ip_proto: 1
            actions:
                output:
                    tunnel: {dp: s3, port: 1}
vlans:
    vlan100:
        vid: 1
dps:
    s1:
        dp_id: 0x1
        hardware: 'GenericTFM'
        stack:
            priority: 1
        interfaces:
            3:
                stack: {dp: s2, port: 3}
            4:
                stack: {dp: s2, port: 4}
            5:
                stack: {dp: s3, port: 5}
            6:
                stack: {dp: s3, port: 6}
    s2:
        dp_id: 0x2
        hardware: 'GenericTFM'
        interfaces:
            1:
                name: source_host
                native_vlan: vlan100
                acls_in: [transit_acl]
            3:
                stack: {dp: s1, port: 3}
            4:
                stack: {dp: s1, port: 4}
    s3:
        dp_id: 0x3
        hardware: 'GenericTFM'
        interfaces:
            1:
                name: destination_host
                native_vlan: vlan100
            5:
                stack: {dp: s1, port: 5}
            6:
                stack: {dp: s1, port: 6}
"""

    def setUp(self):
        """Create a stacking config file."""
        self.setup_valve(self.CONFIG)
        self.activate_all_ports()
        for valve in self.valves_manager.valves.values():
            for port in valve.dp.ports.values():
                if port.stack:
                    self.set_stack_port_up(port.number, valve)

    def validate_tunnel(self, in_port, in_vid, out_port, out_vid, expected, msg):
        if in_vid:
            in_vid = in_vid | ofp.OFPVID_PRESENT
        bcast_match = {
            'in_port': in_port,
            'eth_dst': mac.BROADCAST_STR,
            'vlan_vid': in_vid,
            'eth_type': 0x0800,
        }
        if out_vid:
            out_vid = out_vid | ofp.OFPVID_PRESENT
        if expected:
            self.assertTrue(self.table.is_output(bcast_match, port=out_port, vid=out_vid), msg=msg)
        else:
            self.assertFalse(self.table.is_output(bcast_match, port=out_port, vid=out_vid), msg=msg)

    def test_update_transit_tunnel(self):
        """Test a tunnel through a transit switch (forwards to the correct switch)"""
        valve = self.valves_manager.valves[0x1]
        port1 = valve.dp.ports[3]
        port2 = valve.dp.ports[5]
        # Apply tunnel to ofmsgs on valve
        self.apply_ofmsgs(valve.get_tunnel_flowmods())
        # Should accept packet from stack and output to the next switch
        self.validate_tunnel(
            3, self.TRANSIT_ID, 5, self.TRANSIT_ID, True,
            'Did not output to next switch')
        # Set the chosen port down to force a recalculation on the tunnel path
        self.set_port_down(port1.number)
        # Should accept encapsulated packet and output using the new path
        self.validate_tunnel(
            4, self.TRANSIT_ID, 5, self.TRANSIT_ID, True,
            'Did not output to next switch')
        # Set the chosen port to the next switch down to force a path recalculation
        self.set_port_down(port2.number)
        ofmsgs = valve.get_tunnel_flowmods()
        self.assertTrue(ofmsgs, 'No tunnel ofmsgs returned after a topology change')
        self.apply_ofmsgs(ofmsgs)
        # Should accept encapsulated packet and output using the new path
        self.validate_tunnel(
            4, self.TRANSIT_ID, 6, self.TRANSIT_ID, True,
            'Did not output to next switch')


class ValveTestMultipleTunnel(ValveTestBases.ValveTestSmall):
    """Test tunnel ACL implementation with multiple hosts containing tunnel ACL"""

    TUNNEL_ID = 2

    CONFIG = """
acls:
    tunnel_acl:
        - rule:
            dl_type: 0x0800
            ip_proto: 1
            actions:
                output:
                    tunnel: {dp: s2, port: 1}
vlans:
    vlan100:
        vid: 1
dps:
    s1:
        dp_id: 0x1
        hardware: 'GenericTFM'
        stack:
            priority: 1
        interfaces:
            1:
                native_vlan: vlan100
                acls_in: [tunnel_acl]
            2:
                native_vlan: vlan100
                acls_in: [tunnel_acl]
            3:
                stack: {dp: s2, port: 3}
            4:
                stack: {dp: s2, port: 4}
    s2:
        dp_id: 0x2
        hardware: 'GenericTFM'
        interfaces:
            1:
                native_vlan: vlan100
            3:
                stack: {dp: s1, port: 3}
            4:
                stack: {dp: s1, port: 4}
"""

    def setUp(self):
        """Create a stacking config file."""
        self.setup_valve(self.CONFIG)
        self.activate_all_ports()
        for valve in self.valves_manager.valves.values():
            for port in valve.dp.ports.values():
                if port.stack:
                    self.set_stack_port_up(port.number, valve)

    def validate_tunnel(self, in_port, in_vid, out_port, out_vid, expected, msg):
        if in_vid:
            in_vid = in_vid | ofp.OFPVID_PRESENT
        bcast_match = {
            'in_port': in_port,
            'eth_dst': mac.BROADCAST_STR,
            'vlan_vid': in_vid,
            'eth_type': 0x0800,
            'ip_proto': 1
        }
        if out_vid:
            out_vid = out_vid | ofp.OFPVID_PRESENT
        if expected:
            self.assertTrue(self.table.is_output(bcast_match, port=out_port, vid=out_vid), msg=msg)
        else:
            self.assertFalse(self.table.is_output(bcast_match, port=out_port, vid=out_vid), msg=msg)

    def test_tunnel_update_multiple_tunnels(self):
        """Test having multiple hosts with the same tunnel"""
        valve = self.valves_manager.valves[0x1]
        port = valve.dp.ports[3]
        # Apply tunnel to ofmsgs on valve
        self.apply_ofmsgs(valve.get_tunnel_flowmods())
        # Should encapsulate and output packet towards tunnel destination s3
        self.validate_tunnel(
            1, 0, 3, self.TUNNEL_ID, True,
            'Did not encapsulate and forward')
        self.validate_tunnel(
            2, 0, 3, self.TUNNEL_ID, True,
            'Did not encapsulate and forward')
        # Set the chosen port down to force a recalculation on the tunnel path
        self.set_port_down(port.number)
        ofmsgs = valve.get_tunnel_flowmods()
        self.assertTrue(ofmsgs, 'No tunnel ofmsgs returned after a topology change')
        self.apply_ofmsgs(ofmsgs)
        # Should encapsulate and output packet using the new path
        self.validate_tunnel(
            1, 0, 4, self.TUNNEL_ID, True,
            'Did not encapsulate and forward out re-calculated port')
        self.validate_tunnel(
            1, 0, 4, self.TUNNEL_ID, True,
            'Did not encapsulate and forward out re-calculated port')


class ValveTestOrderedTunnel2DP(ValveTestBases.ValveTestSmall):
    """Test Tunnel ACL implementation"""

    SRC_ID = 5
    DST_ID = 2
    SAME_ID = 4
    NONE_ID = 3

    CONFIG = """
acls:
    src_acl:
        - rule:
            dl_type: 0x0800
            ip_proto: 1
            actions:
                output:
                    - tunnel: {dp: s2, port: 1}
    dst_acl:
        - rule:
            dl_type: 0x0800
            ip_proto: 1
            actions:
                output:
                    - tunnel: {dp: s1, port: 1}
    same_acl:
        - rule:
            dl_type: 0x0800
            ip_proto: 1
            actions:
                output:
                    - tunnel: {dp: s1, port: 1}
    none_acl:
        - rule:
            dl_type: 0x0800
            ip_proto: 1
            actions:
                output:
                    - tunnel: {dp: s2, port: 1}
vlans:
    vlan100:
        vid: 1
dps:
    s1:
        dp_id: 0x1
        hardware: 'GenericTFM'
        stack:
            priority: 1
        interfaces:
            1:
                name: src_tunnel_host
                native_vlan: vlan100
                acls_in: [src_acl]
            2:
                name: same_tunnel_host
                native_vlan: vlan100
                acls_in: [same_acl]
            3:
                stack: {dp: s2, port: 3}
            4:
                stack: {dp: s2, port: 4}
    s2:
        dp_id: 0x2
        hardware: 'GenericTFM'
        interfaces:
            1:
                name: dst_tunnel_host
                native_vlan: vlan100
                acls_in: [dst_acl]
            2:
                name: transit_tunnel_host
                native_vlan: vlan100
                acls_in: [none_acl]
            3:
                stack: {dp: s1, port: 3}
            4:
                stack: {dp: s1, port: 4}
"""

    def setUp(self):
        """Create a stacking config file."""
        self.setup_valve(self.CONFIG)
        self.activate_all_ports()
        for valve in self.valves_manager.valves.values():
            for port in valve.dp.ports.values():
                if port.stack:
                    self.set_stack_port_up(port.number, valve)

    def validate_tunnel(self, in_port, in_vid, out_port, out_vid, expected, msg):
        if in_vid:
            in_vid = in_vid | ofp.OFPVID_PRESENT
        bcast_match = {
            'in_port': in_port,
            'eth_dst': mac.BROADCAST_STR,
            'vlan_vid': in_vid,
            'eth_type': 0x0800,
            'ip_proto': 1
        }
        if out_vid:
            out_vid = out_vid | ofp.OFPVID_PRESENT
        if expected:
            self.assertTrue(self.table.is_output(bcast_match, port=out_port, vid=out_vid), msg=msg)
        else:
            self.assertFalse(self.table.is_output(bcast_match, port=out_port, vid=out_vid), msg=msg)

    def test_update_src_tunnel(self):
        """Test tunnel rules when encapsulating and forwarding to the destination switch"""
        valve = self.valves_manager.valves[0x1]
        port = valve.dp.ports[3]
        # Apply tunnel to ofmsgs on valve
        self.apply_ofmsgs(valve.get_tunnel_flowmods())
        # Should encapsulate and output packet towards tunnel destination s3
        self.validate_tunnel(
            1, 0, 3, self.SRC_ID, True,
            'Did not encapsulate and forward')
        # Set the chosen port down to force a recalculation on the tunnel path
        self.set_port_down(port.number)
        ofmsgs = valve.get_tunnel_flowmods()
        self.assertTrue(ofmsgs, 'No tunnel ofmsgs returned after a topology change')
        self.apply_ofmsgs(ofmsgs)
        # Should encapsulate and output packet using the new path
        self.validate_tunnel(
            1, 0, 4, self.SRC_ID, True,
            'Did not encapsulate and forward out re-calculated port')

    def test_update_same_tunnel(self):
        """Test tunnel rules when outputting to host on the same switch as the source"""
        valve = self.valves_manager.valves[0x1]
        self.apply_ofmsgs(valve.get_tunnel_flowmods())
        self.validate_tunnel(2, 0, 1, 0, True, 'Did not forward to host on same DP')

    def test_update_dst_tunnel(self):
        """Test a tunnel outputting to the correct tunnel destination"""
        valve = self.valves_manager.valves[0x1]
        port = valve.dp.ports[3]
        # Apply tunnel to ofmsgs on valve
        self.apply_ofmsgs(valve.get_tunnel_flowmods())
        # Should accept encapsulated packet and output to the destination host
        self.validate_tunnel(3, self.DST_ID, 1, 0, True, 'Did not output to host')
        # Set the chosen port down to force a recalculation on the tunnel path
        self.set_port_down(port.number)
        ofmsgs = valve.get_tunnel_flowmods()
        self.assertTrue(ofmsgs, 'No tunnel ofmsgs returned after a topology change')
        self.apply_ofmsgs(ofmsgs)
        # Should ccept encapsulated packet and output using the new path
        self.validate_tunnel(4, self.DST_ID, 1, 0, True, 'Did not output to host')

    def test_update_none_tunnel(self):
        """Test tunnel on a switch not using a tunnel ACL"""
        valve = self.valves_manager.valves[0x1]
        self.apply_ofmsgs(valve.get_tunnel_flowmods())
        # Should drop any packets received from the tunnel
        self.validate_tunnel(
            5, self.NONE_ID, None, None, False,
            'Should not output a packet')
        self.validate_tunnel(
            6, self.NONE_ID, None, None, False,
            'Should not output a packet')


class ValveTestTransitOrderedTunnel(ValveTestBases.ValveTestSmall):
    """Test tunnel ACL implementation"""

    TRANSIT_ID = 2

    CONFIG = """
acls:
    transit_acl:
         - rule:
            dl_type: 0x0800
            ip_proto: 1
            actions:
                output:
                    - tunnel: {dp: s3, port: 1}
vlans:
    vlan100:
        vid: 1
dps:
    s1:
        dp_id: 0x1
        hardware: 'GenericTFM'
        stack:
            priority: 1
        interfaces:
            3:
                stack: {dp: s2, port: 3}
            4:
                stack: {dp: s2, port: 4}
            5:
                stack: {dp: s3, port: 5}
            6:
                stack: {dp: s3, port: 6}
    s2:
        dp_id: 0x2
        hardware: 'GenericTFM'
        interfaces:
            1:
                name: source_host
                native_vlan: vlan100
                acls_in: [transit_acl]
            3:
                stack: {dp: s1, port: 3}
            4:
                stack: {dp: s1, port: 4}
    s3:
        dp_id: 0x3
        hardware: 'GenericTFM'
        interfaces:
            1:
                name: destination_host
                native_vlan: vlan100
            5:
                stack: {dp: s1, port: 5}
            6:
                stack: {dp: s1, port: 6}
"""

    def setUp(self):
        """Create a stacking config file."""
        self.setup_valve(self.CONFIG)
        self.activate_all_ports()
        for valve in self.valves_manager.valves.values():
            for port in valve.dp.ports.values():
                if port.stack:
                    self.set_stack_port_up(port.number, valve)

    def validate_tunnel(self, in_port, in_vid, out_port, out_vid, expected, msg):
        if in_vid:
            in_vid = in_vid | ofp.OFPVID_PRESENT
        bcast_match = {
            'in_port': in_port,
            'eth_dst': mac.BROADCAST_STR,
            'vlan_vid': in_vid,
            'eth_type': 0x0800,
        }
        if out_vid:
            out_vid = out_vid | ofp.OFPVID_PRESENT
        if expected:
            self.assertTrue(self.table.is_output(bcast_match, port=out_port, vid=out_vid), msg=msg)
        else:
            self.assertFalse(self.table.is_output(bcast_match, port=out_port, vid=out_vid), msg=msg)

    def test_update_transit_tunnel(self):
        """Test a tunnel through a transit switch (forwards to the correct switch)"""
        valve = self.valves_manager.valves[0x1]
        port1 = valve.dp.ports[3]
        port2 = valve.dp.ports[5]
        # Apply tunnel to ofmsgs on valve
        self.apply_ofmsgs(valve.get_tunnel_flowmods())
        # Should accept packet from stack and output to the next switch
        self.validate_tunnel(
            3, self.TRANSIT_ID, 5, self.TRANSIT_ID, True,
            'Did not output to next switch')
        # Set the chosen port down to force a recalculation on the tunnel path
        self.set_port_down(port1.number)
        # Should accept encapsulated packet and output using the new path
        self.validate_tunnel(
            4, self.TRANSIT_ID, 5, self.TRANSIT_ID, True,
            'Did not output to next switch')
        # Set the chosen port to the next switch down to force a path recalculation
        self.set_port_down(port2.number)
        ofmsgs = valve.get_tunnel_flowmods()
        self.assertTrue(ofmsgs, 'No tunnel ofmsgs returned after a topology change')
        self.apply_ofmsgs(ofmsgs)
        # Should accept encapsulated packet and output using the new path
        self.validate_tunnel(
            4, self.TRANSIT_ID, 6, self.TRANSIT_ID, True,
            'Did not output to next switch')


class ValveTestMultipleOrderedTunnel(ValveTestBases.ValveTestSmall):
    """Test tunnel ACL implementation with multiple hosts containing tunnel ACL"""

    TUNNEL_ID = 2

    CONFIG = """
acls:
    tunnel_acl:
        - rule:
            dl_type: 0x0800
            ip_proto: 1
            actions:
                output:
                    - tunnel: {dp: s2, port: 1}
vlans:
    vlan100:
        vid: 1
dps:
    s1:
        dp_id: 0x1
        hardware: 'GenericTFM'
        stack:
            priority: 1
        interfaces:
            1:
                native_vlan: vlan100
                acls_in: [tunnel_acl]
            2:
                native_vlan: vlan100
                acls_in: [tunnel_acl]
            3:
                stack: {dp: s2, port: 3}
            4:
                stack: {dp: s2, port: 4}
    s2:
        dp_id: 0x2
        hardware: 'GenericTFM'
        interfaces:
            1:
                native_vlan: vlan100
            3:
                stack: {dp: s1, port: 3}
            4:
                stack: {dp: s1, port: 4}
"""

    def setUp(self):
        """Create a stacking config file."""
        self.setup_valve(self.CONFIG)
        self.activate_all_ports()
        for valve in self.valves_manager.valves.values():
            for port in valve.dp.ports.values():
                if port.stack:
                    self.set_stack_port_up(port.number, valve)

    def validate_tunnel(self, in_port, in_vid, out_port, out_vid, expected, msg):
        if in_vid:
            in_vid = in_vid | ofp.OFPVID_PRESENT
        bcast_match = {
            'in_port': in_port,
            'eth_dst': mac.BROADCAST_STR,
            'vlan_vid': in_vid,
            'eth_type': 0x0800,
            'ip_proto': 1
        }
        if out_vid:
            out_vid = out_vid | ofp.OFPVID_PRESENT
        if expected:
            self.assertTrue(self.table.is_output(bcast_match, port=out_port, vid=out_vid), msg=msg)
        else:
            self.assertFalse(self.table.is_output(bcast_match, port=out_port, vid=out_vid), msg=msg)

    def test_tunnel_update_multiple_tunnels(self):
        """Test having multiple hosts with the same tunnel"""
        valve = self.valves_manager.valves[0x1]
        port = valve.dp.ports[3]
        # Apply tunnel to ofmsgs on valve
        self.apply_ofmsgs(valve.get_tunnel_flowmods())
        # Should encapsulate and output packet towards tunnel destination s3
        self.validate_tunnel(
            1, 0, 3, self.TUNNEL_ID, True,
            'Did not encapsulate and forward')
        self.validate_tunnel(
            2, 0, 3, self.TUNNEL_ID, True,
            'Did not encapsulate and forward')
        # Set the chosen port down to force a recalculation on the tunnel path
        self.set_port_down(port.number)
        ofmsgs = valve.get_tunnel_flowmods()
        self.assertTrue(ofmsgs, 'No tunnel ofmsgs returned after a topology change')
        self.apply_ofmsgs(ofmsgs)
        # Should encapsulate and output packet using the new path
        self.validate_tunnel(
            1, 0, 4, self.TUNNEL_ID, True,
            'Did not encapsulate and forward out re-calculated port')
        self.validate_tunnel(
            1, 0, 4, self.TUNNEL_ID, True,
            'Did not encapsulate and forward out re-calculated port')


if __name__ == "__main__":
    unittest.main()  # pytype: disable=module-attr
