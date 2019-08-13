import ipaddress
import os
import yaml
import pprint
import subprocess
import sys
import re
import time
import random
import networkx
import matplotlib.pyplot as plt
from random import shuffle

class Port():
    """
    Basic port structure
    
    port_num:
    dp:
    """

    def __init__(self, port_num, dp):
        self.port_num = port_num
        self.dp = dp


class Host(Port):
    """
    Data structure containing host information, inherits from port
    
    vlan:
    ipaddress:
    """

    def __init__(self, port_num, dp, vlan, _id):
        super().__init__(port_num, dp)
        self.name = Host.get_name(vlan.id, _id)
        self.vlan = vlan
        self.gw = Host.get_gw(vlan.id, _id)
        self.ip = Host.get_ip(vlan.id, _id)

    def get_yaml(self):
        return """
                name: %s
                native_vlan: %s""" % (self.name, self.vlan.name)

    @staticmethod
    def get_gw(vid, _id):
        return '10.%s.0.%s/24' % (vid, _id)

    @staticmethod
    def get_ip(vid, _id):
        return '10.%s.0.%s' % (vid, _id)

    @staticmethod
    def get_name(vid, _id):
        return 'H%s-%s' % (vid, _id)


class StackLink(Port):
    """
    Data structure containing a stack link, inherits from port
    
    dst_port:
    """

    def __init__(self, port_num, dp, dst_port, dst_dp, _id):
        super().__init__(port_num, dp)
        self.dst_port = dst_port
        self.dst_dp = dst_dp
        self.name = StackLink.get_name(dp.id, dst_dp.id, _id)
        self.id = _id
        self.patch = '%s-%s[%s]' % (self.dp.id, self.dst_dp.id, self.id)
        self.peer_patch = '%s-%s[%s]' % (self.dst_dp.id, self.dp.id, self.id)

    def get_yaml(self):
        return """
                name: %s
                stack: {dp: %s, port: %s}""" % (self.name, self.dst_dp.name, self.dst_port + 1)

    @staticmethod
    def get_name(src_dpid, dst_dpid, _id):
        return 'SL%s-%s[%s]' % (src_dpid, dst_dpid, _id)


class VLAN():
    """
    Contains VLAN information, VIP/MAC
    
    id:
    vip:
    mac:
    """

    def __init__(self, vid):
        self.id = vid
        self.name = VLAN.get_name(vid)
        self.vip = VLAN.get_vip(vid)
        self.mac = VLAN.get_mac(int(vid / 100))

    def get_yaml(self):
        return """
    %s:
        vid: %s
        faucet_vips: [%s]
        faucet_mac: %s""" % (self.name, self.id, self.vip, self.mac)

    @staticmethod
    def get_name(vid):
        return 'VLAN%s' % vid

    @staticmethod
    def get_vip(vid):
        return '10.%s.0.254/24' % vid
    
    @staticmethod
    def get_mac(vid):
        return '00:00:00:00:00:%s%s' % (vid, vid)


class DP():
    """
    Contains switch information, ports/dp_id
    
    id:
    ports:
    """

    def __init__(self, dp_id):
        self.id = dp_id
        self.name = DP.get_name(dp_id)
        self.root_priority = -1
        self.ports = []

    def add_host(self, vlan, _id):
        self.ports.append(Host(len(self.ports), self, vlan, _id))

    def add_link(self, src_dp, dst_dp, time):
        src_port_num = len(src_dp.ports)
        dst_port_num = len(dst_dp.ports)
        src_dp.ports.append(StackLink(src_port_num, src_dp, dst_port_num, dst_dp, time))
        dst_dp.ports.append(StackLink(dst_port_num, dst_dp, src_port_num, src_dp, time))

    def get_port_num(self, port):
        return self.ports.index(port)

    def get_interface_yaml(self):
        interface_yaml = """
        interfaces:"""
        for port in self.ports:
            interface_yaml += """
            %s:%s""" % (port.port_num + 1, port.get_yaml())
        return interface_yaml

    def get_yaml(self):
        if self.root_priority >= 0:
            return """
    %s:
        dp_id: %s
        stack: {priority: %s}%s""" % (self.name, self.id, self.root_priority, self.get_interface_yaml())
        else:
            return """
    %s:
        dp_id: %s%s""" % (self.name, self.id, self.get_interface_yaml())

    @staticmethod
    def get_name(dp_id):
        return 'sw%s' % dp_id

