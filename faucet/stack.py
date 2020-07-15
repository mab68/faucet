
"""Configuration for a stack."""

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
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from collections import defaultdict, Counter
import networkx

from faucet.conf import Conf, test_config_condition


# This node is the root of the stack
NODE_ROOT = 0
# This node is at the edge of the stack
NODE_EDGE = 1
# This node is neither at the edge or the root, transit from edge to root
NODE_TRANSIT = 2
# Node currently hasn't had it's position calculated yet
NODE_PENDING_CALC = 3
PLACEMENT_DISPLAY_DICT = {
    NODE_ROOT: 'ROOT',
    NODE_EDGE: 'EDGE',
    NODE_TRANSIT: 'TRANSIT',
    NODE_PENDING_CALC: 'PENDING_CALCULATION',
}


# Current acting root for the whole stack, lowest configured priority
ROOT_CHOSEN = 0
# Configured priority value, this stack is a root candidate
ROOT_CANDIDATE = 1
# No configured priority value, so cannot be root
ROOT_NOTCONF = 2
ROOT_DISPLAY_DICT = {
    ROOT_CHOSEN: 'CHOSEN_ROOT',
    ROOT_CANDIDATE: 'CANDIDATE_ROOT',
    ROOT_NOTCONF: 'NOT_CONFIGURED',
}


