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

import random
import networkx
import yaml


class ConfigGenerationError(Exception):
    """Indicates a problem with generating the configuration file"""
    pass


class FakeOFBase:

    # Name of the FakeOF object
    name = None
    # Index for the FakeOF object type
    index = None

    def __init__(self, name, index):
        self.name = name


class FakeOFSwitch(FakeOFBase):

    # DP ID for the switch
    dpid = None

    def __init__(self, name, dpid, index):
        super().__init__(name, index)
        self.dpid = dpid


class FakeOFHost(FakeOFBase):

    # VLAN(s) indices the host belongs to, dictates what type of host this is by the type of vlans
    # int: untagged host
    # list: tagged host
    vlans = None

    def __init__(self, name, index, vlans):
        super().__init__(name, index)
        self.vlans = vlans


class FakeOFVLAN(FakeOFBase):

    # Number of untagged hosts on the VLAN
    n_untagged = None
    # Number of tagged hosts on the VLAN
    n_tagged = None
    # VID for the VLAN
    vid = None

    def __init__(self, name, index, vid):
        super().__init__(name, index)
        self.vid = vid
        self.n_untagged = 0
        self.n_tagged = 0


class FakeOFLink(FakeOFBase):

    # Source node of the link
    node = None
    # The object that node is linked to
    peer_node = None
    # The port of node to reach peer_node
    port = None
    # The port of peer_node to reach node
    peer_port = None
    # VLAN(s) indices the link belongs to, dictates what type of link this is by the type of vlans
    # int: untagged host
    # list: tagged host
    # None: stack link
    vlans = None

    def __init__(self, name, index, node, peer_node, port=None, peer_port=None):
        super().__init__(name, index)
        self.node = node
        self.peer_node = peer_node
        self.vlans = []
        self.port = port
        self.peer_port = peer_port


