
"""
Inputs:
    - acls
        auto-generated: []
            The content that will always be generated
        depend-generated: []
            The config content that will be generated if other options invoke it
        not-specified-generated: []
            The config content that will be generated if it does not exist in options
        - acls
            dict
            The ACL
            {1: [{'rule': {...}}, {'rule': {...}}]}
    - dps
        auto-generated: ['name', 'dp_id', 'interfaces', 'ofchannel_log']
            The content that will always be generated
        depend-generated: ['stack']
            The config content that will be generated if other options invoke it
        not-specified-generated: ['hardware']
            The config content that will be generated if it does not exist in options
        - topology
            networkx MultiGraph
            The network topology to determine the links & DPs
            networkx.MultiGraph(networkx.generators.cycle_graph(5))
        - options
            dict
            Additional specified options for each DP by DP index
            {0: {'drop_spoofed_faucet_mac': True}}
    - routers
        auto-generated: ['vlans']
            The content that will always be generated
        depend-generated: []
            The config content that will be generated if other options invoke it
        not-specified-generated: []
            The config content that will be generated if it does not exist in options
        - router list
            list
            The routers to generate, a list of VLAN indices for each router
            [[1, 2], [3, 4]]
        - options
            dict
            Additional specified options for each router by router index
            {0: {'bgp': {}}}
    - vlans
        auto-generated: ['name', 'vid', 'description']
            The content that will always be generated
        depend-generated: ['faucet_vips', 'faucet_mac']
            The config content that will be generated if other options invoke it
        not-specified-generated: []
            The config content that will be generated if it does not exist in options
        - number of vlans
            int
            The number of VLANs to generate
            5
        - options
            dict
            Additional specified options for each vlan by vlan index
            {0: {'max_hosts': 255}}

Returns:
    Faucet CONFIG: The generated Faucet config
    additonal information structures
"""

import random
import networkx

class ConfigGeneratorError(Exception):
    pass

class BaseGenerator:

    auto_generated: {}
    depend_generated = {}
    not_specified_generated = {}

    options = None

    def base_iterator(self):
        raise NotImplementedError('Base class does not implement base_iterator function')

    def create_config(self):
        total_config = {}
        for i in self.base_iterator():
            sub_config = {}
            # Generate the auto-generated DP config
            for key, func in self.auto_generated.items():
                if key != 'name':
                    sub_config[key] = func(self, i)
            # Attempt to generate additional config options
            for key, func in self.depend_generated.items():
                depend_conf = func(self, i)
                if depend_conf:
                    sub_config[key] = depend_conf
            # Add the options to the DP config
            if self.options and i in self.options:
                for key, value in self.options[i].items():
                    sub_config[key] = value
            # Generate the not-specified DP config
            for key, func in self.not_specified_generated.items():
                if key not in sub_config:
                    sub_config[key] = func(self, i)
            # Add config to the dps config
            vlan_name = self.auto_generated['name'](self, i)
            total_config[vlan_name] = sub_config
        return total_config


class PortMapper:

    topology = None
    hosts = None
    port_order = None
    start_port = None

    dp_port_map = None

    def __init__(self, topology, hosts, port_order, start_port):
        self.topology = topology
        self.hosts = hosts
        self.port_order = port_order
        self.start_port = start_port
        self.dp_port_map = self.generate_dp_port_map()
    
    def generate_dp_port_map(self):
        # Reserve a port for each 


class Hosts(BaseGenerator):

    def generate_host_name(self, i):
        return 'H%s' % i

    def generate_host_ip(self, i):
        # TODO: Resolve host vlan
        return '10.%s.0.%s' % (i+1, i+1)

    def generate_host_mac(self, i):
        return '00:00:00:00:00:%02x' % (i+1)

    def generate_host_links(self, i):
        # TODO: Would like to resolve for DP name & DP port
        return self.hosts[i]

    auto_generated = {'name': generate_host_name, 'ip': generate_host_ip, 'mac': generate_host_mac, 'links': generate_host_links}
    depend_generated = {}
    not_specified_generated = {}

    def __init__(self, hosts, options):
        self.hosts = hosts
        self.options = options
    
    def base_iterator(self):
        return self.hosts


