#!/bin/bash
NUMBER=$1
DATAPATH_ID=$2
BRIDGE_NAME=br${NUMBER}
echo "Creating bridge ${BRIDGE_NAME}:${DATAPATH_ID}"
sudo ovs-vsctl add-br ${BRIDGE_NAME} \
    -- set bridge ${BRIDGE_NAME} other-config:datapath-id=0x0${DATAPATH_ID} \
    -- set bridge ${BRIDGE_NAME} other-config:disable-in-band=true \
    -- set bridge ${BRIDGE_NAME} fail_mode=secure \
    -- set-controller ${BRIDGE_NAME} tcp:172.17.0.1:6653 tcp:172.17.0.1:6654