class ConfigGenerator():
    """Parses data structures and generates a configuration YAML file"""

    vlans = []
    dps = []
    routers = []
    save_folder = ''
    host_pairs = []
    force_cleanup = True
    config_diff = True
    yaml_config = ''

    def __init__(self, vlan_num, dp_num, dp_roots, dp_hosts, dp_links, name):
        generated_name = 'VLAN%s-DP%s-H%sR' % (vlan_num, dp_num, dp_hosts)
        if name == '':
            for root in dp_roots:
                generated_name += '%s%s' % (root[0], root[1])
            generated_name += 'L'
            for link in dp_links:
                generated_name += '%s%s%s' % (link[0], link[1], link[2])
        else:
            generated_name = '%s-DPs%s-Hs%s-R%s' % (name, dp_num, dp_hosts, dp_roots[0][0])
        self.save_folder = 'graphs/%s' % generated_name
        self.generate_structures(vlan_num, dp_num, dp_roots, dp_hosts, dp_links)
        self.generate_yaml()
        self.host_pairs = []

    def generate_yaml(self):
        yaml_config = "vlans:"
        for vlan in self.vlans:
            yaml_config += vlan.get_yaml()
        yaml_config += "\ndps:"
        for dp in self.dps:
            yaml_config += dp.get_yaml()
        self.yaml_config = yaml_config
        if not os.path.isdir('%s/' % self.save_folder):
            os.makedirs('%s/' % self.save_folder)
        if os.path.isfile('%s/faucet.yaml' % self.save_folder):
            print(self.yaml_config, file=open('faucet.yaml.check', 'w'))
            self.config_diff = subprocess.getoutput('diff faucet.yaml.check faucet.yaml')
            if self.config_diff:
                print(self.yaml_config, file=open('%s/faucet.yaml' % self.save_folder, 'w'))
                print(self.yaml_config, file=open('faucet.yaml', 'w'))
        else:
            self.config_diff = True
            print(self.yaml_config, file=open('%s/faucet.yaml' % self.save_folder, 'w'))
            print(self.yaml_config, file=open('faucet.yaml', 'w'))

    def generate_structures(self, vlan_num, dp_num, dp_roots, dp_hosts, dp_links):
        vlans = []
        for v in range(vlan_num):
            vlans.append(VLAN((v+1) * 100))
        dps = []
        for dpid in range(dp_num):
            dps.append(DP(dpid+1))
            for vlan in vlans:
                for host in range(dp_hosts):
                    dps[dpid].add_host(vlan, (dpid-1) * dp_hosts + (host + 2))
        for link in dp_links:
            src_dpid, dst_dpid, times = link
            src_dp = dps[src_dpid-1]
            dst_dp = dps[dst_dpid-1]
            for time in range(1, times+1):
                src_dp.add_link(src_dp, dst_dp, time)
        for root in dp_roots:
            dpid, priority = root
            dps[dpid - 1].root_priority = priority
        self.vlans = vlans
        self.dps = dps
        self.routers = []

    def create_network(self):
        if self.config_diff or self.force_cleanup:
            print('Generating network')
            subprocess.call('./cleanup.sh', shell=True)
            for dp in self.dps:
                subprocess.call('./add_br.sh %s %s > /dev/null' % (dp.id, dp.id), shell=True)
                for port in dp.ports:
                    if isinstance(port, StackLink):
                        subprocess.call('./create_stack_link.sh %s %s %s %s > /dev/null' % (
                            dp.id, port.patch, port.peer_patch, port.port_num + 1), shell=True)
                    elif isinstance(port, Host):
                        subprocess.call('./create_ns.sh %s %s > /dev/null' % (
                            port.name, port.gw), shell=True)
                        subprocess.call('./set_br_interface.sh %s %s %s > /dev/null' % (
                            dp.id, port.name, port.port_num + 1), shell=True)
                        subprocess.call('./as_ns.sh %s ip route add default via %s dev veth0 > /dev/null' % (
                            port.name, port.vlan.vip[0:-3]), shell=True)

    def startup_faucet(self):
        docker_exists = subprocess.getoutput('sudo docker ps -a | grep faucet/faucet',)
        if docker_exists:
            print('Restart Faucet')
            subprocess.call('sudo docker restart faucet', shell=True)
        else:
            print('Starting Up Faucet')
            subprocess.call('./run_docker.sh faucet.yaml', shell=True)

    def ping_network(self):
        ping_count = 5
        hosts_by_vlan = {}
        for vlan in self.vlans:
            hosts_by_vlan[vlan] = []
        for dp in self.dps:
            for port in dp.ports:
                if isinstance(port, Host):
                    hosts_by_vlan[port.vlan].append(port)
        for src_vlan, src_hosts in hosts_by_vlan.items():
            for dst_vlan, dst_hosts in hosts_by_vlan.items():
                if src_vlan is not dst_vlan: # ?????? WHY DID I DO THIS????
                    continue
                for shost in src_hosts:
                    for dhost in dst_hosts:
                        if shost is dhost:
                            continue
                        data = subprocess.getoutput('./as_ns.sh %s ping -c%u %s' % (
                            shost.name, ping_count, dhost.ip))
                        data_list = data.split('\n')
                        result = re.search('(?<=received, ).*?(?=% packet loss)', data_list[-2])
                        duplicates = re.search('(?<=duplicates, ).*?(?=% packet loss)', data_list[-2])
                        errors = re.search('(?<=errors, ).*?(?=% packet loss)', data_list[-2])
                        # TODO: Create graph drawing line based on inverse percentage packet loss
                        if duplicates or result.group(0) == '0':
                            self.host_pairs.append((shost.name, dhost.name))
                        if result:
                            value = result.group(0)
                            if value != '0' and not duplicates:
                                print('%s (%s) -> %s (%s) = %s%%' % (
                                    shost.name, shost.ip, dhost.name, dhost.ip, value
                                ))

    # TODO: Slowly take apart the network and test pings

    def draw_graph(self):
        dp_graph = networkx.Graph()
        host_graph = networkx.DiGraph()
        hosts = []
        dps = []
        stacklinks = []
        host_dp_links = []
        root_colour_map = []
        for dp in self.dps:
            dps.append(dp.name)
            if dp.root_priority != -1:
                root_colour_map.append('red')
            else:
                root_colour_map.append('blue')
            for port in dp.ports:
                if isinstance(port, Host):
                    hosts.append(port.name)
                    host_dp_links.append((dp.name, port.name))
                elif isinstance(port, StackLink):
                    stacklinks.append((port.dp.name, port.dst_dp.name))
        for node in dps:
            dp_graph.add_node(node)
        for edge in stacklinks:
            dp_graph.add_edge(*edge)
        for node in hosts:
            host_graph.add_node(node)
        for edge in self.host_pairs:
            host_graph.add_edge(*edge)
        fig = plt.figure(1)
        networkx.draw(dp_graph, node_color=root_colour_map, pos=networkx.spring_layout(dp_graph,k=0.15,iterations=20), with_labels=True)
        plt.savefig('%s/dp_graph.svg' % self.save_folder, dpi=fig.dpi)
        fig = plt.figure(2)
        networkx.draw(host_graph, pos=networkx.spring_layout(host_graph,k=0.15,iterations=20), with_labels=True)
        plt.savefig('%s/host_graph.svg' % self.save_folder, dpi=fig.dpi)

