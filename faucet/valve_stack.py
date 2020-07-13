"""Manage higher level stack functions"""


from faucet.valve_manager_base import ValveManagerBase


class ValveStackManager(ValveManagerBase):
    """Implement stack manager, this handles the more higher-order stack functions.
This includes port nominations and flood directionality. This class also handles the
updating of stack port states.

ValveStackManager also changes behaviour decisions based on the stack topology and the valves'
position in the stack.
"""

    @staticmethod
    def _stacked_valves(valves):
        return {valve for valve in valves if valve.dp.stack and valve.dp.stack.root_name}

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
        self.reset_peer_distances()


    def recalculate_distances(self):
        """ """
        self.towards_root_ports = set()
        self.away_from_root_ports = set()

        all_peer_ports = set(self.stack.canonical_up_ports())

        if self.stack.is_root():
            # Root case, no ports towards self, all stack ports are away from self
            self.away_from_root_ports = all_peer_ports

        else:
            # Either an edge switch or a transit switch

            # Get distances for each peer
            port_peer_distances = {
                port: len(port.stack['dp'].stack.shortest_path_to_root() for port in all_peer_ports)}

            # Get the shortest distance to the root DP, this is choosing the path
            shortest_peer_distance = None
            for port, port_peer_distance in port_peer_distances.items():
                if shortest_peer_distance is None:
                    shortest_peer_distance = port_peer_distance
                    continue
                shortest_peer_distance = min(shortest_peer_distance, port_peer_distance)

            # 
            self.towards_root_ports = {
                port for port, port_peer_distance in port_peer_distances.items()
                if port_peer_distance == shortest_peer_distance}

            # 
            if self.towards_root_ports:
                # Choose the port that is the chosen shortest path towards the root
                shortest_path = self.stack.shortest_path_to_root()

            self.away_from_root_ports = all_peer_ports - self.all_towards_root_ports


    # TODO: prune away/towards ports
    def pruned_away_ports(self):
        """ """


    def pruned_towards_ports(self):
        """ """


    # TODO: Returns true; whether port is away/towards the root
    def port_is_away(self, in_port):
        """ """

    def port_is_towards(self, in_port):
        """ """



    def _reset_peer_distances(self):
        """Reset distances to/from root for this DP."""
        self.all_towards_root_stack_ports = set()
        self.towards_root_stack_ports = set()
        self.away_from_root_stack_ports = set()
        all_peer_ports = set(self.stack.canonical_up_ports())
        if self.is_stack_root():
            self.away_from_root_stack_ports = all_peer_ports
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
            if self.all_towards_root_stack_ports:
                # Choose the port that is the chosen shortest path towards the root
                shortest_path = self.dp_shortest_path_to_root()
                if shortest_path and len(shortest_path) > 1:
                    first_peer_dp = self.dp_shortest_path_to_root()[1]
                else:
                    first_peer_port = self.canonical_port_order(
                        self.all_towards_root_stack_ports)[0]
                    first_peer_dp = first_peer_port.stack['dp'].name
                self.towards_root_stack_ports = {
                    port for port in self.all_towards_root_stack_ports
                    if port.stack['dp'].name == first_peer_dp}  # pytype: disable=attribute-error
            self.away_from_root_stack_ports = all_peer_ports - self.all_towards_root_stack_ports
            if self.towards_root_stack_ports:
                self.logger.info(
                    'shortest path to root is via %s' % self.towards_root_stack_ports)
            else:
                self.logger.info('no path available to root')

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



    def healthy_roots(self, now, candidate_dps):
        """Return list of healthy stack root names."""
        healthy_stack_roots_names = [
            dp.name for dp in candidate_dps if self._stack_root_healthy(now, dp)]
        return healthy_stack_roots_names

    def stack_healthy(self, now, last_live_time=0):
        """Return True if a candidate DP is healthy."""
        # A healthy stack root is one that attempted connection recently,
        # or was known to be running recently.
        health_timeout = now - self.stack.root_down_time_multiple
        # Too long since last contact.
        if last_live_time < health_timeout:
            # 
            return False
        if not candidate_dp.all_lags_up():
            # self.dp.all_lags_up()
            return False
        if not self.stack.any_port_up():
            return False
        return True

    def update_stack_root(self, now, current_root_name, other_valves, last_live_time=0):
        """ """
        new_root_name = current_root_name
        stacked_valves = {self}.union(self._stacked_valves(other_valves))
        candidate_dps = [valve.dp.name for valve in stacked_valves if valve.dp.name in self.stack.roots_names]
        healthy_roots_names = self.healthy_roots(now, candidate_dps)
        if healthy_stack_roots_names:
            # Healthy stack roots exist
            if current_root_name not in healthy_roots_names:
                # Only pick a new stack root if the current one is not healthy
                new_root_name = healthy_roots_names[0]
        else:
            # Not healthy stack roots, so choose the first non-healthy root
            new_root_name = self.stack.roots_names[0]
        return new_root_name

   def maintain_stack_root(self, now, other_valves, last_live_time=0):
        """Maintain current stack root and return True if stack root changes."""

        stack_change = False
        if self.meta_dp_state.stack_root_name != new_stack_root_name:
            self.logger.info('stack root changed from %s to %s' % (
                self.meta_dp_state.stack_root_name, new_stack_root_name))
            if self.meta_dp_state.stack_root_name:
                stack_change = True
                prev_root = [dp for dp in stacked_dps if dp.name == self.meta_dp_state.stack_root_name]
                labels = prev_root[0].base_prom_labels()
                self.metrics.is_dp_stack_root.labels(**labels).set(0)
            self.meta_dp_state.stack_root_name = new_stack_root_name
            dpids = [dp.dp_id for dp in stacked_dps if dp.name == new_stack_root_name]
            self.metrics.faucet_stack_root_dpid.set(dpids[0])
        else:
            inconsistent_dps = [
                dp.name for dp in stacked_dps
                if dp.stack.root_name != self.meta_dp_state.stack_root_name]
            if inconsistent_dps:
                self.logger.info('stack root on %s inconsistent' % inconsistent_dps)
                stack_change = True

        if stack_change:
            self.logger.info(
                'root now %s (all candidates %s, healthy %s)' % (
                    self.meta_dp_state.stack_root_name,
                    candidate_stack_roots_names,
                    healthy_stack_roots_names))
            dps = dp_preparsed_parser(self.meta_dp_state.top_conf, self.meta_dp_state)
            # TODO: Ends up reconfiguring all DPS
            self._apply_configs(dps, now, None)
        root_dps = [dp for dp in stacked_dps if dp.name == new_stack_root_name]
        labels = root_dps[0].base_prom_labels()
        self.metrics.is_dp_stack_root.labels(**labels).set(1)
        return stack_change




    # TODO:
    # Have a function that takes in a dp and returns where that 
    #   DP is in regards to this stack, i.e. edge, root, path_to_root, path_to_edge
    def get_dp_location(self, dp_name):
        """ """


    #

    def edge_learn_port_towards(self, pkt_meta, edge_dp):
        """
        Args:
            pkt_meta (PacketMeta):
            edge_dp (DP):
        Returns:
        """
        if pkt_meta.vlan.edge_learn_stack_root:
            return self.shortest_path_root(edge_dp.name)
        return self.shortest_path_port(edge_dp.name)

    def shortest_path_root(self, edge_dp_name):
        """
        Return the port along the shortest path to/from root for edge learning

        Args:
            edge_dp_name (str): DP name
        Returns:
            Port: Port that is either towards or away from the root
        """
        # Path from current node to root
        path_to_root = self.dp_shortest_path_to_root()
        if not path_to_root:
            # No path from current node to the root, return the shortest path to the destination DP
            return self.shortest_path_port(edge_dp_name)

        # ????
        this_dp = path_to_root[0]
        # Path from current node to destination DP
        path_from_edge = self.dp_shortest_path_to_root(edge_dp_name)

        # If this is the edge switch, then learn using default algorithm.
        if not path_from_edge or this_dp == path_from_edge[0]:
            # No path to root from destination OR current DP is destination DP
            return self.shortest_path_port(edge_dp_name)

        # If this switch is along the path towards the edge, then head away
        if this_dp in path_from_edge:
            # Current DP is a transit switch for the path

            # Get node before current node
            away_dp = path_from_edge[path_from_edge.index(this_dp) - 1]

            # Get all ports shortest path towards the previous node in the path
            all_away_up_ports = self.stack.canonical_up_ports(self.away_from_root_stack_ports)
            away_up_ports = [port for port in all_away_up_ports if port.stack['dp'].name == away_dp]

            # Return first choice port
            return away_up_ports[0] if away_up_ports else None

        # If not, then head towards the root
        towards_up_ports = self.stack.canonical_up_ports(self.towards_root_stack_ports)
        # Take first port towards the root
        return towards_up_ports[0] if towards_up_ports else None

    def _stack_flood_ports(self):
        """
        Obtain output ports of a DP that have been pruned and follow reflection rules

        Returns:
            list: Output ports of a DP that have been pruned and follow reflection rules
        """
        # TODO: Consolidate stack port selection logic,
        #           this reuses logic from _build_mask_flood_rules()
        away_flood_ports = []
        towards_flood_ports = []
        # Obtain away ports
        away_up_ports_by_dp = defaultdict(list)
        for port in self.stack.canonical_up_ports(self.away_from_root_stack_ports):
            away_up_ports_by_dp[port.stack['dp']].append(port)
        # Obtain the towards root path port (this is the designated root port)
        towards_up_port = None
        towards_up_ports = self.stack.canonical_up_ports(self.towards_root_stack_ports)
        if towards_up_ports:
            towards_up_port = towards_up_ports[0]
        # Figure out what stack ports will need to be flooded
        for port in self.stack_ports:
            remote_dp = port.stack['dp']
            away_up_port = None
            away_up_ports = away_up_ports_by_dp.get(remote_dp, None)
            if away_up_ports:
                # Pick the lowest port number on the remote DP.
                remote_away_ports = self.canonical_port_order(
                    [away_port.stack['port'] for away_port in away_up_ports])
                away_up_port = remote_away_ports[0].stack['port']
            # Is the port to an away DP, (away from the stack root)
            away_port = port in self.away_from_root_stack_ports
            # Otherwise it is towards the stack root
            towards_port = not away_port

            # Prune == True for ports that do not need to be flooded
            if towards_port:
                # If towards the stack root, then if the port is not the chosen
                #   root path port, then we do not need to flood to it
                prune = port != towards_up_port
                if not prune and not self.is_stack_root():
                    # Port is chosen towards port and not the root so flood
                    #   towards the root
                    towards_flood_ports.append(port)
            else:
                # If away from stack root, then if the port is not the chosen
                #   away port for that DP, we do not need to flood to it
                prune = port != away_up_port
                if not prune and self.is_stack_root():
                    # Port is chosen away port and the root switch
                    #   so flood away from the root
                    away_flood_ports.append(port)

        # Also need to turn off inactive away ports (for DPs that have a better way to get to root)
        exclude_ports = self._inactive_away_stack_ports()
        away_flood_ports = [port for port in away_flood_ports if port not in exclude_ports]
        return towards_flood_ports + away_flood_ports

    def inactive_away_stack_ports(self):
        """
        Obtains list of ports that are chosen to be redundant/inactive

        Returns:
            list: List of ports set to inactive
        """
        all_peer_ports = set(self.stack.canonical_up_ports())
        shortest_path = self.dp_shortest_path_to_root()
        if not shortest_path or len(shortest_path) < 2:
            return []
        self_dp = shortest_path[0]
        inactive = []
        for port in all_peer_ports:
            shortest_path = port.stack['dp'].stack.shortest_path_to_root()
            if len(shortest_path) > 1 and shortest_path[1] != self_dp:
                inactive.append(port)
        return inactive
