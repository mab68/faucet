"""Manage higher level stack functions"""


from collections import defaultdict

from faucet.valve_manager_base import ValveManagerBase


class ValveStackManager(ValveManagerBase):
    """Implement stack manager, this handles the more higher-order stack functions.
This includes port nominations and flood directionality. This class also handles the
updating of stack port states.

ValveStackManager also changes behaviour decisions based on the stack topology and the valves'
position in the stack.
"""

    def __init__(self, logger, dp, stack, **kwargs):
        """
        Initialize variables and set up peer distances

        Args:
            stack (Stack): Stack object of the DP on the Valve being managed
        """
        # Logger for logging
        self.logger = logger
        # DP instance for stack healthyness
        self.dp = dp
        # Stack instance
        self.stack = stack

        # Ports that are the shortest distance to the root
        self.towards_root_ports = None
        # Ports on an adjacent DP that is the chosen shortest path to the root
        self.chosen_towards_ports = None
        # Single port on the adjacent shortest path DP
        self.chosen_towards_port = None

        # All ports that are not the shortest distance to the root
        self.away_ports = None
        # Ports whose peer DPs have a shorter path to root
        self.inactive_away_ports = None
        # Redundant ports for each adjacent DP
        self.pruned_away_ports = None

        self.reset_peer_distances()

    @staticmethod
    def stacked_valves(valves):
        return {valve for valve in valves if valve.dp.stack and valve.dp.stack.root_name}

    def canonical_towards_port(self):
        return self.stack.canonical_up_ports(self.chosen_towards_ports)[0]

    def reset_peer_distances(self):
        """Recalculates the towards and away ports for this node"""
        self.towards_root_ports = set()
        self.chosen_towards_ports = set()
        self.chosen_towards_port = None

        self.away_ports = set()
        self.inactive_away_ports = set()
        self.pruned_away_ports = set()

        all_peer_ports = set(self.stack.canonical_up_ports())
        if self.stack.is_root():
            self.away_ports = all_peer_ports
        else:
            port_peer_distances = {
                port: len(port.stack['dp'].stack.shortest_path_to_root()) for port in all_peer_ports}
            shortest_peer_distance = None
            for port, port_peer_distance in port_peer_distances.items():
                if shortest_peer_distance is None:
                    shortest_peer_distance = port_peer_distance
                    continue
                shortest_peer_distance = min(shortest_peer_distance, port_peer_distance)
            self.towards_root_ports = {
                port for port, port_peer_distance in port_peer_distances.items()
                if port_peer_distance == shortest_peer_distance}
            self.away_ports = all_peer_ports - self.towards_root_ports

            if self.towards_root_ports:
                # Generate a shortest path to calculate the chosen connection to root
                shortest_path = self.stack.shortest_path_to_root()
                # Choose the port that is connected to peer DP
                if shortest_path and len(shortest_path) > 1:
                    first_peer_dp = shortest_path[1]
                else:
                    first_peer_port = self.stack.canonical_port_order(
                        self.towards_root_ports)[0]
                    first_peer_dp = first_peer_port.stack['dp'].name
                # The chosen towards ports are the ports through the chosen peer DP
                self.chosen_towards_ports = {
                    port for port in self.towards_root_ports
                    if port.stack['dp'].name == first_peer_dp}

            if self.chosen_towards_ports:
                self.chosen_towards_port = self.canonical_towards_port()

            # Away ports are all the remaining (non-towards) ports
            self.away_ports = all_peer_ports - self.towards_root_ports

            if self.away_ports:
                # Get inactive away ports, ports whose peers have a better path to root
                self.inactive_away_ports = {
                    port for port in self.away_ports
                    if not self.stack.is_in_path(port.stack['dp'].name, self.stack.root_name)}
                # Get pruned away ports, redundant ports for each adjacent DP
                ports_by_dp = defaultdict(list)
                for port in self.away_ports:
                    ports_by_dp[port.stack['dp']].append(port)
                for dp, ports in ports_by_dp.items():
                    remote_away_ports = self.stack.canonical_up_ports(
                        [port.stack['port'] for port in ports])
                    self.pruned_away_ports.update([
                        port.stack['port'] for port in remote_away_ports
                        if port != remote_away_ports[0]])

        return self.chosen_towards_ports

    def update_stack_topo(self, event, dp, port):
        """
        Update the stack topo according to the event.

        Args:
            event (bool): True if the port is UP
            dp (DP): DP object
            port (Port): The port being brought UP/DOWN
        """
        self.stack.modify_link(dp, port, event)
        towards_ports = self.reset_peer_distances()
        if towards_ports:
            self.logger.info('shortest path to root is via %s' % towards_ports)
        else:
            self.logger.info('no path available to root')

    def default_port_towards(self, dp_name):
        """
        Default shortest path towards the provided destination, via direct shortest path

        Args:
            dp_name (str): Destination DP
        Returns:
           Port: port from current node that is shortest directly towards destination
        """
        return self.stack.shortest_path_port(dp_name)

    def relative_port_towards(self, dp_name):
        """
        Returns the shortest path towards provided destination, via either the root or away paths

        Args:
            dp_name (str): Destination DP
        Returns:
            Port: port from current node that is towards/away the destination DP depending on
                relative position of the current node
        """
        if not self.stack.shortest_path_to_root():
            # No known path from current node to root, use default
            return self.default_port_towards(dp_name)
        if self.stack.name == dp_name:
            # Current node is the destination node, use default
            return self.default_port_towards(dp_name)
        path_to_root = self.stack.shortest_path_to_root(dp_name)
        if path_to_root and self.stack.name in path_to_root:
            # Current node is a transit node between root & destination, direct path to destination
            away_dp = path_to_root[path_to_root.index(self.stack.name) - 1]
            away_up_ports = [
                port for port in self.stack.canonical_up_ports(self.away_ports)
                if port.stack['dp'].name == away_dp]
            return away_up_ports[0] if away_up_ports else None
        else:
            # Otherwise, head towards the root, path to destination via root
            towards_up_ports = self.stack.canonical_up_ports(self.chosen_towards_ports)
            return towards_up_ports[0] if towards_up_ports else None

    def edge_learn_port_towards(self, pkt_meta, edge_dp):
        """
        Returns the port towards the edge DP

        Args:
            pkt_meta (PacketMeta): Packet on the edge DP
            edge_dp (DP): Edge DP that received the packet
        Returns:
            Port: Port towards the edge DP via some stack chosen metric
        """
        if pkt_meta.vlan.edge_learn_stack_root:
            return self.relative_port_towards(edge_dp.name)
        return self.default_port_towards(edge_dp.name)

    def tunnel_outport(self, src_dp, dst_dp, dst_port):
        """
        Returns the output port for the current stack node for the tunnel path

        Args:
            src_dp (str): Source DP name of the tunnel
            dst_dp (str): Destination DP name of the tunnel
            dst_port (int): Destination port of the tunnel
        Returns:
            Port: Output port for the current node of the tunnel
        """
        if not self.stack.is_in_path(src_dp, dst_dp):
            # No known path from the source to destination DP, so no port to output
            return None
        out_port = self.stack.shortest_path_port(dst_dp)
        if self.stack.name == dst_dp:
            # Current stack node is the destination, so output to the tunnel destination port
            out_port = dst_port
        return out_port