def ring_links(dp_num):
    dp_links = []
    for dpid in range(1, dp_num+1):
        currdp = dpid
        nextdp = dpid + 1 if currdp != dp_num else 1
        dp_links.append((currdp, nextdp, 1))
    return (dp_links, 'ring')

def mesh_links(dp_num):
    dp_links = []
    for src_dpid in range(1, dp_num+1):
        for dst_dpid in range(src_dpid+1, dp_num+1):
            dp_links.append((src_dpid, dst_dpid, 1))
    return (dp_links, 'mesh')

def k33(dp_num):
    # dp_num = 6
    dp_links = [
        (1, 4, 1),
        (1, 5, 1),
        (1, 6, 1),
        (2, 4, 1),
        (2, 5, 1),
        (2, 6, 1),
        (3, 4, 1),
        (3, 5, 1),
        (3, 6, 1)
    ]
    return (dp_links, 'k33')

def peterson(dp_num):
    # dp_num = 10
    dp_links = [
        (1, 2, 1),
        (1, 6, 1),
        (1, 5, 1),
        (2, 7, 1),
        (2, 3, 1),
        (3, 8, 1),
        (3, 4, 1),
        (4, 9, 1),
        (4, 5, 1),
        (5, 10, 1),
        (6, 8, 1),
        (6, 9, 1),
        (7, 10, 1),
        (7, 9, 1),
        (8, 10, 1)
    ]
    return (dp_links, 'peterson')

def star(dp_num):
    dp_links = []
    for dpid in range(2, dp_num+1):
        dp_links.append((1, dpid, 1))
    return (dp_links, 'star')

def random_connect(dp_num):
    seed = random.randrange(sys.maxsize)
    print('seed: %u' % seed)
    rng = random.Random(seed)
    dp_links = []
    for _ in range(1, 3):
        for dpid in range(1, dp_num+1):
            dstdp = rng.randrange(dp_num) + 1
            while dstdp == dpid:
                dstdp = rng.randrange(dp_num) + 1
            link = (dpid, dstdp, 1)
            exists = False
            for i in range(len(dp_links)):
                dplink = dp_links[i]
                if (dplink[0] == link[0] and dplink[1] == link[1]) or (
                    dplink[1] == link[0] and dplink[0] == link[1]):
                    dp_links[i] = (dpid, dstdp, dplink[2] + 1)
                    exists = True
            if not exists:
                dp_links.append(link)
    return (dp_links, 'random%s' % seed)

vlan_num = 1
dp_num = 6
stack_root = [(random.randrange(dp_num) + 1, 1)]
dp_hosts = 1
dp_links, name = random_connect(dp_num)
print('Creating Config')
cg = ConfigGenerator(vlan_num, dp_num, stack_root, dp_hosts, dp_links, name)
cg.create_network()
cg.startup_faucet()
time.sleep(20)
print('Testing Network')
cg.ping_network()
print('Drawing Graph')
cg.draw_graph()