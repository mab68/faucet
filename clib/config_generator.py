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

import random
import networkx
import yaml

from mininet.topo import Topo


class GenerationError(Exception):
    """Indicates a problem with generating the configuration file"""
    pass


class FaucetTopoGenerator(Topo):

    # Host CPU option
    CPUF = 0.5
    # Link delay option
    DELAY = '1ms'

    # Switch index map to switch name
    switches_by_id = None
    # Switch name map to list of ports
    # TODO: switch_ports_by_name already exists as self.ports[src][sport] = (dst, dst_port)
    switch_ports_by_name = None
    # Host index map to host name
    hosts_by_id = None

    def dp_dpid(self, i):
        """DP DPID"""
        if i == 0 and self.hw_dpid:
            return self.hw_dpid
        # TODO: generate random DPID
        return '%u' % (i+1)

    def vlan_name(self, i):
        """VLAN name"""
        return 'vlan-%i' % (i+1)

    def vlan_vid(self, i):
        """VLAN VID value"""
        return (i+1) * 100

    def vlan_mac(self, i):
        """VLAN MAC"""
        return '00:00:00:00:00:%u%u' % (i+1, i+1)

    def vlan_vip(self, i):
        """VLAN VIP"""
        return '10.%u.0.254/%u' % (i+1, self.NETPREFIX)

    def host_mac_address(self, host_index, vlan_index):
        """ """
        return ''

    def host_ip_address(self, host_index, vlan_index):
        """Create a string of the host IP address"""
        # TODO: Create multiple addresses/interfaces for a tagged VLAN
        if isinstance(vlan_index, tuple):
            vlan_index = vlan_index[0]
        return '10.%u.0.%u/%u' % (vlan_index+1, host_index+1, self.NETPREFIX)

    def router_name(self, i):
        """Router name"""
        return 'router-%s' % (i+1)

    def __init__(self, *args, **kwargs):
        self.switches_by_id = {}
        self.switch_ports_by_name = {}
        self.hosts_by_id = {}
        super().__init__(*args, **kwargs)

    @staticmethod
    def _get_sid_prefix(ports_served):
        """Return a unique switch/host prefix for a test."""
        # Linux tools require short interface names.
        id_chars = ''.join(sorted(string.ascii_letters + string.digits))  # pytype: disable=module-attr
        id_a = int(ports_served / len(id_chars))
        id_b = ports_served - (id_a * len(id_chars))
        return '%s%s' % (
            id_chars[id_a], id_chars[id_b])

    @staticmethod
    def extend_port_order(self, port_order=None, max_length=16):
        """
        Extends the pattern of port_port order up to max_length

        Args:
            port_order (list): List of integers in an order to extend
            max_length (int): Maximum length to extend the list to
        """
        if not port_order:
            return list(range(max_length + 1))
        extend_order = []
        start_port = max(port_order)
        for i in port_order:
            extend_order.append(start_port + i)
            if len(port_order) + len(extend_order) >= max_length:
                break
        return port_order + extend_order

    def _generate_sid_prefix(self):
        """Returns a sid prefix for a node in the topology"""
        return self._get_sid_prefix(get_serialno(self.ports_sock, self.test_name))

    def _create_next_port(self, switch_name):
        """
        Creates and returns the next port number for a switch

        Args:
            switch_name (str): The name of the switch to generate the next port
        """
        index = len(self.switch_ports_by_name[switch_name])
        port = self.start_port + self.port_order[index]
        self.switch_ports_by_name[switch_name].append(port)
        return port

    def _add_host(self, host_index, vlans):
        """
        Adds a untagged/tagged host to the topology

        Args:
            sid_prefix (str): SID prefix to generate the host name
            host_index (int): Host index to generate the host name
            vlans (list/None/int): Type of host/vlans the host belongs to
        """
        # TODO: host IP address
        # TODO: host MAC address
        sid_prefix = self._generate_sid_prefix()
        host_opts = self.host_options.get(host_index, {})
        config_opts = {'vlans': vlans}
        host_name, host_cls = None, None
        if isinstance(vlans, int):
            vlans = None
            host_name = 'u%s%1.1u' % (sid_prefix, host_index + 1)
            host_cls = FaucetHost
        elif isinstance(vlans, list):
            vlans = [self.vlan_vid(vlan) for vlan in vlans]
            host_name = 't%s%1.1u' % (sid_prefix, host_index + 1)
            host_cls = VLANHost
        elif 'cls' in host_opts:
            host_name = 'e%s%1.1u' % (sid_prefix, host_index + 1)
            host_cls = self.host_opts['cls']
            host_opts = host_opts.copy()
            host_opts.pop('cls')
        else:
            raise GenerationError('Unknown host type')
        self.hosts_by_id[host_index] = host_name
        return self.addHost(
            name=host_name,
            vlans=vlans,
            cls=host_cls,
            cpu=self.CPUF,
            **host_opts,
            config_opts={})

    def _add_faucet_switch(self, switch_index):
        """
        Adds a Faucet switch to the topology

        Args:
            sid_prefix (str): SID prefix to generate the switch name
            switch_index (int): Switch index to generate the host name
            dpid (int): Switch DP ID
            config_opts (dict): Additional configuration options for Faucet configuration file
        """
        sid_prefix = self._generate_sid_prefix()
        switch_cls = FaucetSwitch
        switch_name = 's%s' % sid_prefix
        if switch_index == 0 and self.hw_dpid:
            raw_dpid = self.hw_dpid
            dpid = str(int(self.hw_dpid) + 1)
            output('bridging hardware switch DPID %s (%x) dataplane via OVS DPID %s (%x)\n' % (
                raw_dpid, int(raw_dpid), dpid, int(dpid)))
            switch_cls = NoControllerFaucetSwitch
        else:
            dpid = self.dp_dpid(switch_index)
            raw_dpid = dpid
        self.switch_ports_by_name[switch_name] = []
        config_opts['dp_id'] = raw_dpid
        return self.addSwitch(
            name=switch_name,
            cls=switch_cls,
            datapath=self.ovs_type,
            dpid=mininet_test_util.mininet_dpid(dpid),
            switch_n=switch_index,
            config_opts=config_opts)

    def _add_link(self, node, peer_node, vlans):
        """
        Creates and adds a link between two nodes to the topology

        Args:
            node (str): Name of the node for the link
            peer_node (str): Name of the peer node for the link
            vlans (list/None/int): Type of the link
        """
        port1, port2 = None, None
        delay, htb = None, None
        if node in self.switch_ports_by_name:
            # Node is a switch, create port
            port = self._create_next_port(node)
        if peer_node in self.switch_ports_by_name:
            # Peer node is a switch, create port
            port2 = self._create_next_port(peer_node)
        else:
            # Peer node is a host, use delay & htb options
            delay = self.DELAY
            htb = True
        config_opts = {}
        config_opts['vlans'] = vlans
        return self.addLink(
            node,
            peer_node,
            port1=port1,
            port2=port2,
            delay=delay,
            use_htb=htb,
            config_opts=config_opts)

    def add_switch_topology(self, switch_links, link_vlans):
        """
        Adds the switches and switch-switch links to the network topology
        Tagged links are mapped to a list of vlan indices whereas untagged links
            are mapped to a single vlan index, stack links are mapped to None

        Args:
            switch_topology (list): List of link tuples of switch indices (u, v)
            link_vlans (dict): Link tuple of switch indices (u, v) mapping to vlans
        """
        for u, v in switch_links:
            if u not in self.switches_by_id:
                self._add_faucet_switch(u)
            if v not in self.switches_by_id:
                self._add_faucet_switch(v)
            u_name = self.switches_by_id[u]
            v_name = self.switches_by_id[v]
            self._add_link(u_name, v_name, link_vlans[(u, v)])

    def add_host_topology(self, host_links, host_vlans):
        """
        Adds the hosts and host-switch links to the network topology
        Tagged hosts are mapped to a list of vlan indices whereas untagged hosts
            are mapped to a single vlan index

        Args:
            host_links (dict): Host index key to list of dp indices
            host_vlans (dict): Host index key to vlan index/indices
        """
        for h, links in host_links.items():
            vlans = host_vlans[h]
            if h not in self.hosts_by_id:
                self._add_host(h, vlans)
            host_name = self.hosts_by_id[h]
            for dp in links:
                if dp not in self.switches_by_id:
                    self.create_switch(dp)
                switch_name = self.switches_by_id[dp]
                self._add_link(switch_name, host_name, vlans)

    def build(self, ovs_type, ports_sock, test_name,
              host_links, host_vlans, switch_links, link_vlans,
              hw_dpid=None, hw_ports=None,
              port_order=None, start_port=SWITCH_START_PORT,
              get_serialno=get_serialno, host_options=None, e_cls=None, e_tmpdir=None):
        """
        Creates a Faucet mininet topology

        Args:
            ovs_type (str): The OVS switch type
            ports_sock (str): Port socket
            test_name (str): Name of the test creating the mininet topology
            host_links (dict): Host index key to list of dp indices
            host_vlans (dict): Host index key to vlan index/indices
            switch_links (list): List of link tuples of switch indices (u, v)
            link_vlans (dict): Link tuple of switch indices (u, v) mapping to vlans
            hw_dpid (int): DP ID of the hardware switch to connect to the topology
            hw_ports (list): Map of the OVS bridge port index to hardware port number
            port_order (list): List of integers in order for a switch port index order
            start_port (int): The minimum start port number for all switch port numbers
            get_serialno (func): Function to get the serial no.
            host_options (dict): Host index map to mininet host option
            e_cls (class): Class of the extended host
            e_tmpdir (str): Temporary directory of the extended host
        """
        # Additional test generation information
        self.ovs_type = ovs_type
        self.ports_sock = ports_sock
        self.test_name = test_name

        # Information for hardware switches
        self.hw_dpid = hw_dpid
        self.hw_ports = sorted(hw_ports) if hw_ports else []

        # Additional information for special hosts
        self.host_options = host_options

        # Generate a port order for all of the switches to use
        max_ports = len(switch_links) + len(host_links)
        self.start_port = start_port
        self.port_order = self.extend_port_order(port_order, max_ports)

        # Build the network topology
        self.add_switch_topology(switch_links, switch_vlans)
        self.add_host_topology(host_links, host_vlans)

    def get_acls_config(self, acl_options):
        """Return the ACLs in dictionary format for the configuration file"""
        return acl_options.copy()

    def get_dps_config(self, dp_options, host_options, link_options, dp_port_acls):
        """Return the DPs in dictionary format for the configuration file"""
        dps_config = {}

        def get_interface_config(self, link_name, src_port, dst_port, vlans, options, port_acls):
            interface_config = {}
            type_ = 'switch-switch' if dst_port else 'switch-host'
            if isinstance(vlans, int):
                # Untagged link
                interface_config = {
                    'name': 'untagged %s' % link_name,
                    'native_vlan': self.vlan_vid(vlans)
                }
            elif isinstance(vlans, list):
                # Tagged link
                interface_config = {
                    'name': 'tagged %s' % link_name,
                    'tagged_vlans': [self.vlan_vid(vlan) for vlan in vlans]
                }
            if dst_port and vlans is None:
                # Stack link
                interface_config = {
                    'name': 'stack %s' % link_name,
                    'stack': {
                        'dp': dst_node,
                        'port': dst_port
                    }
                }
            else:
                raise GenerationError('Unknown %s link type %s' % (type_, vlans))
            if options:
                for option_key, option_value in options.items():
                    interface_config[option_key] = option_value
            if port_acls:
                # TODO: this is a special case of options...
                interface_config['acls_in'] = list(port_acls)
            return interface_config

        def add_dp_config(self, src_node, dst_node, link_key, link_info, reverse=False):
            dp_config = dps_config[src_node]
            src_info, dst_info = self.nodeInfo(src_node), self.nodeInfo(dst_node)
            vlans = link_info['config_opts']['vlans']
            src_id = src_info['switch_n']
            dp_config.setdefault('interfaces', {})
            if self.isSwitch(dst_node):
                # Generate switch-switch config link
                if reverse:
                    src_port, dst_port = link_info['port2'], link_info['port1']
                else:
                    src_port, dst_port = link_info['port1'], link_info['port2']
                link_name = 'link #%s to %s:%s' % ((link_key + 1), dst_node, dst_port)
                options = {}
                dst_id = dst_info['switch_n']
                for pair in [(src_id, dst_id), (dst_id, src_id)]:
                    options.update(link_options[pair])
            else:
                # Generate host-switch config link
                src_port, dst_port = link_info['port1'], None
                link_name = 'link #%s to %s:%s' % ((link_key + 1), dst_node, dst_port)
                options = host_options[dst_info['host_n']]
            port_acls = dp_port_acls[src_id][src_port]
            dp_config['interfaces'][src_port] = self.get_interface_config(
                link_name, src_port, dst_port, vlans, options, port_acls)

        for links in self.links(withKeys=True, withInfo=True):
            # NOTE: src_node should always be a switch if we always create a link
            #   with switch as the src node
            # NOTE: This is assuming there are no duplicates of (src, dst) (dst, src) with the same key
            src_node, dst_node, link_key, link_info = links
            dps_config.setdefault(src_node, {})
            dps_config.setdefault(dst_node, {})
            src_info = self.nodeInfo(src_node)
            dst_info = self.nodeInfo(dst_node)
            vlans = link_info['config_opts']['vlans']
            if self.isSwitch(src_node):
                dps_config.setdefault(src_node, {})
                dps_config.setdefault('dp_id', src_info['config_opts']['dp_id'])
                add_dp_config(src_node, dst_node, link_key, link_info)
            if self.isSwitch(dst_node):
                dps_config.setdefault(dst_node, {})
                dps_config.setdefault('dp_id', dst_info['config_opts']['dp_id'])
                add_dp_config(dst_node, src_node, link_key, link_info, True)
        if dp_options:
            for dp, options in dp_options.items():
                switch_name = self.switches_by_id[dp]
                dps_config.setdefault(switch_name, {})
                for option_key, option_value in options.items():
                    dps_config[switch_name][option_key] = option_value
        return dps_config


    def get_vlans_config(self, n_vlans, vlan_options):
        """
        Return the VLANs in dictionary format for the YAML configuration file

        Args:
            n_vlans (int): Number of VLANs to generate
            vlan_options (dict): Additional options for each VLAN, keyed by vlan index
        """
        vlans_config = {}
        for vlan in range(n_vlans):
            vlan_name = self.vlan_name(vlan)
            vlans_config[vlan_name] = {
                'vid' = self.vlan_vid(vlan)
            }
        if vlan_options:
            for vlan, options in vlan_options.items():
                vlan_name = self.vlan_name(vlan)
                for option_key, option_value in options.items():
                    vlans_config[vlan_name][option_key] = option_value
        return vlans_config

    def get_routers_config(self, routers, router_options):
        """
        Return the routers in dictionary format for the configuration file

        Args:
            routers (dict): Router index to list of VLANs in the router
            router_options (dict): Additional options for each router, keyed by router index
        """
        routers_config = {}
        for router, vlans in routers.items():
            router_config[self.router_name(router)] = {
                'vlans': [self.vlan_name(vlan) for vlan in vlans]
            }
        if router_options:
            for router, options in router_options.items():
                router_name = self.router_name(router)
                for option_key, option_value in options.items():
                    routers_config[router_name][option_key] = option_value
        return routers_config

    def get_config(self, n_vlans, acl_options=None, dp_port_acls=None, dp_options=None, host_options=None,
                   link_options=None, vlan_options=None, routers=None, router_options=None,
                   include=None,include_optional=None):
        """
        Creates a Faucet YAML configuration file using the current topology

        Args:
            n_vlans (int): Number of VLANs to generate
            acl_options (dict): Acls in use in the Faucet configuration file
            dp_port_acls (dict): DP port to acl option mapping
            dp_options (dict): Additional options for each DP, keyed by DP index
            host_options (dict): Additional options for each host, keyed by host index
            link_options (dict): Additional options for each link, keyed by switch indices tuple (u, v)
            vlan_options (dict): Additional options for each VLAN, keyed by vlan index
            routers (dict): Router index to list of VLANs in the router
            router_options (dict): Additional options for each router, keyed by router index
            include (list): Files to include using the the Faucet config 'include' key
            include_optional (list): File to include using the Faucet config 'include_optional' key
        """
        config = {'version': 2}
        if include:
            config['include'] = list(include)
        if include_optional:
            config['include_optional'] = list(include_optional)
        config['acls'] = get_acls_config(acl_options)
        config['vlans'] = get_vlans_config(vlan_options)
        config['routers'] = get_routers_config(routers, router_options)
        config['dps'] = get_dps_config(dp_options, host_options, link_options, dp_port_acls)
        return yaml.dump(config, default_flow_style=False)


