"""Manage flooding/learning on stacked datapaths."""

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

from collections import defaultdict
from faucet import valve_of
from faucet.valve_switch_standalone import ValveSwitchManager
from faucet.vlan import NullVLAN


class ValveSwitchStackManagerBase(ValveSwitchManager):
    """Base class for dataplane based flooding/learning on stacked dataplanes."""

    # By default, no reflection used for flooding algorithms.
    _USES_REFLECTION = False

    def __init__(self, stack, tunnel_acls, acl_manager, **kwargs):
        super(ValveSwitchStackManagerBase, self).__init__(**kwargs)

        self.tunnel_acls = tunnel_acls
        self.acl_manager = acl_manager
        self.stack_manager = stack_manager

        self._set_ext_port_flag = ()
        self._set_nonext_port_flag = ()
        self.external_root_only = False
        if self.has_externals:
            self.logger.info('external ports present, using loop protection')
            self._set_ext_port_flag = (self.flood_table.set_external_forwarding_requested(),)
            self._set_nonext_port_flag = (self.flood_table.set_no_external_forwarding_requested(),)
            if not self.is_stack_root() and self.is_stack_root_candidate():
                self.logger.info('external flooding on root only')
                self.external_root_only = True

    @staticmethod
    def _non_stack_learned(other_valves, pkt_meta):
        """
        Obtain DP that has learnt the host that sent the packet

        Args:
            other_valves (list): Other valves
            pkt_meta (PacketMeta): Packet meta sent by the host
        Returns:
            DP: DP that has learnt the host
        """
        # TODO: Not here???
        other_local_dp_entries = []
        other_external_dp_entries = []
        vlan_vid = pkt_meta.vlan.vid
        for other_valve in other_valves:
            other_dp_vlan = other_valve.dp.vlans.get(vlan_vid, None)
            if other_dp_vlan is not None:
                entry = other_dp_vlan.cached_host(pkt_meta.eth_src)
                if not entry:
                    continue
                if not entry.port.non_stack_forwarding():
                    continue
                if entry.port.loop_protect_external:
                    other_external_dp_entries.append(other_valve.dp)
                else:
                    other_local_dp_entries.append(other_valve.dp)
        # Another DP has learned locally, has priority.
        if other_local_dp_entries:
            return other_local_dp_entries[0]
        # No other DP has learned locally, but at least one has learned externally.
        if other_external_dp_entries:
            entry = pkt_meta.vlan.cached_host(pkt_meta.eth_src)
            # This DP has not learned the host either, use other's external.
            if entry is None:
                return other_external_dp_entries[0]
        return None

    def _external_forwarding_requested(self, port):
        external_forwarding_requested = None
        if self.has_externals:
            if port.tagged_vlans and port.loop_protect_external:
                external_forwarding_requested = False
            elif not port.stack:
                external_forwarding_requested = True
        return external_forwarding_requested

    def acl_update_tunnel(self, acl):
        """Return ofmsgs for a ACL with a tunnel rule"""
        ofmsgs = []
        source_vids = defaultdict(list)
        for _id, info in acl.tunnel_info.items():
            dst_dp, dst_port = info['dst_dp'], info['dst_port']
            # Update the tunnel rules for each tunnel action specified
            updated_sources = []
            for i, source in enumerate(acl.tunnel_sources):
                # Update each tunnel rule for each tunnel source
                src_dp = source['dp']
                shortest_path = self.shortest_path(dst_dp, src_dp=src_dp)
                if self.dp_name not in shortest_path:
                    continue
                out_port = None
                # We are in the path, so we need to update
                if self.dp_name == dst_dp:
                    out_port = dst_port
                if not out_port:
                    out_port = self.shortest_path_port(dst_dp).number
                updated = acl.update_source_tunnel_rules(
                    self.dp_name, i, _id, out_port)
                if updated:
                    if self.dp_name == src_dp:
                        source_vids[i].append(_id)
                    else:
                        updated_sources.append(i)
            for source_id in updated_sources:
                ofmsgs.extend(self.acl_manager.build_tunnel_rules_ofmsgs(
                    source_id, _id, acl))
        for source_id, vids in source_vids.items():
            for vid in vids:
                ofmsgs.extend(self.acl_manager.build_tunnel_acl_rule_ofmsgs(
                    source_id, vid, acl))
        return ofmsgs

    def add_tunnel_acls(self):
        ofmsgs = []
        if self.tunnel_acls:
            for acl in self.tunnel_acls:
                ofmsgs.extend(self.acl_update_tunnel(acl))
        return ofmsgs

    def learn_host_intervlan_routing_flows(self, port, vlan, eth_src, eth_dst):
        """Returns flows for the eth_src_table that enable packets that have been
           routed to be accepted from an adjacent DP and then switched to the destination.
           Eth_src_table flow rule to match on port, eth_src, eth_dst and vlan

        Args:
            port (Port): Port to match on.
            vlan (VLAN): VLAN to match on
            eth_src: source MAC address (should be the router MAC)
            eth_dst: destination MAC address
        """
        ofmsgs = []
        (src_rule_idle_timeout, src_rule_hard_timeout, _) = self._learn_host_timeouts(port, eth_src)
        src_match = self.eth_src_table.match(vlan=vlan, eth_src=eth_src, eth_dst=eth_dst)
        src_priority = self.host_priority - 1
        inst = [self.eth_src_table.goto(self.output_table)]
        ofmsgs.extend([self.eth_src_table.flowmod(
            match=src_match,
            priority=src_priority,
            inst=inst,
            hard_timeout=src_rule_hard_timeout,
            idle_timeout=src_rule_idle_timeout)])
        return ofmsgs

    def _build_flood_acts_for_port(self, vlan, exclude_unicast, port,  # pylint: disable=too-many-arguments
                                   exclude_all_external=False,
                                   exclude_restricted_bcast_arpnd=False):
        if self.external_root_only:
            exclude_all_external = True
        return super(ValveSwitchStackManagerBase, self)._build_flood_acts_for_port(
            vlan, exclude_unicast, port,
            exclude_all_external=exclude_all_external,
            exclude_restricted_bcast_arpnd=exclude_restricted_bcast_arpnd)

    def _flood_actions(self, in_port, external_ports,
                       away_flood_actions, toward_flood_actions, local_flood_actions):
        raise NotImplementedError




    def _build_flood_rule_actions(self, vlan, exclude_unicast, in_port,
                                  exclude_all_external=False, exclude_restricted_bcast_arpnd=False):
        """
        Args:
            vlan (VLAN):
            exclude_unicast (bool):
            in_port (Port):
            exclude_all_external (bool):
            exclude_restricted_bcast_arpnd (bool):
        Returns:
            list: flood actions
        """
        exclude_ports = self._inactive_away_stack_ports()
        external_ports = vlan.loop_protect_external_ports()

        # TODO: stack.ports
        # TODO: stack.towards_root_ports()??
        # TODO: stack.away_from_root_ports()
        if in_port and in_port in self.stack_ports:
            in_port_peer_dp = in_port.stack['dp']
            exclude_ports = exclude_ports + [
                port for port in self.stack_ports
                if port.stack['dp'] == in_port_peer_dp]
        local_flood_actions = tuple(self._build_flood_local_rule_actions(
            vlan, exclude_unicast, in_port, exclude_all_external, exclude_restricted_bcast_arpnd))
        away_flood_actions = tuple(valve_of.flood_tagged_port_outputs(
            self.away_from_root_stack_ports, in_port, exclude_ports=exclude_ports))
        toward_flood_actions = tuple(valve_of.flood_tagged_port_outputs(
            self.towards_root_stack_ports, in_port))
        flood_acts = self._flood_actions(
            in_port, external_ports, away_flood_actions,
            toward_flood_actions, local_flood_actions)
        return flood_acts

    def _build_mask_flood_rules(self, vlan, eth_type, eth_dst, eth_dst_mask,  # pylint: disable=too-many-arguments
                                exclude_unicast, exclude_restricted_bcast_arpnd,
                                command, cold_start):
        """
        Args:
            vlan (VLAN):
            eth_type:
            eth_dst:
            eth_dst_mask:
            exclude_unicast:
            exclude_restricted_bcast_arpnd:
            command:
            cold_start:
        Returns:
            list: ofmsgs
        """
        # TODO: REFACTOR...
        # Stack ports aren't in VLANs, so need special rules to cause flooding from them.
        ofmsgs = super(ValveSwitchStackManagerBase, self)._build_mask_flood_rules(
            vlan, eth_type, eth_dst, eth_dst_mask,
            exclude_unicast, exclude_restricted_bcast_arpnd,
            command, cold_start)

        # TODO: stack_manager
        away_up_ports_by_dp = defaultdict(list)
        for port in self._canonical_stack_up_ports(self.away_from_root_stack_ports):
            away_up_ports_by_dp[port.stack['dp']].append(port)
        towards_up_port = None
        towards_up_ports = self._canonical_stack_up_ports(self.towards_root_stack_ports)
        if towards_up_ports:
            towards_up_port = towards_up_ports[0]


        replace_priority_offset = (
            self.classification_offset - (
                self.pipeline.filter_priority - self.pipeline.select_priority))

        # TODO: stack_manager/stack
        for port in self.stack_ports:
            remote_dp = port.stack['dp']
            away_up_port = None
            away_up_ports = away_up_ports_by_dp.get(remote_dp, None)
            if away_up_ports:
                # Pick the lowest port number on the remote DP.
                remote_away_ports = self.canonical_port_order(
                    [away_port.stack['port'] for away_port in away_up_ports])
                away_up_port = remote_away_ports[0].stack['port']
            away_port = port in self.away_from_root_stack_ports
            towards_port = not away_port
            flood_acts = []

            match = {'in_port': port.number, 'vlan': vlan}
            if eth_dst is not None:
                match.update({'eth_dst': eth_dst, 'eth_dst_mask': eth_dst_mask})
                # Prune broadcast flooding where multiply connected to same DP
                if towards_port:
                    prune = port != towards_up_port
                else:
                    prune = port != away_up_port
            else:
                # Do not prune unicast, may be reply from directly connected DP.
                prune = False

            priority_offset = replace_priority_offset
            if eth_dst is None:
                priority_offset -= 1
            if prune:
                # Allow the prune rule to be replaced with OF strict matching if
                # this port is unpruned later.
                ofmsgs.extend(self.pipeline.filter_packets(
                    match, priority_offset=priority_offset))
            else:
                ofmsgs.extend(self.pipeline.remove_filter(
                    match, priority_offset=priority_offset))
                # Control learning from multicast/broadcast on non-root DPs.
                if not self.is_stack_root() and eth_dst is not None and self._USES_REFLECTION:
                    # If ths is an edge DP, we don't have to learn from
                    # hosts that only broadcast.  If we're an intermediate
                    # DP, only learn from broadcasts further away from
                    # the root (and ignore the reflected broadcast for
                    # learning purposes).
                    if self.is_stack_edge() or towards_port:
                        ofmsgs.extend(self.pipeline.select_packets(
                            self.flood_table, match,
                            priority_offset=self.classification_offset))

            if self.has_externals:
                # If external flag is set, flood to external ports, otherwise exclude them.
                for ext_port_flag, exclude_all_external in (
                        (valve_of.PCP_NONEXT_PORT_FLAG, True),
                        (valve_of.PCP_EXT_PORT_FLAG, False)):
                    if not prune:
                        flood_acts, _, _ = self._build_flood_acts_for_port(
                            vlan, exclude_unicast, port,
                            exclude_all_external=exclude_all_external,
                            exclude_restricted_bcast_arpnd=exclude_restricted_bcast_arpnd)
                    port_flood_ofmsg = self._build_flood_rule_for_port(
                        vlan, eth_type, eth_dst, eth_dst_mask, command, port, flood_acts,
                        add_match={valve_of.EXTERNAL_FORWARDING_FIELD: ext_port_flag})
                    ofmsgs.append(port_flood_ofmsg)
            else:
                if not prune:
                    flood_acts, _, _ = self._build_flood_acts_for_port(
                        vlan, exclude_unicast, port,
                        exclude_restricted_bcast_arpnd=exclude_restricted_bcast_arpnd)
                port_flood_ofmsg = self._build_flood_rule_for_port(
                    vlan, eth_type, eth_dst, eth_dst_mask, command, port, flood_acts)
                ofmsgs.append(port_flood_ofmsg)

        return ofmsgs




    def edge_learn_port(self, other_valves, pkt_meta):
        """
        Find a port towards the edge DP where the packet originated from

        Args:
            other_valves (list): All Valves other than this one.
            pkt_meta (PacketMeta): PacketMeta instance for packet received.
        Returns:
            port to learn host on, or None.
        """
        # Got a packet from another DP.
        if pkt_meta.port.stack:
            # Received packet from
            # self.stack_manager.edge_learn_port(???)
            edge_dp = self._edge_dp_for_host(other_valves, pkt_meta)
            if edge_dp:
                return self.stack_manager.edge_learn_port_towards(pkt_meta, edge_dp)
            # Assuming no DP has learned this host.
            return None

        # Got a packet locally.
        # If learning on an external port, check another DP hasn't
        # already learned on a local/non-external port.
        if pkt_meta.port.loop_protect_external:
            edge_dp = self._non_stack_learned(other_valves, pkt_meta)
            if edge_dp:
                return self.stack_manager.edge_learn_port_towards(pkt_meta, edge_dp)
        # Locally learn.
        return super(ValveSwitchStackManagerBase, self).edge_learn_port(
            other_valves, pkt_meta)

    def _edge_dp_for_host(self, other_valves, pkt_meta):
        """Simple distributed unicast learning.

        Args:
            other_valves (list): All Valves other than this one.
            pkt_meta (PacketMeta): PacketMeta instance for packet received.
        Returns:
            Valve instance or None (of edge datapath where packet received)
        """
        raise NotImplementedError

    def add_port(self, port):
        ofmsgs = super(ValveSwitchStackManagerBase, self).add_port(port)
        # If this is a stacking port, accept all VLANs (came from another FAUCET)
        if port.stack:
            # Actual stack traffic will have VLAN tags.
            ofmsgs.append(self.vlan_table.flowdrop(
                match=self.vlan_table.match(
                    in_port=port.number,
                    vlan=NullVLAN()),
                priority=self.low_priority+1))
            ofmsgs.append(self.vlan_table.flowmod(
                match=self.vlan_table.match(in_port=port.number),
                priority=self.low_priority,
                inst=self.pipeline.accept_to_classification()))
        return ofmsgs

    def del_port(self, port):
        ofmsgs = super(ValveSwitchStackManagerBase, self).del_port(port)
        if port.stack:
            for vlan in self.vlans.values():
                vlan.clear_cache_hosts_on_port(port)
        return ofmsgs

    def get_lacp_dpid_nomination(self, lacp_id, valve, other_valves):
        """Chooses the DP for a given LAG.

        The DP will be nominated by the following conditions in order:
            1) Number of LAG ports
            2) Root DP
            3) Lowest DPID

        Args:
            lacp_id: The LACP LAG ID
            other_valves (list): list of other valves
        Returns:
            nominated_dpid, reason
        """
        if not other_valves:
            return None, ''
        stacked_other_valves = valve._stacked_valves(other_valves)
        all_stacked_valves = {valve}.union(stacked_other_valves)
        ports = {}
        root_dpid = None
        for valve in all_stacked_valves:
            all_lags = valve.dp.lags_up()
            if lacp_id in all_lags:
                ports[valve.dp.dp_id] = len(all_lags[lacp_id])
            if valve.dp.stack.is_root():
                root_dpid = valve.dp.dp_id
        # Order by number of ports
        port_order = sorted(ports, key=ports.get, reverse=True)
        if not port_order:
            return None, ''
        most_ports_dpid = port_order[0]
        most_ports_dpids = [dpid for dpid, num in ports.items() if num == ports[most_ports_dpid]]
        if len(most_ports_dpids) > 1:
            # There are several dpids that have the same number of lags
            if root_dpid in most_ports_dpids:
                # root_dpid is the chosen DPID
                return root_dpid, 'root dp'
            # Order by lowest DPID
            return sorted(most_ports_dpids), 'lowest dpid'
        # Most_ports_dpid is the chosen DPID
        return most_ports_dpid, 'most LAG ports'


