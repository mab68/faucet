from functools import partial
import unittest
import ipaddress
import yaml

from ryu.lib import mac
from ryu.ofproto import ofproto_v1_3 as ofp

from faucet import valves_manager
from faucet import valve_of
from faucet.port import (
    STACK_STATE_INIT, STACK_STATE_UP,
    LACP_PORT_SELECTED, LACP_PORT_UNSELECTED)

from fakeoftable import CONTROLLER_PORT

from valve_test_lib import (
    BASE_DP1_CONFIG, CONFIG, STACK_CONFIG, STACK_LOOP_CONFIG, ValveTestBases)


class ACLTableTestCase(ValveTestBases.ValveTestSmall):

    CONFIG = """
acls:
    multiout-acl:
        - rule:
            ip_proto: 1
            dl_type: 0x0800
            actions:
                output:
                    - port: 2
                    - vlan_vid: 512
                    - port: 3
                    - pop_vlans: 1
                    - port: 4
vlans:
    vlan100:
        vid: 100
dps:
    s1:
        %s
        interfaces:
            1:
                native_vlan: vlan100
                acls_in: [multiout-acl]
            2:
                native_vlan: vlan100
            3:
                native_vlan: vlan100
            4:
                native_vlan: vlan100
""" % BASE_DP1_CONFIG

    def setUp(self):
        self.setup_valve(self.CONFIG)

    def test_multiple_outputs(self):
        """ """
        match = {
            'in_port': in_port,
            'eth_dst': mac.BROADCAST_STR,
            'eth_type': 0x0800,
            'ip_proto': 1,
            'vid': 0
        }
        self.table.is_full_output(match, 2, 0)
        self.table.is_full_output(match, 3, 512 | ofp.OFP_VID_PRESENT)
        self.table.is_full_output(match, 4, 0)


class GroupDelACLTestCase(ValveTestBases.ValveTestSmall):
    """ """

    CONFIG = """
acls:
    group-acl:
        - rule:
            dl_dst: "0e:00:00:00:02:02"
            actions:
                output:
                    failover:
                        group_id: 1001
                        ports: [2, 3]
vlans:
    vlan100:
        vid: 100
dps:
    s1:
        %s
        interfaces:
            1:
                native_vlan: vlan100
            2:
                native_vlan: vlan100
            3:
                native_vlan: vlan100
""" % BASE_DP1_CONFIG

    def setUp(self):
        self.setup_valve(self.CONFIG)

    def test_groupdel_exists(self):
        """ """
        
