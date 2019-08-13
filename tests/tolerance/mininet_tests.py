#!/usr/bin/env python3

import binascii
import collections
import copy
import itertools
import ipaddress
import json
import os
import random
import re
import shutil
import socket
import threading
import time
import unittest
import networkx
import sys

from http.server import SimpleHTTPRequestHandler
from http.server import HTTPServer

import scapy.all

import yaml # pytype: disable=pyi-error

from mininet.log import error
from mininet.util import pmonitor

from clib import mininet_test_base
from clib import mininet_test_util
from clib import mininet_test_topo

from clib.mininet_test_base import PEER_BGP_AS, IPV4_ETH, IPV6_ETH

class TopologyGenerator():
    """
    Generates DP links
    TODO: Add offsets to dpid_indices to enable component-wise generation of stack links
    """

    #def __init__(self):
    #    self.seed = random.randrange(sys.maxsize)
    #    self.rng = random.Random(self.seed)
    
    @staticmethod
    def ring_links(dp_num):
        dp_links = []
        for dpid in range(dp_num):
            currdp = dpid
            nextdp = dpid + 1 if currdp != dp_num else 0
            dp_links.append((currdp, nextdp, 1))
        return dp_links

    @staticmethod
    def mesh_links(dp_num):
        dp_links = []
        for src_dpid in range(dp_num):
            for dst_dpid in range(src_dpid+1, dp_num):
                dp_links.append((src_dpid, dst_dpid, 1))
        return dp_links

    @staticmethod
    def k33():
        # DP_NUM = 6
        dp_links = [
            (0, 3, 1),
            (0, 4, 1),
            (0, 5, 1),
            (1, 3, 1),
            (1, 4, 1),
            (1, 5, 1),
            (2, 3, 1),
            (2, 4, 1),
            (2, 5, 1)
        ]
        return dp_links

    @staticmethod
    def peterson():
        # DP_NUM = 10
        dp_links = [
            (0, 1, 1),
            (0, 5, 1),
            (0, 4, 1),
            (1, 6, 1),
            (1, 2, 1),
            (2, 7, 1),
            (2, 3, 1),
            (3, 8, 1),
            (3, 4, 1),
            (4, 9, 1),
            (5, 7, 1),
            (5, 8, 1),
            (6, 9, 1),
            (6, 8, 1),
            (7, 9, 1)
        ]
        return dp_links

    @staticmethod
    def star(dp_num):
        dp_links = []
        for dpid in range(1, dp_num):
            dp_links.append((0, dpid, 1))
        return dp_links

    @staticmethod
    def random_connect(dp_num):
        seed = random.randrange(sys.maxsize)
        rng = random.Random(seed)
        dp_links = []
        for _ in range(1, 3):
            for dpid in range(dp_num):
                dstdp = rng.randrange(dp_num)
                while dstdp == dpid:
                    dstdp = rng.randrange(dp_num)
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
        return dp_links


