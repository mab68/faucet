#!/usr/bin/env python3
import yaml
import pprint
import subprocess
import sys
import re
from random import shuffle

subprocess.call('./cleanup.sh', shell=True)

vlan_ip_prefix = {}
vlan_ip_suffix = {}

def ipr_str(host_name, ip_route, vip):
    return './as_ns.sh %s ip route add %s via %s dev veth0' % (host_name, ip_route, vip)

def process_dps(dps_dict, vlans_dict):
    vlan_vip = {}

    vlan_name_ip = {}

    for vlan_name, vlan_dict in vlans_dict.items():
        if 'faucet_vips' in vlan_dict:
            vlan_vip[vlan_name] = vlan_dict['faucet_vips'][0]
        vlan_name_ip[vlan_name] = []
    for dp_name, dp_dict in dps_dict.items():
        patch_count = {}

        dp_id = dp_dict['dp_id']
        #print(dp_name, dp_dict['dp_id'])
        subprocess.call('./add_br.sh %s %s' % (dp_id, dp_id), shell=True)
        for port_num, port_dict in dp_dict['interfaces'].items():
            #print(port_num, port_dict)
            if 'stack' in port_dict:
                stack_dict = port_dict['stack']
                peer_port = stack_dict['port']
                peer_dp_name = stack_dict['dp']
                peer_dp = dps_dict[peer_dp_name]['dp_id']
                if peer_dp in patch_count:
                    patch_count[peer_dp] = patch_count[peer_dp]+1
                else:
                    patch_count[peer_dp] = ord('a')
                p_count = chr(patch_count[peer_dp])
                patch = "%s_%s%s" % (dp_id, peer_dp, p_count)
                peer_patch = "%s_%s%s" % (peer_dp, dp_id, p_count)
                subprocess.call('./create_stack_link.sh %s %s %s %s' % (dp_id, patch, peer_patch, port_num), shell=True)
            else:
                name = port_dict['name']
                if 'output_only' in port_dict and port_dict['output_only']:
                    continue
                else:
                    vlan = port_dict['native_vlan']
                    vlan_prefix = vlan_ip_prefix[vlan]
                    ip_suffix = vlan_ip_suffix[port_dict['native_vlan']]
                    ip_address = "fc0%s::1:%s/64" % (vlan_prefix, ip_suffix)
                    subprocess.call('./create_ns.sh %s %s' % (name, ip_address), shell=True)
                    subprocess.call('./set_br_interface.sh %s %s %s' % (dp_id, name, port_num), shell=True)
                    vlan_ip_suffix[vlan] += 1
                    if vlan in vlan_vip:
                        subprocess.call('./as_ns.sh %s ip route add default via %s dev veth0' % (name, vlan_vip[vlan][0:-4]), shell=True)
                    if vlan in vlan_name_ip:
                        vlan_name_ip[vlan].append((name, '10.0.%s.%s' % (vlan_prefix, ip_suffix)))

    #print('\nTESTING INTERVLAN ROUTING...\n')
    #vlan_a, vlan_b = vlan_name_ip.keys()
    #vlan_a_info = vlan_name_ip[vlan_a]
    #vlan_b_info = vlan_name_ip[vlan_b]
    #shuffle(vlan_a_info)
    #shuffle(vlan_b_info)
    #for a_tuple in vlan_a_info:
    #    a_name, a_ip = a_tuple
    #    for b_tuple in vlan_b_info:
    #        b_name, b_ip = b_tuple

    #       a_data = subprocess.getoutput('./as_ns.sh %s ping -c2 %s' % (a_name, b_ip))
    #        a_data = (a_data.split("\n"))[-2]
    #        a_result = re.search('(?<=received, ).*?(?= packet loss)', a_data)
    #        print('%s (%s) -> %s (%s): %s' % (a_name, a_ip, b_name, b_ip, a_result.group(0)))

    #        b_data = subprocess.getoutput('./as_ns.sh %s ping -c2 %s' % (b_name, a_ip))
    #        b_data = (b_data.split("\n"))[-2]
    #        print('%s (%s) -> %s (%s): %s' % (b_name, b_ip, a_name, a_ip, a_result.group(0)))

file_name = sys.argv[1]
config_file = "faucet.yaml.%s" % file_name
with open(config_file, 'r') as stream:
    print("Reading: %s" % config_file)
    try:
        config_dict = yaml.load(stream)
        #pprint.pprint(config_dict)
        #print("\n")
        ip_count = 1
        for vlan_name, vlan_dict in config_dict['vlans'].items():
            vlan_ip_prefix[vlan_name] = ip_count
            vlan_ip_suffix[vlan_name] = 1
            ip_count += 1
        process_dps(config_dict['dps'], config_dict['vlans'])
    except yaml.YAMLError as err:
        print(err)
