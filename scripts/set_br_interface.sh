#!/bin/bash
NUMBER=$1
BRIDGE_NAME=br${NUMBER}
HOST=$2
HOST_NAME=veth-${HOST}
PORT_NUM=$3
echo "Setting bridge interface ${HOST_NAME}:${PORT_NUM} on ${BRIDGE_NAME}"
sudo ovs-vsctl add-port ${BRIDGE_NAME} ${HOST_NAME} -- set interface ${HOST_NAME} ofport_request=${PORT_NUM}
