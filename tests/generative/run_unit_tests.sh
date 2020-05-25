#!/bin/bash

SCRIPTPATH=$(readlink -f "$0")
TESTDIR=`dirname $SCRIPTPATH`
BASEDIR=`readlink -f $TESTDIR/..`
cd $BASEDIR || exit 1

# #!/bin/sh

# ./sysctls_for_tests.sh

# export OVS_LOGDIR=/usr/local/var/log
# export FAUCET_DIR=$PWD/../faucet
# export PYTHONPATH=$PWD/..:$PWD/../clib

# cd integration
# rm -rf /tmp/faucet*log /tmp/gauge*log /tmp/faucet-tests* /var/tmp/faucet-tests* $OVS_LOGDIR/* ;
# killall ryu-manager ;
# ./mininet_main.py -c ;
# /usr/local/share/openvswitch/scripts/ovs-ctl stop ;
# /usr/local/share/openvswitch/scripts/ovs-ctl start ;
# ./mininet_main.py $*


#TESTCMD="PYTHONPATH=$BASEDIR coverage run --parallel-mode --source $BASEDIR/faucet:$PWD/..:$PWD/../../clib"
TESTCMD=""
SRCFILES="find $TESTDIR/unit/test_*py -type f"

$SRCFILES | xargs realpath | shuf | parallel --timeout 30
$SRCFILES | xargs realpath | shuf | parallel --timeout 300 --delay 1 --bar --halt now,fail=1 -j 2 $TESTCMD || exit 1