class DPS(BaseGenerator):

    topology = None

    def generate_dp_name(self, i):
        return 's%s' % (i+1)

    def generate_dpid(self, i):
        reserved_range = 100
        dpid = random.randint(1, (2**32 - reserved_range)) + reserved_range
        return int(str(dpid))

    def generate_interfaces(self, i):
        interface_config = {}

        def generate_port_num(i):
            # TODO: Need port numbers to be proper
            return (i+1)
        
        def generate_host_interface(i):

            def generate_host_name():
                return 'H'

            host_interface = {}
            return host_interface

        def generate_link_interface(i, j, n):

            def generate_link_name(link_type):
                return '%s #%s link %s - %s' % (
                    link_type, n+1, self.generate_dp_name(i), self.generate_dp_name(j))

            link_interface = {}
            link_dict = self.topology[i][j][n]
            if 'vlans' in link_dict:
                value = link_dict['vlans']
                if isinstance(value, list):
                    # Tagged link
                    link_interface['name'] = generate_link_name('trunk')
                    link_interface['tagged_vlans'] = value
                elif value is not None:
                    # Untagged link
                    link_interface['name'] = generate_link_name('native_vlan')
                    link_interface['native_vlan'] = value
                elif value is None:
                    # Stack link
                    # TODO: Need to properly generate destination port number
                    link_interface['name'] = generate_link_name('stack')
                    link_interface['stack'] = {'dp': self.generate_dp_name(j), 'port': 'something'}
            else:
                # Default to stack link
                # TODO: Need to properly generate destination port number
                link_interface['name'] = generate_link_name('stack')
                link_interface['stack'] = {'dp': self.generate_dp_name(j), 'port': 'something'}
            return link_interface

        port_index = 0
        if i in self.topology:
            for j in self.topology[i]:
                for n in self.topology[i][j]:
                    interface_config[generate_port_num(port_index)] = generate_link_interface(i, j, n)
                    port_index += 1
        for host, links in self.hosts:
            for _ in range(links.count(i)):
                interface_config[generate_port_num(port_index)] = generate_host_interface()
                port_index += 1
        return interface_config

    auto_generated = {'name': generate_dp_name, 'dp_id': generate_dpid, 'interfaces': generate_interfaces}

    def generate_stack(self, i):
        if i == 0 and i in self.topology:
            # Links from i to other DPs j
            for j, links in self.topology[i].items():
                # One or more links from i to j
                for link in links.values():
                    # Does link contain VLAN VIDs
                    if 'vlans' in link:
                        if link['vlans'] is None:
                            return {'priority': 1}
                    else:
                        # Link information not specified, so default to stacked link
                        return {'priority': 1}
        return None

    depend_generated = {'stack': generate_stack}

    def generate_hardware(self, i):
        return 'Open vSwitch'

    not_specified_generated = {'hardware': generate_hardware}

    def __init__(self, topology, hosts, options):
        if not isinstance(topology, networkx.MultiGraph):
            raise ConfigGeneratorError('Provided network topology was not a multi-graph')
        self.topology = topology
        self.hosts = hosts
        self.options = options

    def base_iterator(self):
        return self.topology.nodes()


class VLANS(BaseGenerator):

    num_vlans = None
    
    def generate_name(self, i):
        return 'vlan-%i' % (i+1)

    def generate_vid(self, i):
        return (i+1) * 100

    def generate_description(self, i):
        return 'VLAN %s' % (i+1)

    auto_generated = {'name': generate_name, 'vid': generate_vid, 'description': generate_description}

    def generate_faucet_vips(self, i):
        return '10.%s.0.254' % (i+1)

    def generate_faucet_mac(self, i):
        return ('%02x' % (i+1)) + ((':%02x' % (i+1)) * 5)

    depend_generated = {'faucet_vips': generate_faucet_vips, 'faucet_mac': generate_faucet_mac}
    not_specified_generated = {}
    
    def __init__(self, num_vlans, options):
        self.num_vlans = num_vlans
        self.options = options   

    def base_iterator(self):
        return range(self.num_vlans)


class ConfigGenerator(BaseGenerator):

    def generate_name(self, i):
        return 'CONFIG #%s' % (i+1)

    def generate_vlans(self, i):
        return self.vlans_generator.create_config()

    def generate_dps(self, i):
        return self.dps_generator.create_config()

    auto_generated = {'name': generate_name, 'vlans': generate_vlans, 'dps': generate_dps}
    depend_generated = {}
    not_specified_generated = {}

    def __init__(self, vlans_generator, dps_generator):
        self.vlans_generator = vlans_generator
        self.dps_generator = dps_generator

    def base_iterator(self):
        return [0]


if __name__ == '__main__':
    import pprint

    mg = networkx.MultiGraph(networkx.generators.cycle_graph(5))
    mg.edges[0, 1, 0]['vlans'] = 4
    mg.edges[1, 2, 0]['vlans'] = [2, 3]
    mg.edges[2, 3, 0]['vlans'] = None
    dg = DPS(mg, {})
    vg = VLANS(5, {})

    cg = ConfigGenerator(vg, dg)
    pprint.pprint(cg.create_config())

    host_config = Hosts({0: [1, 2], 1: [2, 2]}, {})
    pprint.pprint(host_config.create_config())