class Stack(Conf):
    """Stores state related to DP stack information, this includes the current elected root as that
is technically a fixed allocation for this DP Stack instance."""

    defaults = {
        'priority': None,
        # Sets the root priority value of the current DP with stacking
        'route_learning': False,
        # Use the stack route algorithms, will be forced true if routing is enabled
        'root_down_time_multiple': 3,
        # Multiple of STACK_ROOT_STATE_UPDATE_TIME to be considered a healthy stack root
    }

    defaults_types = {
        'priority': int,
        'route_learning': bool,
        'root_down_time_multiple': int,
    }

    def __init__(self, _id, dp_id, name, canonical_port_order, conf):
        """
        Constructs a new stack object

        Args:
            _id (str): Name of the configuration key
            dp_id (int): DP ID of the DP that holds this stack instance
            name (str): Name of the DP that holds this stack instance
            canonical_port_order (func): Function to order ports in a standardized way
            conf (dict): Stack configuration
        """
        self.name = name

        # Function to order ports in a standardized way
        self.canonical_port_order = canonical_port_order

        # Stack configuration options
        self.priority = None
        self.route_learning = None
        self.root_down_time_multiple = None

        # Ports that have stacking configured
        self.ports = []

        # Stack graph containing all the DPs & ports in the stacking topology
        self.graph = None

        # Additional stacking information
        self.root_name = None
        self.roots_names = None
        self.root_flood_reflection = None

        super(Stack, self).__init__(_id, dp_id, conf)

    def resolve_topology(self, dps, meta_dp_state):
        """
        Resolve & verify correct inter-DP stacking config

        Args:
            dps (list): List of configured DPs
            meta_dp_state (MetaDPState): Provided if reloading when choosing a new root DP
        """
        stack_dps = [dp for dp in dps if dp.stack is not None]
        stack_priority_dps = [dp for dp in stack_dps if dp.stack.priority]
        stack_port_dps = [dp for dp in dps if dp.stack_ports()]

        if not stack_priority_dps:
            test_config_condition(stack_dps, 'stacking enabled but no root DP')
            return

        if not self.ports:
            return

        for dp in stack_priority_dps:  # pylint: disable=invalid-name
            test_config_condition(not isinstance(dp.stack.priority, int), (
                'stack priority must be type %s not %s' % (
                    int, type(dp.stack.priority))))
            test_config_condition(dp.stack.priority <= 0, (
                'stack priority must be > 0'))
        stack_priority_dps = sorted(stack_priority_dps, key=lambda x: x.stack.priority)

        self.roots_names = tuple([dp.name for dp in stack_priority_dps])
        self.root_name = self.roots_names[0]
        if meta_dp_state:
            # If meta_dp_state exists, then we are reloading a new instance of the stack
            #   for a new 'dynamically' chosen root
            if meta_dp_state.stack_root_name in self.roots_names:
                self.root_name = meta_dp_state.stack_root_name

        self.route_learning = False
        for dp in stack_port_dps:  # pylint: disable=invalid-name
            for vlan in dp.vlans.values():
                if vlan.faucet_vips:
                    self.route_learning = True

        edge_count = Counter()
        graph = networkx.MultiGraph()
        for dp in stack_port_dps:  # pylint: disable=invalid-name
            graph.add_node(dp.name)
            for port in dp.stack_ports():
                edge_name = self.add_link(graph, dp, port)
                edge_count[edge_name] += 1
        for edge_name, count in edge_count.items():
            test_config_condition(count != 2, '%s defined only in one direction' % edge_name)
        if graph.size() and self.name in graph:
            self.graph = graph
            for dp in graph.nodes():  # pylint: disable=invalid-name
                path_to_root_len = len(self.shortest_path(self.root_name, src_dp=dp))
                test_config_condition(
                    path_to_root_len == 0, '%s not connected to stack' % dp)
            if self.longest_path_to_root_len() > 2:
                self.root_flood_reflection = True
        self.recalculate_ports()

    @staticmethod
    def modify_topology(graph, dp, port, add=True):  # pylint: disable=invalid-name
        """Add/remove an edge to the stack graph which originates from this dp and port."""

        def canonical_edge(dp, port):  # pylint: disable=invalid-name
            peer_dp = port.stack['dp']
            peer_port = port.stack['port']
            sort_edge_a = (
                dp.name, port.name, dp, port)
            sort_edge_z = (
                peer_dp.name, peer_port.name, peer_dp, peer_port)
            sorted_edge = sorted((sort_edge_a, sort_edge_z))
            edge_a, edge_b = sorted_edge[0][2:], sorted_edge[1][2:]
            return edge_a, edge_b

        def make_edge_name(edge_a, edge_z):
            edge_a_dp, edge_a_port = edge_a
            edge_z_dp, edge_z_port = edge_z
            return '%s:%s-%s:%s' % (
                edge_a_dp.name, edge_a_port.name,
                edge_z_dp.name, edge_z_port.name)

        def make_edge_attr(edge_a, edge_z):
            edge_a_dp, edge_a_port = edge_a
            edge_z_dp, edge_z_port = edge_z
            return {
                'dp_a': edge_a_dp, 'port_a': edge_a_port,
                'dp_z': edge_z_dp, 'port_z': edge_z_port}

        edge = canonical_edge(dp, port)
        edge_a, edge_z = edge
        edge_name = make_edge_name(edge_a, edge_z)
        edge_attr = make_edge_attr(edge_a, edge_z)
        edge_a_dp, _ = edge_a
        edge_z_dp, _ = edge_z
        if add:
            graph.add_edge(
                edge_a_dp.name, edge_z_dp.name,
                key=edge_name, port_map=edge_attr)
        elif (edge_a_dp.name, edge_z_dp.name, edge_name) in graph.edges:
            graph.remove_edge(edge_a_dp.name, edge_z_dp.name, edge_name)

        return edge_name

    def modify_link(dp, port, add):
        """Update the stack topology according to the event"""
        return cls.modify_topology(self.graph, dp, port, add)

    def hash(self):
        """Return hash of a topology graph"""
        return hash(tuple(sorted(self.graph.degree())))

    def get_node_link_data(self):
        """Return network stacking graph as a node link representation"""
        return networkx.json_graph.node_link_data(self.graph)

    def add_port(self, port):
        """Add a port to this stack"""
        self.ports.append(port)

    def any_port_up(self):
        """Return true if any stack port is UP"""
        for port in self.ports:
            if port.is_stack_up():
                return True
        return False

    def canonical_up_ports(self, ports=None):
        """Obtains list of UP stack ports in canonical order"""
        if ports is None:
            ports = self.ports
        return self.canonical_port_order([port for port in ports if port.is_stack_up()])

    def shortest_path(self, dest_dp, src_dp=None):
        """Return shortest path to a DP, as a list of DPs."""
        if src_dp is None:
            src_dp = self.name
        if self.graph:
            try:
                return sorted(networkx.all_shortest_paths(self.graph, src_dp, dest_dp))[0]
            except (networkx.exception.NetworkXNoPath, networkx.exception.NodeNotFound):
                pass
        return []

    def shortest_path_to_root(self, src_dp=None):
        """Return shortest path to root DP, as list of DPs."""
        return self.shortest_path(self.root_name, src_dp=src_dp)

    def is_root(self):
        """Return True if this DP is the root of the stack."""
        return self.name == self.root_name

    def is_root_candidate(self):
        """Return True if this DP could be a root of the stack."""
        return self.name in self.roots_names

    def is_edge(self):
        """Return True if this DP is a stack edge."""
        return (not self.is_root() and
                self.longest_path_to_root_len() == len(self.shortest_path_to_root()))

    def shortest_path_port(self, dest_dp):
        """Return first port on our DP, that is the shortest path towards dest DP."""
        shortest_path = self.shortest_path(dest_dp)
        if len(shortest_path) > 1:
            peer_dp = shortest_path[1]
            peer_dp_ports = self.peer_up_ports(peer_dp)
            if peer_dp_ports:
                return peer_dp_ports[0]
        return None

    def peer_up_ports(self, peer_dp):
        """Return list of stack ports that are up towards a peer."""
        return self.canonical_port_order([
            port for port in self.ports if port.running() and (
                port.stack['dp'].name == peer_dp)])

    def longest_path_to_root_len(self):
        """Return length of the longest path to root in the stack."""
        if not self.graph or not self.root_name:
            return None
        len_paths_to_root = [
            len(self.shortest_path(self.root_name, src_dp=dp))
            for dp in self.graph.nodes()]
        if len_paths_to_root:
            return max(len_paths_to_root)
        return None

    def is_in_path(self, src_dp, dst_dp):
        """Return True if the current DP is in the path from src_dp to dst_dp

        Args:
            src_dp (str): DP name
            dst_dp (str): DP name
        Returns:
            bool: True if self is in the path from the src_dp to the dst_dp.
        """
        path = self.shortest_path(dst_dp, src_dp=src_dp)
        return self.name in path

    def peer_symmetric_up_ports(self, peer_dp):
        """Return list of stack ports that are up towards us from a peer"""
        # Sort adjacent ports by canonical port order
        return self.canonical_port_order([
            port.stack['port'] for port in self.ports if port.running() and (
                port.stack['dp'].name == peer_dp)])

    def shortest_symmetric_path_port(self, peer_dp):
        """Return port on our DP that is the first port of the adjacent DP towards us"""
        shortest_path = self.shortest_path(self.name, src_dp=peer_dp)
        if len(shortest_path) == 2:
            adjacent_up_ports = self.peer_symmetric_up_ports(peer_dp)
            if adjacent_up_ports:
                return adjacent_up_ports[0].stack['port']
        return None
