#!/bin/bash
#BR1=br${1}
#BR2=br${2}
#BR1_BR2_PORT=$3
#BR2_BR1_PORT=$4
#BR1_PATCH=patch$5
#BR2_PATCH=patch$6
#echo "Stack link; ${BR1}:${BR1_BR2_PORT} <-> ${BR2}:${BR2_BR1_PORT}"
#sudo ovs-vsctl \
#    -- add-port ${BR1} ${BR1_PATCH} \
#    -- set-interface ${BR1_PATCH} type=patch options:peer=${BR2_PATCH} ofport_request=${BR1_BR2_PORT} \
#    -- add-port ${BR2} ${BR2_PATCH} \
#    -- set-interface ${BR2_PATCH} type=patch options:peer=${BR1_PATCH} ofport_request=${BR2_BR1_PORT}
BR1=br${1}
BR1_PATCH=patch${2}
BR2_PATCH=patch${3}
BR1_PORT=$4
echo "Stack link ${BR1} ${BR1_PATCH}:${BR2_PATCH} from ${BR1_PORT}"
sudo ovs-vsctl add-port ${BR1} ${BR1_PATCH} -- set interface ${BR1_PATCH} type=patch options:peer=${BR2_PATCH} ofport_request=${BR1_PORT}
