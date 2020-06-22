#!/bin/sh

cd /faucet-src

./docker/pip_deps.sh
pip3 install ./
pip3 show faucet

export LANG=en_US.UTF-8
export LANGUAGE=en_US.en
export LC_ALL=en_US.UTF-8

export PYTHONPATH=/faucet-src:/faucet-src/faucet:/faucet-src/clib

python3 /faucet-src/tests/generative/fuzzer/config/generate_dict.py

dictfile="/faucet-src/tests/generative/fuzzer/config/config.dict"
inputfile="/faucet-src/tests/generative/fuzzer/config/ex/"
outputfile="/var/log/afl"
checkfile="$outputfile/fuzzer_stats"

if [ -e "$checkfile" ]; then
    start=$(sed -n '1p' $checkfile | cut -c 18-)
    end=$(sed -n '2p' $checkfile | cut -c 18-)
    diff=$(($end-$start))
    cmp="1500"
    if [ "$diff" -gt "$cmp" ]; then
        inputfile="-"
    fi
fi

AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1 AFL_SKIP_CPUFREQ=1 py-afl-fuzz -x "$dictfile" -m 5000 -i "$inputfile" -o "$outputfile" -- /usr/bin/python3 /faucet-src/tests/generative/fuzzer/fuzz_config.py
