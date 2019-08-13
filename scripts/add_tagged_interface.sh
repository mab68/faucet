#!/bin/bash
NAME=$1
IP=$2
VLAN=$3
NETNS=faucet-${NAME}
echo "Adding tagged interface ${NAME}:${IP}:${VLAN}:${NETNS}"
sudo ip netns exec ${NETNS} ip link add link veth0 name veth0.${VLAN} type vlan id $VLAN
sudo ip netns exec ${NETNS} ip link set dev veth0.${VLAN} up
sudo ip netns exec ${NETNS} ip addr flush dev veth0
sudo ip netns exec ${NETNS} ip addr add dev veth0.${VLAN} $IP
