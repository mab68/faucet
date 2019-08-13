#!/bin/bash
if [ -z "$1" ]; then
    echo "No parameters given"
    exit 0
fi
config_file="$1"
echo "Creating faucet with config:$config_file"
cd ../
sudo docker stop faucet
sudo docker rm faucet
sudo docker build -t faucet/faucet -f Dockerfile.faucet .
sudo docker run -d \
    --name faucet \
    --restart=always \
    -v /home/m/Documents/COMPX520/FaucetSDN/scripts/$config_file:/etc/faucet/faucet.yaml \
    -v /var/log/faucet/:/var/log/faucet/ \
    -p 6653:6653 \
    -p 9302:9302 \
    faucet/faucet
#cd scripts/
#python3 create_network.py "$1"
