#!/bin/bash
NAME=$1
NETNS=faucet-${NAME}
echo "${NAME} executing $@ on ${NETNS}"
shift
sudo ip netns exec $NETNS $@
