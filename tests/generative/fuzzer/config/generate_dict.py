
import yaml

import networkx
from networkx.generators.atlas import graph_atlas_g

from mininet.topo import Topo  # pylint: disable=unused-import

from clib.config_generator import FaucetFakeOFTopoGenerator

from faucet.acls import ACL
from faucet.meter import Meter
from faucet.port import Port
from faucet.router import Router
from faucet.dp import DP
from faucet.vlan import VLAN
from faucet.config_parser import V2_TOP_CONFS

# Generate YAML config dictionary via obtaining possible variables from Faucet CONF objects

config_fn = 'config.dict'
config_file = open(config_fn, 'ra')

# Read set of bogus values already currently in the config.dict file
bogus_values = []
for value in config_file.readlines():
    # Remove quotes and \n from bogus value to get the true bogus value
    bogus_values.append(value[1:2])

# Make sure to add head values into the dictionary
for value in V2_TOP_CONFS:
    for bogus in bogus_values:
        to_write = '%s%s' % (value, bogus)
        rev_to_write = '%s%s' % (bogus, value)
        if to_write in bogus_values or rev_to_write in bogus_values or value in bogus_values:
            continue
        config_file.write('"%s"' % to_write)
        config_file.write('"%s"' % rev_to_write)

# Find CONF objects config file options
for conf_obj in [ACL, Meter, Port, Router, DP]:
    for value in conf_obj.defaults.keys():
        for bogus in bogus_values:
            to_write = '%s%s' % (value, bogus)
            rev_to_write = '%s%s' % (bogus, value)
            if to_write in bogus_values or rev_to_write in bogus_values or value in bogus_values:
                continue
            config_file.write('"%s"' % to_write)
            config_file.write('"%s"' % rev_to_write)

config_file.close()

# Generate some initial starting configs by generating them via the config_generator

ex_curr = 0
ex_base = 'examples/'

serial = 0
NUM_HOSTS = 1
NUM_VLANS = 2
SWITCH_TO_SWITCH_LINKS = 2

def get_serialno(*_args, **_kwargs):
    """"Return mock serial number"""
    serial += 1
    return serial

def create_config(network_graph, stack=True):
    """Return topo object and a simple stack config generated from network_graph"""
    host_links = {}
    host_vlans = {}
    dp_options = {}
    host_n = 0
    for dp_i in network_graph.nodes():
        for _ in range(NUM_HOSTS):
            for v_i in range(NUM_VLANS):
                host_links[host_n] = [dp_i]
                host_vlans[host_n] = v_i
                host_n += 1
        dp_options[dp_i] = {'hardware': 'GenericTFM'}
        if dp_i == 0 and stack:
            dp_options[dp_i]['stack'] = {'priority': 1}
    switch_links = list(network_graph.edges()) * SWITCH_TO_SWITCH_LINKS
    if stack:
        link_vlans = {link: None for link in switch_links}
    else:
        link_vlans = {link: list(range(NUM_VLANS)) for link in switch_links}
    topo = FaucetFakeOFTopoGenerator(
        'ovstype', 'portsock', 'testname',
        host_links, host_vlans, switch_links, link_vlans,
        start_port=START_PORT, port_order=PORT_ORDER,
        get_serialno=get_serialno)
    config = topo.get_config(NUM_VLANS, dp_options=dp_options)
    return config

configs = []
topologies = graph_atlas_g()
for graph in topologies:
    if not graph or not networkx.is_connected(graph):
        continue
    if len(graph.nodes()) > 4:
        break
    for stack in (True, False):
        configs.append(create_config(graph), stack=stack)

for config in configs:
    ex_fn = '%sex%s' % (ex_base, ex_curr)
    ex_file = open(ex_fn, 'xw')
    ex_file.write(config)
    ex_file.close()
    ex_curr += 1
