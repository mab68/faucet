"""Manage higher level stack functions"""


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
        super(ValveSwitchStackManagerBase, self).__init__(**kwargs)
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
        self.active_away_ports = None
        # First UP port for each adjacent DP
        self.pruned_away_ports = None

        self.reset_peer_distances()

    @staticmethod
    def _stacked_valves(valves):
        return {valve for valve in valves if valve.dp.stack and valve.dp.stack.root_name}

    def pruned_stack_flood_ports(self):
        """ """
        # TODO: re-write
        chosen_towards_port = set()
        pruned_towards_ports = set()
        chosen_away_ports = set()
        pruned_away_ports = set()

        if self.stack.dyn_chosen_towards_ports:
            # To prune towards_ports, choose the canonical first UP chosen_towards_port
            pruned_towards_ports = self.stack.canonical_up_ports(self.stack.dyn_chosen_towards_ports)
            chosen_port = pruned_towards_ports[0]
            pruned_towards_ports.remove(chosen_towards_port[0])
            chosen_towards_port = set(chosen_port)

        if self.stack.dyn_away_ports:
            # To prune away_ports, choose first UP ports for all adjacent (non-towards) ports
            away_up_ports_by_dp = defaultdict(list)
            for port in self.stack.canonical_up_ports(self.stack.dyn_away_ports):
                away_up_ports_by_dp[port.stack['dp']].append(port)
            for dp, ports in away_up_ports_by_dp.items():
                remote_away_ports = self.canonical_port_order(
                    [port.stack['port'] for port in ports])
                chosen_remote_away_port = remote_away_port[0]
                remote_away_ports.remove(chosen_remote_away_port)
                chosen_away_ports.add(chosen_remote_away_port.stack['port'])
                for port in remote_away_ports:
                    pruned_away_ports.add(port.stack['port'])              

        return chosen_towards_port, pruned_towards_ports, chosen_away_ports, pruned_away_ports

    def reset_peer_distances(self):
        """Recalculates the towards and away ports for this node"""
        self.towards_root_ports = set()
        self.chosen_towards_ports = set()
        self.chosen_towards_port = None

        self.away_ports = set()
        self.active_away_ports = set()
        self.pruned_away_ports = set()

        all_peer_ports = set(self.stack.canonical_up_ports())
        if self.is_stack_root():
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
            self.all_towards_root_stack_ports = {
                port for port, port_peer_distance in port_peer_distances.items()
                if port_peer_distance == shortest_peer_distance}
            self.away_ports = all_peer_ports - self.towards_root_ports

            if self.towards_root_ports:
                # Generate a shortest path to calculate the chosen connection to root
                shortest_path = self.shortest_path_to_root()
                # Choose the port that is connected to peer DP
                if shortest_path and len(shortest_path) > 1:
                    first_peer_dp = shortest_path[1]
                else:
                    first_peer_port = self.canonical_port_order(
                        self.towards_root_ports)[0]
                    first_peer_dp = first_peer_port.stack['dp'].name
                # The chosen towards ports are the ports through the chosen peer DP
                self.chosen_towards_ports = {
                    port for port in self.towards_root_ports
                    if port.stack['dp'].name == first_peer_dp}

            if self.chosen_towards_ports:
                self.chosen_towards_port = self.stack.canonical_up_ports(self.chosen_towards_ports)[0]

            # Away ports are all the remaining (non-towards) ports
            self.away_ports = all_peer_ports - self.towards_root_ports

            if self.away_ports:
                # Get inactive away ports, ports whose peers have a better path to root
                self.active_away_ports = {
                    for port in self.away_ports
                    if self.is_in_path(self.root_name, port.stack['dp'].name)}

            if self.active_away_ports:
                # Get pruned away ports
                ports_by_dp = defaultdict(list)
                for port in self.active_away_ports:
                    ports_by_dp[port.stack['dp']].append(port)
                for dp, ports in ports_by_dp.items():
                    remote_away_ports = self.stack.canonical_up_ports(
                        [port.stack['port'] for port in ports])
                    # TODO: nonpruned_port = remote_away_ports[0]

        return self.chosen_towards_ports

    def update_stack_topo(self, event, dp, port):
        """
        Update the stack topo according to the event.

        Args:
            event (bool): True if the port is UP
            dp (DP): DP object
            port (Port): The port being brought UP/DOWN
        """
        before_ports = self.stack.dyn_chosen_towards_ports
        self.stack.modify_link(dp, port, event)
        after_ports = self.stack.recalculate_ports()
        if after_ports != before_ports:
            if towards_ports:
                self.logger.info('shortest path to root is via %s' % after_ports)
            else:
                self.logger.info('no path available to root')



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
        # TODO: This should not be here too
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
        # TODO: This part should be in valve_switch_stack??
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


    def default_port_towards(self, dp_name):
        """
        Default shortest path towards the provided destination, via direct

        Args:
            dp_name (str): Destination DP
        Returns:
           Port: port from current node that is shortest directly towards destination
        """
        return self.shortest_path_port(dp_name)

    def relative_port_towards(self, dp_name):
        """
        Returns the shortest path towards provided destination, via either the root or direct

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
        if path_to_root:
            # Current node is a transit node between root & destination, direct path to destination
            away_dp = path_to_root[path_to_root.index(self.stack.name) - 1]
            away_up_ports = [
                port for port in self.stack.canonical_up_ports(self.stack.dyn_away_ports)
                if port.stack['dp'].name == away_dp]
            return away_up_ports[0] if away_up_ports else None
        else:
            # Otherwise, head towards the root, path to destination via root
            towards_up_ports = self.stack.canonical_up_ports(self.stack.dyn_chosen_towards_ports)
            return towards_up_ports if towards_up_ports else None

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