class MetricHolder():
    """
    TODO: REPLACE WITH A PYTHON LIBRARY
    Calculates the metrics used to determine the quality of a network topology
    Types:
        Connectivity:
            Total number of host/switch and controllers connected to the main topology.
        Distance:
            Number of nexthops between host end-points.
        Reliability:
            Metric determined by the number of host end-points that can communicate.
    """
    dpids = None                   # Identified by ID
    hosts = None                   # Identified by IP
    dp_graph = None                # DP connectivity graph
    host_connectivity = None       # Reliability information
    host_connectivity_graph = None # Reliability graph
    tear_downs = None

    curr_metric = 0                # Current tear-down time/instance

    def __init__(self, dpids=None, dp_links=None):
        self.dpids = dpids
        self.hosts = []
        self.dp_graph = networkx.Graph()
        self.host_connectivity = []
        self.host_connectivity.append({})
        #self.host_connectivity_graph = networkx.DiGraph()
        self.tear_downs = ['Initial']
        for dpid in dpids:
            self.dp_graph.add_node(dpid)
        for link in dp_links:
            for _ in range(link[2]):
                self.dp_graph.add_edge(link[0], link[1])

    def add_host_connectivity(self, src, dst, packet_loss):
        """Adds the host connectivity information"""
        if src not in self.hosts:
            self.hosts.append(src)
        if dst not in self.hosts:
            self.hosts.append(dst)
        if src not in self.host_connectivity[self.curr_metric]:
            self.host_connectivity[self.curr_metric][src] = []
        self.host_connectivity[self.curr_metric][src].append({
            'dst': dst,
            'loss': packet_loss
        })

    def tear_down_event(self, name, **kwargs):
        """Adds the tear down event information"""
        self.tear_downs.append(name)
        self.curr_metric += 1
        self.host_connectivity.append({})

    def stop_running(self):
        """Determines whether we have learnt enough to stop testing"""
        # TODO: Use smarts to calculate stopping point (> 50% network outage??)
        return True

    def __str__(self):
        return yaml.dump(self.host_connectivity, default_flow_style=False)

class FaucetTest(mininet_test_base.FaucetTestBase):
    pass

