"""Manage higher level stack functions"""


from collections import defaultdict

from faucet.valve_manager_base import ValveManagerBase


class ValveStackManager(ValveManagerBase):
    """Implement stack manager, this handles the more higher-order stack functions.
This includes port nominations and flood directionality."""

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
        """Return set of valves that have stacking enabled"""
        return {valve for valve in valves if valve.dp.stack and valve.dp.stack.root_name}

    def reset_peer_distances(self):
        """Recalculates the towards and away ports for this node"""
        self.towards_root_ports = set()
        self.chosen_towards_ports = set()
        self.chosen_towards_port = None

        self.away_ports = set()
        self.inactive_away_ports = set()
        self.pruned_away_ports = set()
        self.selected_away_ports = set()

        all_peer_ports = set(self.stack.canonical_up_ports())
        if self.stack.is_root():
            self.away_ports = all_peer_ports
        else:
            port_peer_distances = {
                port: len(port.stack['dp'].stack.shortest_path_to_root())
                for port in all_peer_ports}
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
                self.chosen_towards_port = self.stack.canonical_up_ports(
                    self.chosen_towards_ports)[0]

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
                for ports in ports_by_dp.values():
                    remote_away_ports = self.stack.canonical_up_ports(
                        [port.stack['port'] for port in ports])
                    self.pruned_away_ports.update([
                        port.stack['port'] for port in remote_away_ports
                        if port != remote_away_ports[0]])
                self.selected_away_ports = (
                    self.away_ports - self.pruned_away_ports - self.inactive_away_ports)

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
            int: Output port number for the current node of the tunnel
        """
        if not self.stack.is_in_path(src_dp, dst_dp):
            # No known path from the source to destination DP, so no port to output
            return None
        out_port = self.stack.shortest_path_port(dst_dp)
        if self.stack.name == dst_dp:
            # Current stack node is the destination, so output to the tunnel destination port
            out_port = dst_port
        elif out_port:
            out_port = out_port.number
        return out_port

    def update_health(self, now, last_live_times, update_time):
        """
        Returns whether the current stack node is healthy, a healthy stack node
            is one that attempted connected recently, or was known to be running
            recently, has all LAGs UP and any stack port UP

        Args:
            now (float): Current time
            last_live_times (dict): Last live time value for each DP
            update_time (int): Stack root update interval time
        Returns:
            bool: True if current stack node is healthy
        """
        prev_health = self.stack.dyn_healthy
        new_health, reason = self.stack.update_health(
            now, last_live_times, update_time, self.dp.lacp_down_ports(),
            self.stack.down_ports())
        if prev_health != new_health:
            health = 'HEALTHY' if new_health else 'UNHEALTHY'
            self.logger.info('Stack node %s %s (%s)' % (self.stack.name, health, reason))
        return new_health

    def consistent_roots(self, expected_root_name, valve, other_valves):
        """Returns true if all the stack nodes have the root configured correctly"""
        stacked_valves = {valve}.union(self.stacked_valves(other_valves))
        for stack_valve in stacked_valves:
            if stack_valve.dp.stack.root_name != expected_root_name:
                return False
        return True

    def nominate_stack_root(self, root_valve, other_valves, now, last_live_times, update_time):
        """
        Nominate a new stack root

        Args:
            root_valve (Valve): Previous/current root Valve object
            other_valves (list): List of other valves (not including previous root)
            now (float): Current time
            last_live_times (dict): Last live time value for each DP
            update_time (int): Stack root update interval time
        Returns:
            str: Name of the new elected stack root
        """
        stack_valves = {valve for valve in other_valves if valve.dp.stack}
        if root_valve:
            stack_valves = {root_valve}.union(stack_valves)

        # Create lists of healthy and unhealthy root candidates
        healthy_valves = []
        unhealthy_valves = []
        for valve in stack_valves:
            if valve.dp.stack.is_root_candidate():
                healthy = valve.stack_manager.update_health(now, last_live_times, update_time)
                if healthy:
                    healthy_valves.append(valve)
                else:
                    unhealthy_valves.append(valve)

        if not healthy_valves and not unhealthy_valves:
            # No root candidates/stack valves, so no nomination
            return None

        # Choose a candidate valve to be the root
        if healthy_valves:
            # Healthy valves exist, so pick a healthy valve as root
            new_root_name = None
            if root_valve:
                new_root_name = root_valve.dp.name
            if root_valve not in healthy_valves:
                # Need to pick a new healthy root if current root not healthy
                stacks = [valve.dp.stack for valve in healthy_valves]
                _, new_root_name = stacks[0].nominate_stack_root(stacks)
        else:
            # No healthy stack roots, so forced to choose a bad root
            stacks = [valve.dp.stack for valve in unhealthy_valves]
            _, new_root_name = stacks[0].nominate_stack_root(stacks)

        return new_root_name

    def is_stack_port(self, port):
        """Return whether the port is a stack port"""
        return port in self.stack.ports

    def is_away_port(self, port):
        """Return whether the port is an away port for the node"""
        return port in self.away_ports

    def is_towards_root_port(self, port):
        """Return whether the port is a port towards the root for the node"""
        return port in self.towards_root_ports

    def is_selected_towards_root_port(self, port):
        """Return true if port is the chosen port towards the stack root"""
        return port == self.chosen_towards_port

    def is_selected_away_port(self, port):
        """Return true if the port is a chosen port away from the root"""
        return port in self.selected_away_ports

    def adjacent_stack_ports(self, peer_dp):
        """Return list of ports that connect to an adjacent DP"""
        return [port for port in self.stack.ports if port.stack['dp'] == peer_dp]