class ValveSwitchStackManagerNoReflection(ValveSwitchStackManagerBase):
    """Stacks of size 2 - all switches directly connected to root.

    Root switch simply floods to all other switches.

    Non-root switches simply flood to the root.
    """

    def _flood_actions(self, in_port, external_ports,
                       away_flood_actions, toward_flood_actions, local_flood_actions):
        if not in_port or in_port in self.stack_ports:
            flood_prefix = ()
        else:
            if external_ports:
                flood_prefix = self._set_nonext_port_flag
            else:
                flood_prefix = self._set_ext_port_flag

        flood_actions = (
            flood_prefix + toward_flood_actions + away_flood_actions + local_flood_actions)

        return flood_actions

    def _edge_dp_for_host(self, other_valves, pkt_meta):
        """Size 2 means root shortest path is always directly connected."""
        peer_dp = pkt_meta.port.stack['dp']
        if peer_dp.dyn_running:
            return self._non_stack_learned(other_valves, pkt_meta)
        # Fall back to assuming peer knows if we are not the peer's controller.
        return peer_dp


class ValveSwitchStackManagerReflection(ValveSwitchStackManagerBase):
    """Stacks size > 2 reflect floods off of root (selective flooding).

       .. code-block:: none

                                Hosts
                                 ||||
                                 ||||
                   +----+       +----+       +----+
                ---+1   |       |1234|       |   1+---
          Hosts ---+2   |       |    |       |   2+--- Hosts
                ---+3   |       |    |       |   3+---
                ---+4  5+-------+5  6+-------+5  4+---
                   +----+       +----+       +----+

                   Root DP

       Non-root switches flood only to the root. The root switch
       reflects incoming floods back out. Non-root switches flood
       packets from the root locally and to switches further away
       from the root. Flooding is entirely implemented in the dataplane.

       A host connected to a non-root switch can receive a copy of its
       own flooded packet (because the non-root switch does not know
       it has seen the packet already).

       A host connected to the root switch does not have this problem
       (because flooding is always away from the root). Therefore,
       connections to other non-FAUCET stacking networks should only
       be made to the root.

       On the root switch (left), flood destinations are:

       1: 2 3 4 5(s)
       2: 1 3 4 5(s)
       3: 1 2 4 5(s)
       4: 1 2 3 5(s)
       5: 1 2 3 4 5(s, note reflection)

       On the middle switch:

       1: 5(s)
       2: 5(s)
       3: 5(s)
       4: 5(s)
       5: 1 2 3 4 6(s)
       6: 5(s)

       On the rightmost switch:

       1: 5(s)
       2: 5(s)
       3: 5(s)
       4: 5(s)
       5: 1 2 3 4
    """

    # Indicate to base class use of reflection required.
    _USES_REFLECTION = True

    def _learn_cache_check(self, entry, vlan, now, eth_src, port, ofmsgs,  # pylint: disable=unused-argument
                           cache_port, cache_age,
                           delete_existing, refresh_rules):
        learn_exit = False
        update_cache = True
        if cache_port is not None:
            # packet was received on same member of a LAG.
            same_lag = (port.lacp and port.lacp == cache_port.lacp)
            # stacks of size > 2 will have an unknown MAC flooded towards the root,
            # and flooded down again. If we learned the MAC on a local port and
            # heard the reflected flooded copy, discard the reflection.
            local_stack_learn = port.stack and not cache_port.stack
            guard_time = self.cache_update_guard_time
            if cache_port == port or same_lag or local_stack_learn:
                # aggressively re-learn on LAGs, and prefer recently learned
                # locally learned hosts on a stack.
                if same_lag or local_stack_learn:
                    guard_time = 2
                # port didn't change status, and recent cache update, don't do anything.
                if (cache_age < guard_time and
                        port.dyn_update_time is not None and
                        port.dyn_update_time <= entry.cache_time):
                    update_cache = False
                    learn_exit = True
                # skip delete if host didn't change ports or on same LAG.
                elif cache_port == port or same_lag:
                    delete_existing = False
                    refresh_rules = True
        return (learn_exit, ofmsgs, cache_port, update_cache, delete_existing, refresh_rules)

    def _flood_actions(self, in_port, external_ports,
                       away_flood_actions, toward_flood_actions, local_flood_actions):
        if self.is_stack_root():
            if external_ports:
                flood_prefix = self._set_nonext_port_flag
            else:
                flood_prefix = self._set_ext_port_flag
            flood_actions = (away_flood_actions + local_flood_actions)

            if in_port and in_port in self.away_from_root_stack_ports:
                # Packet from a non-root switch, flood locally and to all non-root switches
                # (reflect it).
                flood_actions = (
                    away_flood_actions + (valve_of.output_in_port(),) + local_flood_actions)

            flood_actions = flood_prefix + flood_actions
        else:
            # Default non-root strategy is flood towards root.
            if external_ports:
                flood_actions = self._set_nonext_port_flag + toward_flood_actions
            else:
                flood_actions = self._set_ext_port_flag + toward_flood_actions

            if in_port:
                # Packet from switch further away, flood it to the root.
                if in_port in self.away_from_root_stack_ports:
                    flood_actions = toward_flood_actions
                # Packet from the root.
                elif in_port in self.all_towards_root_stack_ports:
                    # If we have external ports, and packet hasn't already been flooded
                    # externally, flood it externally before passing it to further away switches,
                    # and mark it flooded.
                    if external_ports:
                        flood_actions = (
                            self._set_nonext_port_flag + away_flood_actions + local_flood_actions)
                    else:
                        flood_actions = (
                            away_flood_actions + self._set_nonext_port_flag + local_flood_actions)
                # Packet from external port, locally. Mark it already flooded externally and
                # flood to root (it came from an external switch so keep it within the stack).
                elif in_port.loop_protect_external:
                    flood_actions = self._set_nonext_port_flag + toward_flood_actions
                else:
                    flood_actions = self._set_ext_port_flag + toward_flood_actions

        return flood_actions

    def _edge_dp_for_host(self, other_valves, pkt_meta):
        """For stacks size > 2."""
        # TODO: currently requires controller to manage all switches
        # in the stack to keep each DP's graph consistent.
        # TODO: simplest possible unicast learning.
        # We find just one port that is the shortest unicast path to
        # the destination. We could use other factors (eg we could
        # load balance over multiple ports based on destination MAC).
        # Find port that forwards closer to destination DP that
        # has already learned this host (if any).
        peer_dp = pkt_meta.port.stack['dp']
        if peer_dp.dyn_running:
            return self._non_stack_learned(other_valves, pkt_meta)
        # Fall back to peer knows if edge or root if we are not the peer's controller.
        if peer_dp.stack.is_edge() or peer_dp.stack.is_root():
            return peer_dp
        # No DP has learned this host, yet. Take no action to allow remote learning to occur.
        return None
