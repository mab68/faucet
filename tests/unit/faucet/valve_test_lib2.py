#!/usr/bin/env python

"""Library for test_valve.py."""

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

from collections import namedtuple
from functools import partial
import cProfile
import io
import ipaddress
import logging
import os
import pstats
import shutil
import socket
import tempfile
import time
import unittest
import yaml

from ryu.lib import mac
from ryu.lib.packet import (
    arp, ethernet, icmp, icmpv6, ipv4, ipv6, lldp, slow, packet, vlan)
from ryu.ofproto import ether, inet
from ryu.ofproto import ofproto_v1_3 as ofp
from ryu.ofproto import ofproto_v1_3_parser as parser
from prometheus_client import CollectorRegistry
from beka.route import RouteAddition, RouteRemoval
from beka.ip import IPAddress, IPPrefix

from faucet import faucet_bgp
from faucet import faucet_dot1x
from faucet import faucet_event
from faucet import faucet_metrics
from faucet import valves_manager
from faucet import valve_of
from faucet import valve_packet
from faucet import valve_util
from faucet.valve import TfmValve

from fakeoftable import FakeOFTable

class ValveTestBases:
    """Insulate test base classes from unittest so we can reuse base clases."""

    class ValveTestBase(unittest.TestCase):
        """ """



    class ValveTestSmall(unittest.TestCase):  # pytype: disable=module-attr
        """Base class for all Valve unit tests."""

        #DP = 's1'
        #DP_ID = 1

        NUM_PORTS = 5
        NUM_TABLES = 10

        P1_V100_MAC = '00:00:00:01:00:01'
        P2_V100_MAC = '00:00:00:01:00:02'
        P3_V100_MAC = '00:00:00:01:00:03'
        P1_V200_MAC = '00:00:00:02:00:01'
        P2_V200_MAC = '00:00:00:02:00:02'
        P3_V200_MAC = '00:00:00:02:00:03'
        P1_V300_MAC = '00:00:00:03:00:01'

        UNKNOWN_MAC = '00:00:00:04:00:04'
        BROADCAST_MAC = 'ff:ff:ff:ff:ff:ff'

        V100 = 0x100 | ofp.OFPVID_PRESENT
        V200 = 0x200 | ofp.OFPVID_PRESENT
        V300 = 0x300 | ofp.OFPVID_PRESENT

        LOGNAME = 'faucet'
        ICMP_PAYLOAD = bytes('A'*64, encoding='UTF-8')  # must support 64b payload.
        REQUIRE_TFM = True
        CONFIG_AUTO_REVERT = False

        def __init__(self, *args, **kwargs):
            self.valves_manager = None
            self.dot1x = None
            self.metrics = None
            self.bgp = None
            self.logger = None
            
            self.last_flows_to_dp = {}
            self.tables = {}

            self.tmpdir = None
            self.faucet_event_sock = None
            self.registry = None
            self.sock = None
            self.notifier = None
            self.config_file = None
            self.up_ports = {}
            self.mock_now_sec = 100
            super(ValveTestBases.ValveTestSmall, self).__init__(*args, **kwargs)

        def mock_time(self, increment_sec=1):
            """
            Manage a mock timer for better unit test control
            Args:
                increment_sec: Amount to increment current mock time
            Returns:
                current mock time
            """
            self.mock_now_sec += increment_sec
            return self.mock_now_sec

        def setup_valves(self, config, error_expected=0, log_stdout=False):
            """
            Set up test DP with config.
            Args:
                config:
                error_expected:
                log_stdout:
            Returns:
                initial_ofmsgs
            """
            self.tmpdir = tempfile.mkdtemp()
            self.config_file = os.path.join(self.tmpdir, 'valve_unit.yaml')
            self.faucet_event_sock = os.path.join(self.tmpdir, 'event.sock')
            logfile = 'STDOUT' if log_stdout else os.path.join(self.tmpdir, 'faucet.log')
            self.logger = valve_util.get_logger(self.LOGNAME, logfile, logging.DEBUG, 0)
            self.registry = CollectorRegistry()
            self.metrics = faucet_metrics.FaucetMetrics(reg=self.registry)  # pylint: disable=unexpected-keyword-arg
            # TODO: verify events
            self.notifier = faucet_event.FaucetEventNotifier(
                self.faucet_event_sock, self.metrics, self.logger)
            self.bgp = faucet_bgp.FaucetBgp(
                self.logger, logfile, self.metrics, self.send_flows_to_dp_by_id)
            self.dot1x = faucet_dot1x.FaucetDot1x(
                self.logger, logfile, self.metrics, self.send_flows_to_dp_by_id)
            self.valves_manager = valves_manager.ValvesManager(
                self.LOGNAME, self.logger, self.metrics, self.notifier,
                self.bgp, self.dot1x, self.CONFIG_AUTO_REVERT, self.send_flows_to_dp_by_id)
            self.notifier.start()
            initial_ofmsgs = self.update_config(config, reload_expected=False, error_expected=error_expected)
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(self.faucet_event_sock)
            for dp_id in self.valves_manager.valves:
                self.setup_valve(dp_id, error_expected)
            return initial_ofmsgs
        
        def setup_valve(self, dp_id, error_expected=0):
            """Setup & connect a single valve with dpid"""
            self.last_flows_to_dp[dp_id] = []
            self.tables[dp_id] = FakeOFTable(self.NUM_TABLES)
            if not error_expected:
                self.connect_dp(dp_id)

        def teardown_valves(self):
            """Tear down test DP."""
            for valve in self.valves_manager.valves.values():
                valve.close_logs()

        def tearDown(self):
            """Tear down the test suite"""
            valve_util.close_logger(self.logger)
            self.bgp.shutdown_bgp_speakers()
            self.teardown_valves()
            self.sock.close()
            shutil.rmtree(self.tmpdir)

        def connect_dp(self, dp_id):
            """Call DP connect and wth all ports up."""
            valve = self.valves_manager.valves[dp_id]
            discovered_up_ports = set(list(valve.dp.ports.keys())[:self.NUM_PORTS])
            connect_msgs = (
                valve.switch_features(None) +
                valve.datapath_connect(self.mock_time(10), discovered_up_ports))
            self.apply_ofmsgs(connect_msgs)
            self.valves_manager.update_config_applied(sent={dp_id: True})
            self.assertEqual(1, int(self.get_prom('dp_status')))
            self.assertTrue(valve.dp.to_conf())
            return connect_msgs

        def cold_start(self, dp_id):
            """Cold-start dataplane"""
            valve = self.valves_manager.valves[dp_id]
            valve.datapath_disconnect()
            return self.connect_dp(dp_id)

        def apply_ofmsgs(self, ofmsgs, dp_id=None):
            """Postprocess flows before sending to simulated DP."""
            if dp_id is None:
                dp_id = self.DP_ID
            valve = self.valves_manager.valves[dp_id]
            final_ofmsgs = valve.prepare_send_flows(ofmsgs)
            self.tables[dp_id].apply_ofmsgs(final_ofmsgs)
            return final_ofmsgs

        @staticmethod
        def profile(func, sortby='cumulative', amount=20, count=1):
            """Convenience method to profile a function call."""
            prof = cProfile.Profile()
            prof.enable()
            for _ in range(count):
                func()
            prof.disable()
            prof_stream = io.StringIO()
            prof_stats = pstats.Stats(prof, stream=prof_stream).sort_stats(sortby)
            prof_stats.print_stats(amount)
            return (prof_stats, prof_stream.getvalue())

        def get_prom(self, var, labels=None, bare=False, dp_name=None, dp_id=None):
            """Return a Prometheus variable value."""
            if dp_name is None:
                dp_name = self.DP_NAME
            if dp_id is None:
                dp_id = self.DP_ID
            if labels is None:
                labels = {}
            if not bare:
                labels.update({
                    'dp_name': dp,
                    'dp_id': '0x%x' % dp_id})
            val = self.registry.get_sample_value(var, labels)
            if val is None:
                val = 0
            return val

        def prom_inc(self, func, var, labels=None, inc_expected=True):
            """Check Prometheus variable increments by 1 after calling a function."""
            before = self.get_prom(var, labels)
            func()
            after = self.get_prom(var, labels)
            msg = '%s %s before %f after %f' % (var, labels, before, after)
            if inc_expected:
                self.assertEqual(before + 1, after, msg=msg)
            else:
                self.assertEqual(before, after, msg=msg)

        def send_flows_to_dp_by_id(self, valve, flows):
            """Callback for ValvesManager to simulate sending flows to DP."""
            flows = valve.prepare_send_flows(flows)
            self.last_flows_to_dp[valve.dp.dp_id] = flows

        def update_config(self, config, reload_type='cold',
                          reload_expected=True, error_expected=0):
            """Update FAUCET config with config as text."""
            before_dp_status = int(self.get_prom('dp_status'))
            existing_config = None
            if os.path.exists(self.config_file):
                with open(self.config_file) as config_file:
                    existing_config = config_file.read()
            with open(self.config_file, 'w') as config_file:
                config_file.write(config)
            content_change_expected = config != existing_config
            self.assertEqual(
                content_change_expected,
                self.valves_manager.config_watcher.content_changed(self.config_file))
            reload_ofmsgs = []
            reload_func = partial(
                self.valves_manager.request_reload_configs,
                self.mock_time(10), self.config_file)

            if error_expected:
                reload_func()
            else:
                var = 'faucet_config_reload_%s_total' % reload_type
                self.prom_inc(reload_func, var=var, inc_expected=reload_expected)
                for dp_id in self.valves_manager.valves:
                    reload_ofmsgs = self.last_flows_to_dp[dp_id]
                    # DP requested reconnection
                    if reload_ofmsgs is None:
                        reload_ofmsgs = self.connect_dp(dp_id)
                    else:
                        self.apply_ofmsgs(reload_ofmsgs, dp_id)
            self.assertEqual(before_dp_status, int(self.get_prom('dp_status')))
            self.assertEqual(error_expected, self.get_prom('faucet_config_load_error', bare=True))
            return reload_ofmsgs

        def port_labels(self, port_no, dp_id=None):
            """Get port labels"""
            if dp_id is None:
                dp_id = self.DP_ID
            valve = self.valves_manager.valves[dp_id]
            port = valve.dp.ports[port_no]
            return {'port': port.name, 'port_description': port.description}

        def port_expected_status(self, port_no, exp_status, dp_id=None):
            """Verify port has status"""
            if dp_id is None:
                dp_id = self.DP_ID
            valve = self.valves_manager.valves[dp_id]
            if port_no not in valve.dp.ports:
                return
            labels = self.port_labels(port_no, dp_id)
            status = int(self.get_prom('port_status', labels=labels))
            self.assertEqual(
                status, exp_status,
                msg='status %u != expected %u for port %s' % (
                    status, exp_status, labels))

        def set_port_down(self, port_no, dp_id=None):
            """Set port status of port to down."""
            if dp_id is None:
                dp_id = self.DP_ID
            valve = self.valves_manager.valves[dp_id]
            self.apply_ofmsgs(valve.port_status_handler(
                port_no, ofp.OFPPR_DELETE, ofp.OFPPS_LINK_DOWN, [], time.time()).get(valve, []))
            self.port_expected_status(port_no, 0)

        def set_port_up(self, port_no, dp_id=None):
            """Set port status of port to up."""
            if dp_id is None:
                dp_id = self.DP_ID
            valve = self.valves_manager.valves[dp_id]
            self.apply_ofmsgs(valve.port_status_handler(
                port_no, ofp.OFPPR_ADD, 0, [], time.time()).get(valve, []))
            self.port_expected_status(port_no, 1)

        def flap_port(self, port_no, dp_id=None):
            """Flap op status on a port."""
            self.set_port_down(port_no, dp_id)
            self.set_port_up(port_no, dp_id)

        def all_stack_up(self):
            """Bring all the ports in a stack fully up"""
            for valve in self.valves_manager.valves.values():
                valve.dp.dyn_running = True
                for port in valve.dp.stack_ports:
                    port.stack_up()

        # TODO: What to do with this...
        def up_stack_port(self, port, dp_id=None):
            """Bring up a single stack port"""
            peer_dp = port.stack['dp']
            peer_port = port.stack['port']
            for state_func in [peer_port.stack_init, peer_port.stack_up]:
                state_func()
                self.rcv_lldp(port, peer_dp, peer_port, dp_id)
            self.assertTrue(port.is_stack_up())
        def down_stack_port(self, port):
            """Bring down a single stack port"""
            self.up_stack_port(port)
            peer_port = port.stack['port']
            peer_port.stack_gone()
            now = self.mock_time(600)
            self.valves_manager.valve_flow_services(
                now,
                'fast_state_expire')
            self.assertTrue(port.is_stack_gone())

        def _update_port_map(self, port, add_else_remove):
            this_dp = port.dp_id
            this_num = port.number
            this_key = '%s:%s' % (this_dp, this_num)
            peer_dp = port.stack['dp'].dp_id
            peer_num = port.stack['port'].number
            peer_key = '%s:%s' % (peer_dp, peer_num)
            key_array = [this_key, peer_key]
            key_array.sort()
            key = key_array[0]
            if add_else_remove:
                self.up_ports[key] = port
            else:
                del self.up_ports[key]

        def activate_all_ports(self, packets=10):
            """Activate all stack ports through LLDP"""
            for valve in self.valves_manager.valves.values():
                valve.dp.dyn_running = True
                for port in valve.dp.ports.values():
                    port.dyn_phys_up = True
                for port in valve.dp.stack_ports:
                    self.up_stack_port(port, dp_id=valve.dp.dp_id)
                    self._update_port_map(port, True)
            self.trigger_all_ports(packets=packets)

        def trigger_all_ports(self, packets=10):
            """Do the needful to trigger any pending state changes"""
            # TODO: This triggers stack ports????
            for dp_id, valve in self.valves_manager.valves.items():
                interval = valve.dp.lldp_beacon['send_interval']
                for _ in range(0, packets):
                    for port in self.up_ports.values():
                        dp_id = port.dp_id
                        this_dp = self.valves_manager.valves[dp_id].dp
                        peer_dp = port.stack['dp']
                        peer_port = port.stack['port']
                        self.rcv_lldp(port, peer_dp, peer_port, dp_id)
                        self.rcv_lldp(peer_port, this_dp, port, peer_dp.dp_id)
                    self.last_flows_to_dp[dp_id] = []
                    now = self.mock_time(interval)
                    self.valves_manager.valve_flow_services(
                        now, 'fast_state_expire')
                    flows = self.last_flows_to_dp[dp_id]
                    self.apply_ofmsgs(flows, dp_id)

        def deactivate_stack_port(self, port, packets=10):
            """Deactivate a given stack port"""
            self._update_port_map(port, False)
            self.trigger_all_ports(packets=packets)

        def activate_stack_port(self, port, packets=10):
            """Deactivate a given stack port"""
            self._update_port_map(port, True)
            self.trigger_all_ports(packets=packets)

        @staticmethod
        def packet_outs_from_flows(flows):
            """Return flows that are packetout actions."""
            return [flow for flow in flows if isinstance(flow, valve_of.parser.OFPPacketOut)]

        @staticmethod
        def flowmods_from_flows(flows):
            """Return flows that are flowmods actions."""
            return [flow for flow in flows if isinstance(flow, valve_of.parser.OFPFlowMod)]

        def rcv_packet(self, port, vid, match, dp_id=None):
            """Apply and return flows created receiving a packet on a port/VID."""
            dp_id = dp_id or self.DP_ID
            valve = self.valves_manager.valves[dp_id]
            pkt = build_pkt(match)
            vlan_pkt = pkt
            # TODO: VLAN packet submitted to packet in always has VID
            # Fake OF switch implementation should do this by applying actions.
            if vid and vid not in match:
                vlan_match = match
                vlan_match['vid'] = vid
                vlan_pkt = build_pkt(match)
            msg = namedtuple(
                'null_msg',
                ('match', 'in_port', 'data', 'total_len', 'cookie', 'reason'))(
                    {'in_port': port}, port, vlan_pkt.data, len(vlan_pkt.data),
                    valve.dp.cookie, valve_of.ofp.OFPR_ACTION)
            self.last_flows_to_dp[self.DP_ID] = []
            now = self.mock_time(0)
            packet_in_func = partial(self.valves_manager.valve_packet_in, now, valve, msg)
            if dp_id == self.DP_ID:
                self.prom_inc(packet_in_func, 'of_packet_ins_total')
            else:
                packet_in_func()
            rcv_packet_ofmsgs = self.last_flows_to_dp[self.DP_ID]
            self.last_flows_to_dp[self.DP_ID] = []
            self.apply_ofmsgs(rcv_packet_ofmsgs)
            for valve_service in (
                    'resolve_gateways', 'advertise', 'fast_advertise', 'state_expire'):
                self.valves_manager.valve_flow_services(
                    now, valve_service)
            self.valves_manager.update_metrics(now)
            return rcv_packet_ofmsgs

        def rcv_lldp(self, port, other_dp, other_port, dp_id=None):
            """Receive an LLDP packet"""
            if dp_id is None:
                dp_id = self.DP_ID
            tlvs = []
            tlvs.extend(valve_packet.faucet_lldp_tlvs(other_dp))
            tlvs.extend(valve_packet.faucet_lldp_stack_state_tlvs(other_dp, other_port))
            dp_mac = other_dp.faucet_dp_mac if other_dp.faucet_dp_mac else FAUCET_MAC
            self.rcv_packet(port.number, 0, {
                'eth_src': dp_mac,
                'eth_dst': lldp.LLDP_MAC_NEAREST_BRIDGE,
                'port_id': other_port.number,
                'chassis_id': dp_mac,
                'system_name': other_dp.name,
                'org_tlvs': tlvs}, dp_id=dp_id)

        def set_stack_port_status(self, port_no, status, dp_id=None):
            """Set stack port up recalculating topology as necessary."""
            if dp_id is None:
                dp_id = self.DP_ID
            valve = self.valves_manager.valves[dp_id]
            port = valve.dp.ports[port_no]
            port.dyn_stack_current_state = status
            valve.flood_manager.update_stack_topo(True, valve.dp, port)
            for valve_vlan in valve.dp.vlans.values():
                self.apply_ofmsgs(valve.flood_manager.add_vlan(valve_vlan))

        def set_stack_port_up(self, port_no, dp_id=None):
            """Set stack port up recalculating topology as necessary."""
            self.set_stack_port_status(port_no, 3, dp_id)

        def set_stack_port_down(self, port_no, dp_id=None):
            """Set stack port up recalculating topology as necessary."""
            self.set_stack_port_status(port_no, 2, dp_id)

        # TODO: Past this point is verification stuff...

        def learn_hosts(self):
            """Learn some hosts."""
            # TODO: verify learn caching.
            for _ in range(2):
                self.rcv_packet(1, 0x100, {
                    'eth_src': self.P1_V100_MAC,
                    'eth_dst': self.UNKNOWN_MAC,
                    'ipv4_src': '10.0.0.1',
                    'ipv4_dst': '10.0.0.4'})
                # TODO: verify host learning banned
                self.rcv_packet(1, 0x100, {
                    'eth_src': self.UNKNOWN_MAC,
                    'eth_dst': self.P1_V100_MAC,
                    'ipv4_src': '10.0.0.4',
                    'ipv4_dst': '10.0.0.1'})
                self.rcv_packet(3, 0x100, {
                    'eth_src': self.P3_V100_MAC,
                    'eth_dst': self.P2_V100_MAC,
                    'ipv4_src': '10.0.0.3',
                    'ipv4_dst': '10.0.0.2',
                    'vid': 0x100})
                self.rcv_packet(2, 0x200, {
                    'eth_src': self.P2_V200_MAC,
                    'eth_dst': self.P3_V200_MAC,
                    'ipv4_src': '10.0.0.2',
                    'ipv4_dst': '10.0.0.3',
                    'vid': 0x200})
                self.rcv_packet(3, 0x200, {
                    'eth_src': self.P3_V200_MAC,
                    'eth_dst': self.P2_V200_MAC,
                    'ipv4_src': '10.0.0.3',
                    'ipv4_dst': '10.0.0.2',
                    'vid': 0x200})

        def verify_expiry(self):
            """Verify FIB resolution attempts expire."""
            for _ in range(self.valve.dp.max_host_fib_retry_count + 1):
                now = self.mock_time(self.valve.dp.timeout * 2)
                self.valve.state_expire(now, None)
                self.valve.resolve_gateways(now, None)
            # TODO: verify state expired

        def verify_flooding(self, matches):
            """Verify flooding for a packet, depending on the DP implementation."""

            def _verify_flood_to_port(match, port, valve_vlan, port_number=None):
                if valve_vlan.port_is_tagged(port):
                    vid = valve_vlan.vid | ofp.OFPVID_PRESENT
                else:
                    vid = 0
                if port_number is None:
                    port_number = port.number
                return self.table.is_output(match, port=port_number, vid=vid)

            for match in matches:
                in_port_number = match['in_port']
                in_port = self.valve.dp.ports[in_port_number]

                if ('vlan_vid' in match and
                        match['vlan_vid'] & ofp.OFPVID_PRESENT != 0):
                    valve_vlan = self.valve.dp.vlans[match['vlan_vid'] & ~ofp.OFPVID_PRESENT]
                else:
                    valve_vlan = in_port.native_vlan

                all_ports = {
                    port for port in self.valve.dp.ports.values() if port.running()}
                remaining_ports = all_ports - {
                    port for port in valve_vlan.get_ports() if port.running}

                hairpin_output = _verify_flood_to_port(
                    match, in_port, valve_vlan, ofp.OFPP_IN_PORT)
                self.assertEqual(
                    in_port.hairpin, hairpin_output,
                    msg='hairpin flooding incorrect (expected %s got %s)' % (
                        in_port.hairpin, hairpin_output))

                for port in valve_vlan.get_ports():
                    output = _verify_flood_to_port(match, port, valve_vlan)
                    if self.valve.floods_to_root():
                        # Packet should only be flooded to root.
                        self.assertEqual(False, output, 'unexpected non-root flood')
                    else:
                        # Packet must be flooded to all ports on the VLAN.
                        if port == in_port:
                            self.assertEqual(port.hairpin, output,
                                             'unexpected hairpin flood %s %u' % (
                                                 match, port.number))
                        else:
                            self.assertTrue(
                                output,
                                msg=('%s with unknown eth_dst not flooded'
                                     ' on VLAN %u to port %u\n%s' % (
                                         match, valve_vlan.vid, port.number, self.table)))

                # Packet must not be flooded to ports not on the VLAN.
                for port in remaining_ports:
                    if port.stack:
                        self.assertTrue(
                            self.table.is_output(match, port=port.number),
                            msg=('Unknown eth_dst not flooded to stack port %s' % port))
                    elif not port.mirror:
                        self.assertFalse(
                            self.table.is_output(match, port=port.number),
                            msg=('Unknown eth_dst flooded to non-VLAN/stack/mirror %s' % port))

        def validate_flood(self, in_port, vlan_vid, out_port, expected, msg):
            bcast_match = {
                'in_port': in_port,
                'eth_dst': mac.BROADCAST_STR,
                'vlan_vid': vlan_vid,
                'eth_type': 0x800,
            }
            if expected:
                self.assertTrue(self.table.is_output(bcast_match, port=out_port), msg=msg)
            else:
                self.assertFalse(self.table.is_output(bcast_match, port=out_port), msg=msg)

        def pkt_match(self, src, dst):
            """Make a unicast packet match dict for the given src & dst"""
            return {
                'eth_src': '00:00:00:01:00:%02x' % src,
                'eth_dst': '00:00:00:01:00:%02x' % dst,
                'ipv4_src': '10.0.0.%d' % src,
                'ipv4_dst': '10.0.0.%d' % dst,
                'vid': self.V100
            }

        def _config_edge_learn_stack_root(self, new_value):
            config = yaml.load(self.CONFIG, Loader=yaml.SafeLoader)
            config['vlans']['v100']['edge_learn_stack_root'] = new_value
            return yaml.dump(config)