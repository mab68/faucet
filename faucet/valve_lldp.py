"""Manage LLDP."""

# Copyright (C) 2013 Nippon Telegraph and Telephone Corporation.
# Copyright (C) 2015 Brad Cowie, Christopher Lorier and Joe Stringer.
# Copyright (C) 2015 Research and Education Advanced Network New Zealand Ltd.
# Copyright (C) 2015--2019 The Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from faucet import valve_of
from faucet import valve_packet
from faucet.valve_manager_base import ValveManagerBase


class ValveLLDPManager(ValveManagerBase):
    """Manage LLDP."""

    def __init__(self, vlan_table, highest_priority, logger):
        self.vlan_table = vlan_table
        self.highest_priority = highest_priority
        self.logger = logger

    def add_port(self, port):
        ofmsgs = []
        if port.receive_lldp:
            ofmsgs.append(self.vlan_table.flowcontroller(
                match=self.vlan_table.match(
                    in_port=port.number,
                    eth_dst=valve_packet.LLDP_MAC_NEAREST_BRIDGE,
                    eth_dst_mask=valve_packet.BRIDGE_GROUP_MASK,
                    eth_type=valve_of.ether.ETH_TYPE_LLDP),
                priority=self.highest_priority,
                max_len=128))
        return ofmsgs

    def _verify_lldp(self, port, now, other_valves,
                           remote_dp_id, remote_dp_name,
                           remote_port_id, remote_port_state):
        """
        Verify correct LLDP cabling, then update port to next state

        Args:
            port (Port): Port that received the LLDP
            now (float): Current time
            other_valves (list): Other valves in the topology
            remote_dp_id (int): Received LLDP remote DP ID
            remote_dp_name (str): Received LLDP remote DP name
            remote_port_id (int): Recevied LLDP port ID
            remote_port_state (int): Received LLDP port state
        Returns:
            dict: Ofmsgs by valve
        """
        if not port.stack:
            return {}
        remote_dp = port.stack['dp']
        remote_port = port.stack['port']
        stack_correct = True
        self._inc_var('stack_probes_received')
        if (remote_dp_id != remote_dp.dp_id or
                remote_dp_name != remote_dp.name or
                remote_port_id != remote_port.number):
            self.logger.error(
                'Stack %s cabling incorrect, expected %s:%s:%u, actual %s:%s:%u' % (
                    port,
                    valve_util.dpid_log(remote_dp.dp_id),
                    remote_dp.name,
                    remote_port.number,
                    valve_util.dpid_log(remote_dp_id),
                    remote_dp_name,
                    remote_port_id))
            stack_correct = False
            self._inc_var('stack_cabling_errors')
        port.dyn_stack_probe_info = {
            'last_seen_lldp_time': now,
            'stack_correct': stack_correct,
            'remote_dp_id': remote_dp_id,
            'remote_dp_name': remote_dp_name,
            'remote_port_id': remote_port_id,
            'remote_port_state': remote_port_state
        }
        return self.update_stack_link_state([port], now, other_valves)

    def update_stack_link_state(self, ports, now, other_valves):
        """
        Update the stack link states of the set of provided stack ports

        Args:
            ports (list): List of stack ports to update the state of
            now (float): Current time
            other_valves (list): List of other valves
        Returns:
            dict: ofmsgs by valve
        """
        stack_changes = 0
        ofmsgs_by_valve = defaultdict(list)
        stacked_valves = {self}.union(self._stacked_valves(other_valves))
        for port in ports:
            before_state = port.stack_state()
            after_state, reason = port.stack_port_update(now)
            if before_state != after_state:
                self._set_port_var('port_stack_state', after_state, port)
                self.notify({'STACK_STATE': {
                    'port': port.number,
                    'state': after_state}})
                stack_changes += 1
                self.logger.info('Stack %s state %s (previous state %s): %s' % (
                    port, port.stack_state_name(after_state),
                    port.stack_state_name(before_state), reason))
                port_up = False
                if port.is_stack_up():
                    port_up = True
                elif port.is_stack_init() and port.stack['port'].is_stack_up():
                    port_up = True
                for valve in stacked_valves:
                    valve.stack_manager.update_stack_topo(port_up, self.dp, port)
        if stack_changes:
            self.logger.info('%u stack ports changed state' % stack_changes)
            notify_dps = {}
            for valve in stacked_valves:
                if not valve.dp.dyn_running:
                    continue
                ofmsgs_by_valve[valve].extend(valve.add_vlans(valve.dp.vlans.values()))
                for port in valve.dp.stack_ports():
                    ofmsgs_by_valve[valve].extend(valve.switch_manager.del_port(port))
                ofmsgs_by_valve[valve].extend(valve.switch_manager.add_tunnel_acls())
                path_port = valve.dp.stack.shortest_path_port(valve.dp.stack.root_name)
                path_port_number = path_port.number if path_port else 0.0
                self._set_var(
                    'dp_root_hop_port', path_port_number, labels=valve.dp.base_prom_labels())
                notify_dps.setdefault(valve.dp.name, {})['root_hop_port'] = path_port_number
            # Find the first valve with a valid stack and trigger notification.
            for valve in stacked_valves:
                if valve.dp.stack.graph:
                    self.notify(
                        {'STACK_TOPO_CHANGE': {
                            'stack_root': valve.dp.stack.root_name,
                            'graph': valve.dp.stack.get_node_link_data(),
                            'dps': notify_dps
                            }})
                    break
        return ofmsgs_by_valve
