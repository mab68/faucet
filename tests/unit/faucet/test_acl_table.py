#!/usr/bin/env python

"""Unit tests run as PYTHONPATH=../../.. python3 ./test_acl_table.py"""

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
                acls_in: [group-acl]
            2:
                native_vlan: vlan100
            3:
                native_vlan: vlan100
""" % BASE_DP1_CONFIG

    def setUp(self):
        self.setup_valve(self.CONFIG)

    def test_groupdel_exists(self):
        """ """
        valve = self.valves_manager.valves[0x1]
        port = valve.dp.ports[1]
        ofmsgs = valve.acl_manager.add_port(port)
        import pprint
        pprint.pprint(ofmsgs)