class FaucetFaultToleranceBaseTest(FaucetTest):

    NUM_DPS = 2
    N_TAGGED = 0
    N_UNTAGGED = 0

    NETPREFIX = 24
    GROUP_TABLE = False

    topology_generator = None
    metric_holder = None
    host_information = None

    seed = 0
    rng = None

    def build_net(self, n_dps=0, n_vlans=0, n_hosts=0, dp_links=None,
                  hw_dpid=None):
        """
        Use the TopologyGenerator to generate the YAML configuration and create the network

        Args:
            n_dps:   Number of DPs
            n_vlans: Number of VLANs
            n_hosts: Number of hosts on each DP on each VLAN
            dplinks: The stack links
        """
        self.NUM_DPS = n_dps
        self.N_UNTAGGED = n_vlans * n_hosts
        self.dpids = [str(self.rand_dpid()) for _ in range(n_dps)]
        self.dpids[0] = self.dpid
        self.topo = mininet_test_topo.FaucetStackTopo(
            self.OVS_TYPE,
            self.ports_sock,
            test_name=self._test_name(),
            dpids=self.dpids,
            n_hosts=(n_vlans*n_hosts),
            dp_links=dp_links,
            hw_dpid=self.hw_dpid,
            switch_map=self.switch_map,
            port_order=self.port_order
        )
        self.port_maps = {dpid: self.create_port_map(dpid) for dpid in self.dpids}
        self.port_map = self.port_maps[self.dpid]
        self.CONFIG = self.get_config(
            dpids=self.dpids,
            n_vlans=n_vlans,
            n_hosts=n_hosts,
            dp_links=dp_links,
            hw_dpid=hw_dpid,
            hardware=self.hardware,
            ofchannel_log=self.debug_log_path
        )
        self.n_dps = n_dps
        self.n_vlans = n_vlans
        self.n_hosts = n_hosts
        self.dp_links = dp_links
        self.metric_holder = MetricHolder(self.dpids, self.dp_links)
        self.seed = random.randrange(sys.maxsize)
        self.rng = random.Random(self.seed)

    def get_config(self, dpids=None, n_vlans=0, n_hosts=0, dp_links=None,
                   hw_dpid=None, hardware=None, ofchannel_log=None):
        def dp_name(i):
            return 'faucet-%i' % (i+1)
        def vlan_name(i):
            return 'vlan-%i' % (i+1)
        def vlan_vid(i):
            return (i+1) * 100
        def add_vlans():
            vlans_config = {}
            for i in range(n_vlans):
                vlans_config[vlan_name(i)] = {
                    'description': 'untagged',
                    'vid': vlan_vid(i)
                }
            return vlans_config
        def add_dp(i, dpid):
            dp_config = {
                'dp_id': int(dpid),
                'hardware': hardware if dpid == hw_dpid else 'Open vSwitch',
                'table_sizes': {'flood': 64},
                'ofchannel_log': ofchannel_log + str(i) if ofchannel_log else None,
                'interfaces': {},
                'group_table': self.GROUP_TABLE,
            }
            interfaces_config = {}
            index = 1
            for i in range(n_vlans):
                for j in range(n_hosts):
                    port = self.port_maps[dpid]['port_%d' % index]
                    interfaces_config[port] = {
                        'native_vlan': vlan_vid(i),
                    }
                    index += 1
            for link in self.topo.dpid_peer_links(dpid):
                port, peer_dpid, peer_port = link.port, link.peer_dpid, link.peer_port
                interfaces_config[port] = {}
                interfaces_config[port].update(
                    {
                        'stack': {
                            'dp': dp_name(dpids.index(peer_dpid)),
                            'port': peer_port
                        }
                    }
                )
            dp_config['interfaces'] = interfaces_config
            return dp_config
        config = {'version': 2}
        config['vlans'] = add_vlans()
        config['dps'] = {}
        for i, dpid in enumerate(dpids):
            config['dps'][dp_name(i)] = add_dp(i, dpid)
        return yaml.dump(config, default_flow_style=False)

    def get_ip(self, host_index, vlan_index):
        """ """
        return '10.%u00.0.%u' % (vlan_index, host_index)

    def pairwise_connectivity(self, src_host, dst_ip):
        """Returns percentage of packets lost between two hosts"""
        ping_cmd = 'ping -c1 -I%s %s' % (src_host.defaultIntf(), dst_ip)
        data = src_host.cmd(ping_cmd)
        print('%s' % data)
        for _ in range(3):
            data_list = data.split('\n')
            result = re.search('(?<=received, ).*?(?=% packet loss)', data_list[-2])
            duplicates = re.search('(?<=duplicates, ).*?(?=% packet loss)', data_list[-2])
            errors = re.search('(?<=errors, ).*?(?=% packet loss)', data_list[-2])
            if errors and int(errors.group(0)) == 0:
                print('errors')
                return int(errors.group(0))
            if duplicates and int(duplicates.group(0)) == 0:
                print('duplicates')
                return int(duplicates.group(0))
            if result and int(result.group(0)) == 0:
                print('results')
                return int(result.group(0))
        return 100

    def calculate_connectivity(self):
        """Ping between each set of host pairs to calculate host connectivity"""
        for src_hosts in self.host_information.values():
            for dst_hosts in self.host_information.values():
                for src in src_hosts:
                    for dst in dst_hosts:
                        if src != dst:
                            #self.require_host_learned(src['host'])
                            #self.require_host_learned(dst['host'])
                            result = self.pairwise_connectivity(src['host'], dst['ip'].ip)
                            self.metric_holder.add_host_connectivity(str(src['ip'].ip), str(dst['ip'].ip), result)

    def create_tear_down_event(self):
        """Randomly (TODO: Smartly) choose a switch/link/controller to tear down"""
        event_options = ['link', 'switch', 'controller']
        event = self.rng.randrange(3)
        # TODO: Give percentage chances to take down a link/controller/switch
        #           with values weighted towards the link then controller then swithc
        #           also probably want to have events to reconnect them if possible
        #if event == 0:
        #    # SWITCH DOWN
        #    self.net.switches[i].cmd('%s del-controller %s' % (self.VSCTL, switch.name))
        #elif event == 1:
        #    # LINK DOWN
        #elif event == 2:
        #    # CONTROLLER DOWN
        #      _ofctl(req, params)
        #       self._stop_net()???
        #       tearDown

        # Start with the link case
        # Pick a random link
        index = self.rng.randrange(len(self.dp_links))
        dplink = self.dp_links[index]
        srcdp = self.dpids[dplink[0]]
        dstdp = self.dpids[dplink[1]]
        name = '[%s-%s]' % (srcdp, dstdp)
        for link in self.topo.dpid_peer_links(srcdp):
            port, peer_dpid, peer_port = link.port, link.peer_dpid, link.peer_port
            status = self.stack_port_status(srcdp, 'faucet-%u' % self.dpids.index(srcdp) + 1, port)
            if peer_dpid == dstdp and status == 3:
                self.set_port_down(port, srcdp)
                self.metric_holder.tear_down_event(name)
                break
        # TODO: When no link could be broken

    def network_function(self):
        """ 
        Test the network by slowly tearing it down in several different ways
        """
        self.verify_no_cable_errors()
        self.verify_stack_up()
        self.host_information = {}
        for i in range(self.n_vlans):
            self.host_information[i] = []
        for i, host in enumerate(self.hosts_name_ordered()):
            vlan = i % self.n_vlans
            ip = self.get_ip(i + 1, vlan + 1)
            self.host_information[vlan].append({
                'host': host,
                'ip': ipaddress.ip_interface(ip)
            })
            host.setIP(ip, prefixLen=self.NETPREFIX)
        self.calculate_connectivity()
        # TEAR DOWN THE NETWORK SLOWLY & RANDOMLY SEVERAL TIMES UNTIL DESIRED BREAKING POINT

    def non_host_links(self, dpid):
        return self.topo.dpid_peer_links(dpid)
    def verify_no_cable_errors(self):
        i = 0
        for dpid in self.dpids:
            i += 1
            labels = {'dp_id': '0x%x' % int(dpid), 'dp_name': 'faucet-%u' % i}
            self.assertEqual(
                0, self.scrape_prometheus_var(
                    var='stack_cabling_errors_total', labels=labels, default=None))
            self.assertGreater(
                self.scrape_prometheus_var(
                    var='stack_probes_received_total', labels=labels), 0)
    def stack_port_status(self, dpid, dp_name, port_no):
        labels = self.port_labels(port_no)
        labels.update({'dp_id': '0x%x' % int(dpid), 'dp_name': dp_name})
        return self.scrape_prometheus_var(
            'port_stack_state', labels=labels,
            default=None, dpid=False)
    def wait_for_stack_port_status(self, dpid, dp_name, port_no, status, timeout=25):
        labels = self.port_labels(port_no)
        labels.update({'dp_id': '0x%x' % int(dpid), 'dp_name': dp_name})
        if not self.wait_for_prometheus_var(
                'port_stack_state', status, labels=labels,
                default=None, dpid=False, timeout=timeout):
            self.fail('did not get expected dpid %x port %u port_stack_state %u' % (
                int(dpid), port_no, status))
    def verify_stack_up(self, prop=1.0, timeout=25):
        for _ in range(timeout):
            links = 0
            links_up = 0
            for i, dpid in enumerate(self.dpids, start=1):
                dp_name = 'faucet-%u' % i
                for link in self.non_host_links(dpid):
                    status = self.stack_port_status(dpid, dp_name, link.port)
                    links += 1
                    if status == 3:  # up
                        links_up += 1
            prop_up = links_up / links
            if prop_up >= prop:
                return
            time.sleep(1)
        self.fail('not enough links up: %f / %f' % (links_up, links))


class FaucetFaultToleranceNetworkTest(FaucetFaultToleranceBaseTest):

    def setUp(self):
        super(FaucetFaultToleranceNetworkTest, self).setUp()
        n_dps = 3
        n_vlans = 1
        n_hosts = 1
        dp_links = TopologyGenerator.ring_links(n_dps)
        self.build_net(n_dps, n_vlans, n_hosts, dp_links)
        self.start_net()

    def test_ring_links(self):
        self.network_function()
        self.assertFalse(True, '\n%s' % self.metric_holder)