class ConfigGenerator:

    # Network graph 
    network_topology = None
    # Switch index map to switches
    switches_by_id = None
    # Switch index map to list of switch links
    switch_links_by_switch_id = None
    # Host index to hosts
    hosts_by_id = None
    # Vlan index to vlans
    vlans_by_id = None

    def dp_name(self, i):
        """DP name"""
        return 'faucet-%u' % (i + 1)

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
        self.switch_links_by_switch_id = {}
        self.hosts_by_id = {}
        self.vlans_by_id = {}

    def create_switch(self, index):
        """Creates the switch"""
        name = self.dp_name(index)
        dpid = self.dp_dpid(index)
        switch = FakeOFSwitch(name, dpid, index)
        self.switches_by_id[index] = switch
        self.switch_links_by_switch_id[index] = []
        return switch

    def create_host(self, index, vlans):
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
        if isinstance(node, FakeOFSwitch):
            self.switch_links_by_switch_id[node.index].append(link)
        if isinstance(peer_node, FakeOFSwitch):
            self.switch_links_by_switch_id[peer_node.index].append(link)
        return link

    def add_switch_topology(self, switch_topology):
        """
        Adds the switches and switch-switch links to the network topology

        Args:
            switch_topology (networkx.MultiGraph): Graph of the switch topology with dp index nodes
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
            self.create_link(u_switch, v_switch, None, None)
            self.network_topology.add_edge(u_switch.name, v_switch.name)

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

    def get_dps_config(self, dp_options, host_options, dp_port_acls):
        """Return the DPs in dictionary format for the configuration file"""
        dps_config = {}

        for dp, switch in self.switches_by_id.items():
            dp_config = {}
            dp_config['dp_id'] = switch.dpid
            interfaces_config = {}

            for link in switch_links_by_switch_id[dp]:
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
                    for option_key, option_value in link.options.items():
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
                   vlan_options=None, routers=None, router_options=None,
                   include=None,include_optional=None):
        """
        Args:
            acl_options (dict): Acls in use in the Faucet configuration file
            dp_port_acls (dict): DP port to acl option mapping
            dp_options (dict): Additional options for each DP, keyed by DP index
            host_options (dict): Additional options for each host, keyed by host index
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
        config['dps'] = get_dps_config(dp_options, host_options, dp_port_acls)
        return yaml.dump(config, default_flow_style=False)








    def get_config(self, dpids=None, hw_dpid=None, hardware=None, ofchannel_log=None,
                   n_vlans=1, host_links=None, host_vlans=None, stack_roots=None,
                   include=None, include_optional=None, acls=None, acl_in_dp=None,
                   lacp_trunk=False, vlan_options=None, dp_options=None,
                   routers=None, host_options=None):
        """
        Args:
            dpids: List of DPIDs the dp indices in the configuration dictionaries refer to
            hw_dpid: DPID for connected hardware switch
            hardware:
            ofchannel_log: Debug log path
            n_vlans: Number of VLANs
            host_links (dict): host index to dp index
            host_vlans (dict): host index to vlan index
            stack_roots (dict): dp index to priority value (leave none for tagged links)
            include:
            include_optional:
            hw_dpid: DPID of hardware switch
            lacp_trunk: Use LACP trunk ports
            vlan_options (dict): vlan_index to key, value dp options
            dp_options (dict): dp index to key, value dp options
            routers (dict): router index to list of vlan index
            host_options (dict): Host index to host option key, values
        """
        if dpids is None:
            dpids = []
        if include is None:
            include = []
        if include_optional is None:
            include_optional = []
        if acls is None:
            acls = {}
        if acl_in_dp is None:
            acl_in_dp = {}

        def add_vlans(n_vlans, host_vlans, vlan_options):
            vlans_config = {}
            for vlan in range(n_vlans):
                n_tagged = 0
                n_untagged = 0
                for vlans in host_vlans.values():
                    if isinstance(vlans, int) and vlan == vlans:
                        n_untagged += 1
                    elif isinstance(vlans, tuple) and vlan in vlans:
                        n_tagged += 1
                vlans_config[self.vlan_name(vlan)] = {
                    'description': '%s tagged, %s untagged' % (n_tagged, n_untagged),
                    'vid': self.vlan_vid(vlan)
                }
            if vlan_options:
                for vlan, options in vlan_options.items():
                    for key, value in options.items():
                        vlans_config[self.vlan_name(vlan)][key] = value
            return vlans_config

        def add_routers(routers):
            router_config = {}
            for i, vlans in routers.items():
                router_config['router-%s' % i] = {
                    'vlans': [self.vlan_name(vlan) for vlan in vlans]
                }
            return router_config

        def add_acl_to_port(i, port, interfaces_config):
            if i in acl_in_dp and port in acl_in_dp[i]:
                interfaces_config[port]['acl_in'] = acl_in_dp[i][port]

        def add_dp(i, dpid, hw_dpid, ofchannel_log, group_table,
                   n_vlans, host_vlans, stack_roots, host_links, dpid_peer_links, port_maps):
            dp_config = {
                'dp_id': int(dpid),
                'hardware': hardware if dpid == hw_dpid else 'Open vSwitch',
                'ofchannel_log': ofchannel_log + str(i) if ofchannel_log else None,
                'interfaces': {},
                'group_table': group_table,
            }

            if dp_options and i in dp_options:
                for key, value in dp_options[i].items():
                    dp_config[key] = value

            if stack_roots and i in stack_roots:
                dp_config['stack'] = {}
                dp_config['stack']['priority'] = stack_roots[i]  # pytype: disable=unsupported-operands

            interfaces_config = {}
            # Generate host links
            index = 1
            for host_id, links in host_links.items():
                if i in links:
                    n_links = links.count(i)
                    vlan = host_vlans[host_id]
                    if isinstance(vlan, int):
                        key = 'native_vlan'
                        value = self.vlan_name(vlan)
                    else:
                        key = 'tagged_vlans'
                        value = [self.vlan_name(vlan) for vlan in vlan]
                    for _ in range(n_links):
                        port = port_maps[dpid]['port_%d' % index]
                        interfaces_config[port] = {
                            key: value
                        }
                        if host_options and host_id in host_options:
                            for option_key, option_value in host_options[host_id].items():
                                interfaces_config[port][option_key] = option_value
                        index += 1
                        add_acl_to_port(i, port, interfaces_config)

            # Generate switch-switch links
            for link in dpid_peer_links:
                # TODO: dpid_peer_links should be 
                port, peer_dpid, peer_port = link.port, link.peer_dpid, link.peer_port
                interfaces_config[port] = {}
                if stack_roots:
                    interfaces_config[port].update({
                        'stack': {
                            'dp': self.dp_name(dpids.index(peer_dpid)),
                            'port': peer_port
                        }})
                else:
                    tagged_vlans = [self.vlan_name(vlan) for vlan in range(n_vlans)]
                    interfaces_config[port].update({'tagged_vlans': tagged_vlans})
                    if lacp_trunk:
                        interfaces_config[port].update({
                            'lacp': 1,
                            'lacp_active': True
                        })
                        dp_config['lacp_timeout'] = 10
                add_acl_to_port(i, port, interfaces_config)

            dp_config['interfaces'] = interfaces_config
            return dp_config

        config = {'version': 2}
        if include:
            config['include'] = list(include)
        if include_optional:
            config['include_optional'] = list(include_optional)
        config['acls'] = acls.copy()
        config['vlans'] = add_vlans(n_vlans, host_vlans, vlan_options)

        if routers:
            config['routers'] = add_routers(routers)

        dpid_names = {dpids[i]: self.dp_name(i) for i in range(len(dpids))}
        self.set_dpid_names(dpid_names)

        config['dps'] = {}
        for i, dpid in enumerate(dpids):
            # TODO: GROUP_TABLE
            #       topo.dpid_peer_links(dpid)
            #       port_maps
            config['dps'][self.dp_name(i)] = add_dp(
                i, dpid, hw_dpid, ofchannel_log, self.GROUP_TABLE, n_vlans, host_vlans,
                stack_roots, host_links, self.topo.dpid_peer_links(dpid), self.port_maps)

        return yaml.dump(config, default_flow_style=False)