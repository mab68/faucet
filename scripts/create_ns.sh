#!/bin/bash
NAME=$1
IP=$2
NETNS=faucet-${NAME}
echo "Creating host ${NAME}:${IP} on ${NETNS}"
sudo ip netns add ${NETNS}
sudo ip link add dev veth-${NAME} type veth peer name veth0 netns $NETNS
sudo ip link set dev veth-${NAME} up
sudo ip netns exec ${NETNS} ip link set dev veth0 up
sudo ip netns exec ${NETNS} ip addr add dev veth0 $IP
sudo ip netns exec ${NETNS} ip link set dev lo up