class FaucetFakeOFTopoGenerator(FaucetTopoGenerator):
    """ """

    def dp_dpid(self, i):
        """DP DPID"""
        return '%u' % (i+1)


class FaucetGenerator:
    # TODO: This takes mininet.topo to generate objects
    # TODO: This is provided mininet.topo and then generates those too

    # Network graph 
    network_topology = None
    # Switch index map to switches
    switches_by_id = None
    # Switch index map to list of switch links
    links_by_switch_id = None
    # Host index to hosts
    hosts_by_id = None
    # Vlan index to vlans
    vlans_by_id = None

    def dp_dpid(self, i):
        """DP DPID"""
        return '%u' % (i+1)

    def vlan_name(self, i):
        """VLAN name"""
        return 'vlan-%i' % (i+1)

    def vlan_vid(self, i):
        """VLAN VID value"""
        return (i+1) * 100

    def vlan_mac(self, i):
        """VLAN MAC"""
        return '00:00:00:00:00:%u%u' % (i+1, i+1)

    def vlan_vip(self, i):
        """VLAN VIP"""
        return '10.%u.0.254/%u' % (i+1, self.NETPREFIX)

    def host_ip_address(self, host_index, vlan_index):
        """Create a string of the host IP address"""
        if isinstance(vlan_index, tuple):
            vlan_index = vlan_index[0]
        return '10.%u.0.%u/%u' % (vlan_index+1, host_index+1, self.NETPREFIX)

    def router_name(self, i):
        """Router name"""
        return 'router-%s' % (i+1)

    def __init__(self):
        self.network_topology = networkx.MultiGraph()
        self.switches_by_id = {}
        self.links_by_switch_id = {}
        self.hosts_by_id = {}
        self.vlans_by_id = {}

    def _add_faucet_switch(self, index):
        """Creates the switch"""
        name = self.dp_name(index)
        dpid = self.dp_dpid(index)
        switch = FakeOFSwitch(name, dpid, index)
        self.switches_by_id[index] = switch
        self.links_by_switch_id[index] = []
        return switch

    def _add_host(self, index, vlans):
        """Creates the host"""
        name = self.host_name(index)
        host = FakeOFHost(name, index, vlans)
        self.hosts_by_id[index] = host
        return host

    def create_vlan(self, index):
        """Creates a VLAN"""
        name = self.vlan_name(index)
        vid = self.vlan_vid(index)
        vlan = FakeOFVLAN(name, index, vid)
        self.vlans_by_id[index] = vlan
        return vlan

    def create_link(self, node, peer_node, port, peer_port=None):
        """Creates a switch-switch or switch-host link"""
        name = node.name + '-' + peer_node.name
        link = FakeOFLink(name, 0, node, peer_node, port, peer_port)
        peer_link = FakeOFLink(name, 0, peer_node, node, peer_port, port)
        if isinstance(node, FakeOFSwitch):
            self.links_by_switch_id[node.index].append(link)
        if isinstance(peer_node, FakeOFSwitch):
            self.links_by_switch_id[peer_node.index].append(peer_link)
        return link

    def add_link_options(self, u, v, options):
        """
        Sets all the links u-v to contain the options

        Args:
            u (int): Source link switch index
            v (int): Destination link switch index
            options (dict): Options for the link
        """
        v_switch = self.switches_by_id[v]
        for link in self.links_by_switch_id[u]:
            if link.peer_node == v_switch:
                for vlan in vlans:
                    if vlan not in self.vlans_by_id:
                        self.create_vlan(vlan)
                link.options = options

    def add_link_vlans(self, u, v, vlans):
        """
        Sets all the links u-v to be of type determined by vlans
        int: untagged host
        list: tagged host
        None: stack link

        Args:
            u (int): Source link switch index
            v (int): Destination link switch index
            vlans (None/list/int): Sets the link type with vlans by indices
        """
        v_switch = self.switches_by_id[v]
        for link in self.links_by_switch_id[u]:
            if link.peer_node == v_switch:
                for vlan in vlans:
                    if vlan not in self.vlans_by_id:
                        self.create_vlan(vlan)
                link.vlans = vlans

    def add_switch_topology(self, switch_topology, link_vlans):
        """
        Adds the switches and switch-switch links to the network topology

        Args:
            switch_topology (networkx.MultiGraph): Graph of the switch topology with dp index nodes
            link_vlans (dict): Link tuple of switch indices (u, v) mapping to vlans
        """
        for u, v in switch_topology.edges():
            if u not in self.switches_by_id:
                u_switch = self.create_switch(u)
                self.network_topology.add_node(u_switch.name)
            else:
                u_switch = self.switches_by_id[u].name
            if v not in self.switches_by_id:
                v_switch = self.create_switch(v)
                self.network_topology.add_node(v_switch.name)
            else:
                v_switch = self.switches_by_id[v].name
            link = self.create_link(u_switch, v_switch, None, None)
            self.network_topology.add_edge(u_switch.name, v_switch.name)
        for pair, vlans in link_vlans.items():
            u, v = pair
            self.add_link_vlans(u, v, vlans)

    def add_host_topology(self, host_links, host_vlans):
        """
        Adds the hosts and host-switch links to the network topology
        Tagged hosts are mapped to a list of vlan indices whereas untagged hosts
            are mapped to a single vlan index

        Args:
            host_links (dict): Host key to list of dp indices
            host_vlans (dict): Host key to vlan index/indices
        """
        for h, links in host_links.items():
            if h not in self.hosts_by_id:
                vlans = host_vlans[h]
                for vlan in vlans:
                    if vlan not in self.vlans_by_id:
                        self.create_vlan(vlan)
                host = self.create_host(h, vlans)
                self.network_topology.add_node(host.name)
            else:
                host = self.hosts_by_id[h]
            for dp in links:
                if dp not in self.switches_by_id:
                    switch = self.create_switch(dp)
                    self.network_topology.add_node(switch.name)
                else:
                    switch = self.switches_by_id[dp]
                self.create_link(switch, host, None)
                self.network_topology.add_edge(host.name, switch.name)

    def get_acls_config(self, acl_options):
        """Return the ACLs in dictionary format for the configuration file"""
        return acl_options.copy()

    def get_vlans_config(self, vlan_options):
        """Return the VLANs in dictionary format for the configuration file"""
        vlans_config = {}
        for v, vlan in self.vlans_by_id.items():
            vlans_config[vlan.name] = {
                'description': '%s tagged, %s untagged' % (vlan.n_tagged, vlan.n_untagged),
                'vid': vlan.vid
            }
        if vlan_options:
            for v, options in vlan_options.items():
                vlan = self.vlans_by_id[v]
                for option_key, option_value in options.items():
                    vlans_config[vlan.name][option_key] = option_value
        return vlans_config

    def get_routers_config(self, routers, router_options):
        """Return the routers in dictionary format for the configuration file"""
        routers_config = {}
        for router, vlans in routers.items():
            router_config[self.router_name(router)] = {
                'vlans': [self.vlans_by_id[vlan].name for vlan in vlans]
            }
        if router_options:
            for router, options in router_options.items():
                for option_key, option_value in options.items():
                    router_config[self.router_name(router)][option_key] = option_value
        return routers_config

    def get_dps_config(self, dp_options, host_options, link_options, dp_port_acls):
        """Return the DPs in dictionary format for the configuration file"""
        dps_config = {}

        for dp, switch in self.switches_by_id.items():
            dp_config = {}
            dp_config['dp_id'] = switch.dpid
            interfaces_config = {}

            for link in links_by_switch_id[dp]:
                # TODO: port_map
                port = link.port
                interfaces_config[port] = {}
                interfaces_config[port]['name'] = link.name
                if isinstance(link.peer_node, FakeOFHost):
                    # Generate switch-host config links
                    host = link.peer_node
                    vlan_key = None
                    vlan_value = None
                    if isinstance(host.vlans, list):
                        # Tagged host
                        vlan_key = 'tagged_vlans'
                        vlan_value = [self.vlans_by_id[vlan].vid for vlan in host.vlans]
                    elif isinstance(host.vlans, int):
                        # Untagged host
                        vlan_key = 'native_vlan'
                        vlan_value = self.vlans_by_id[vlan].vid
                    if vlan_key is None or vlan_value is None:
                        raise ConfigGenerationError('Unknown host link type')
                    interfaces_config[port][vlan_key] = vlan_value
                    if host_options and host.index in host_options:
                        for option_key, option_value in host_options[host.index].items():
                            interfaces_config[port][option_key] = option_value
                elif isinstance(link.peer_node, FakeOFSwitch):
                    # Generate switch-switch config links
                    peer_switch, peer_port = link.peer_node, link.peer_port
                    if link.vlans is None:
                        # Stack link
                        interfaces_config[port].update({
                            'stack': {
                                'dp': peer_switch.name,
                                'port': peer_port
                            }
                        })
                    elif isinstance(link.vlans, int):
                        # Untagged link
                        interfaces_config[port]['native_vlan'] = self.vlans_by_id[link.vlans].vid
                    elif isinstance(link.vlans, list):
                        # Tagged link
                        interfaces_config[port]['tagged_vlans'] = [
                            self.vlans_by_id[vlan].vid for vlan in link.vlans]
                    else:
                        raise ConfigGenerationError('Unknown link type')
                    # TODO: This is not correct...
                    if (switch.index, peer_switch.index):
                    for option_key, option_value in link_options.items():
                        interfaces_config[port][option_key] = option_value
                else:
                    raise ConfigGenerationError('Unknown link peer type')
                if dp in dp_port_acls and port in dp_port_acls[dp]:
                    interfaces_config[port]['acls_in'] = dp_port_acls[dp][port]

            dp_config['interfaces'] = interfaces_config
            dps_config[switch.name] = dp_config

        for dp, options in dp_options.items():
            for option_key, option_value in options.items():
                dps_config[self.switches_by_id[dp].name][option_key] = option_value

        return dps_config

    def get_config(self, acl_options=None, dp_port_acls=None, dp_options=None, host_options=None,
                   link_options=None, vlan_options=None, routers=None, router_options=None,
                   include=None,include_optional=None):
        """
        Args:
            acl_options (dict): Acls in use in the Faucet configuration file
            dp_port_acls (dict): DP port to acl option mapping
            dp_options (dict): Additional options for each DP, keyed by DP index
            host_options (dict): Additional options for each host, keyed by host index
            link_options (dict): Additional options for each link, keyed by switch indices tuple (u, v)
            vlan_options (dict): Additional options for each VLAN, keyed by vlan index
            routers (dict): Router index to list of VLANs in the router
            router_options (dict): Additional options for each router, keyed by router index
            include (list):
            include_optional (list):
        """
        config = {'version': 2}
        if include:
            config['include'] = list(include)
        if include_optional:
            config['include_optional'] = list(include_optional)
        config['acls'] = get_acls_config(acl_options)
        config['vlans'] = get_vlans_config(vlan_options)
        config['routers'] = get_routers_config(routers, router_options)
        config['dps'] = get_dps_config(dp_options, host_options, link_options, dp_port_acls)
        return yaml.dump(config, default_flow_style=False)


if __name__ == '__main__':
    print('Testing')
    ftg = FaucetTopoGenerator()