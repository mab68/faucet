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
    """ """

    # Host CPU option
    CPUF = 0.5
    # Link delay option
    DELAY = '1ms'

    # Switch index map to switch name
    switches_by_id = None
    # Switch index map to switch dpid
    dpids_by_id = None
    # Host index map to host name
    hosts_by_id = None

    # Generated hardware switch name
    hw_name = None
    # DPID of the hardware switch
    hw_dpid = None
    # List of port order for the hardware switch
    hw_ports = None

    # Function to resolve serial numbers
    get_serialno = None

    # Additional mininet host options
    host_options = None

    # The generated starting port for each switch
    start_port = None
    # The port order for each switch
    port_order = None

    def get_dpids(self):
        """Returns list of DPIDs in switch index keyed order"""
        return [value for key, value in sorted(self.dpids_by_id.keys())]

    def create_port_maps(self):
        """Return a port map for each switch/dpid keyed by dpid"""
        port_maps = {}
        for i, dpid in self.dpids_by_id.items():
            switch_name = self.switches_by_id[i]
            ports = self.ports[switch_name].keys()
            port_maps[dpid] = {'port_%d' % i: port for i, port in enumerate(ports)}
        return port_maps

    def get_switch_peer_links(self, switch_index):
        """Returns a list of (port, peer_port) pairs for switch-switch links from switch_index"""
        switch_name = self.switches_by_id[switch_index]
        ports = self.ports[switch_name]
        peer_links = []
        for port, link in self.ports[switch_name].items():
            if self.isSwitch(link[0]):
                peer_links.append((port, link[1]))
        return peer_links

    def get_host_peer_links(self, host_index):
        """Returns a list of (peer_index, peer_port) pairs for host-switch links from host_index"""
        host_name = self.hosts_by_id[host_index]
        ports = self.ports[host_name]
        peer_links = []
        for port, link in self.ports[host_name].items():
            peer_name = link[0]
            switch_id = self.g.node[peer_name]['switch_n']
            peer_links.append((switch_id, link[1]))
        return peer_links

    def dp_dpid(self, i):
        """DP DPID"""
        if i == 0 and self.hw_dpid:
            return self.hw_dpid
        reserved_range = 100
        while True:
            dpid = random.randint(1, (2**32 - reserved_range)) + reserved_range
            if dpid not in self.dpids_by_id.values():
                return str(dpid)

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

    def router_name(self, i):
        """Router name"""
        return 'router-%s' % (i+1)

    def __init__(self, *args, **kwargs):
        self.switches_by_id = {}
        self.dpids_by_id = {}
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
        return self._get_sid_prefix(self.get_serialno(self.ports_sock, self.test_name))

    def _create_next_port(self, switch_name):
        """
        Creates and returns the next port number for a switch

        Args:
            switch_name (str): The name of the switch to generate the next port
        """
        index = len(self.ports[switch_name])
        if self.hw_name and switch_name == self.hw_name and self.hw_ports:
            return self.hw_ports[self.port_order[index]]
        return self.start_port + self.port_order[index]

    def _add_host(self, host_index, vlans):
        """
        Adds a untagged/tagged host to the topology

        Args:
            sid_prefix (str): SID prefix to generate the host name
            host_index (int): Host index to generate the host name
            vlans (list/None/int): Type of host/vlans the host belongs to
        """
        # TODO: host IP address
        sid_prefix = self._generate_sid_prefix()
        host_opts = self.host_options.get(host_index, {})
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
        """
        sid_prefix = self._generate_sid_prefix()
        switch_cls = FaucetSwitch
        switch_name = 's%s' % sid_prefix
        if switch_index == 0 and self.hw_dpid:
            self.hw_name = switch_name
            self.dpids_by_id[switch_index] = self.hw_dpid
            dpid = str(int(self.hw_dpid) + 1)
            output('bridging hardware switch DPID %s (%x) dataplane via OVS DPID %s (%x)\n' % (
                raw_dpid, int(raw_dpid), dpid, int(dpid)))
            switch_cls = NoControllerFaucetSwitch
        else:
            dpid = self.dp_dpid(switch_index)
            self.dpids_by_id[switch_index] = dpid
        return self.addSwitch(
            name=switch_name,
            cls=switch_cls,
            datapath=self.ovs_type,
            dpid=mininet_test_util.mininet_dpid(dpid),
            switch_n=switch_index)

    def _add_link(self, node, peer_node, vlans):
        """
        Creates and adds a link between two nodes to the topology

        Args:
            node (str): Name of the node for the link, NOTE: should ALWAYS be a switch
            peer_node (str): Name of the peer node for the link
            vlans (list/None/int): Type of the link
        """
        port1, port2 = None, None
        delay, htb = None, None
        if self.isSwitch(node):
            # Node is a switch, create port
            port = self._create_next_port(node)
        if self.isSwitch(peer_node):
            # Peer node is a switch, create port
            port2 = self._create_next_port(peer_node)
        else:
            # Peer node is a host, use delay & htb options
            delay = self.DELAY
            htb = True
        return self.addLink(
            node,
            peer_node,
            port1=port1,
            port2=port2,
            delay=delay,
            use_htb=htb,
            config_vlans=vlans)

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

    # TODO: Add back in get_serialno
    def build(self, ovs_type, ports_sock, test_name,
              host_links, host_vlans, switch_links, link_vlans,
              hw_dpid=None, hw_ports=None,
              port_order=None, start_port=5,
              get_serialno=None, host_options=None):
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
            host_options (dict): Host index map to additional mininet host options
        """
        # Additional test generation information
        self.ovs_type = ovs_type
        self.ports_sock = ports_sock
        self.test_name = test_name
        self.get_serialno = get_serialno

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
        self.add_switch_topology(switch_links, link_vlans)
        self.add_host_topology(host_links, host_vlans)

    def get_acls_config(self, acl_options):
        """Return the ACLs in dictionary format for the configuration file"""
        return acl_options.copy()

    def get_dps_config(self, dp_options, host_options, link_options):
        """Return the DPs in dictionary format for the configuration file"""
        dps_config = {}

        def get_interface_config(self, link_name, src_port, dst_port, vlans, options):
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
            src_node, dst_node, link_key, link_info = links
            dps_config.setdefault(src_node, {})
            dps_config.setdefault(dst_node, {})
            src_info = self.nodeInfo(src_node)
            dst_info = self.nodeInfo(dst_node)
            vlans = link_info['config_opts']['vlans']
            if self.isSwitch(src_node):
                dps_config.setdefault(src_node, {})
                dps_config.setdefault('dp_id', int(src_info['config_opts']['dp_id']))
                add_dp_config(src_node, dst_node, link_key, link_info)
            if self.isSwitch(dst_node):
                dps_config.setdefault(dst_node, {})
                dps_config.setdefault('dp_id', int(dst_info['config_opts']['dp_id']))
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
                'vid': self.vlan_vid(vlan)
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

    def get_config(self, n_vlans, acl_options=None, dp_options=None, host_options=None,
                   link_options=None, vlan_options=None, routers=None, router_options=None,
                   include=None, include_optional=None):
        """
        Creates a Faucet YAML configuration file using the current topology

        Args:
            n_vlans (int): Number of VLANs to generate
            acl_options (dict): Acls in use in the Faucet configuration file
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
        if acl_options:
            config['acls'] = self.get_acls_config(acl_options)
        config['vlans'] = self.get_vlans_config(n_vlans, vlan_options)
        if routers:
            config['routers'] = self.get_routers_config(routers, router_options)
        config['dps'] = self.get_dps_config(dp_options, host_options, link_options)
        return yaml.dump(config, default_flow_style=False)


class FaucetFakeOFTopoGenerator(FaucetTopoGenerator):
    """ """

    # NOTE: For now, we dont actually create the objects for the unittests
    #   so we can leave them as they are in the FaucetTopoGenerator function

    def dp_dpid(self, i):
        """DP DPID"""
        return '%u' % (i+1)
