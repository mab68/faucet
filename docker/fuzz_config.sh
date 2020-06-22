#!/bin/sh

echo "FUZZING FAUCET CONFIGURATION FILES"

export PYTHONPATH=/faucet-src:/faucet-src/faucet:/faucet-src/clib

cd /faucet-src/tests/generative/fuzzer/config/

python3 generate_dict.py || exit 0

dictfile="/faucet-src/tests/generative/fuzzer/config/config.dict"

cat "$dictfile"

inputfile="/faucet-src/tests/generative/fuzzer/config/examples/"

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

echo core >/proc/sys/kernel/core_pattern

LIMIT_MB=5000
#ulimit -Sv $[LIMIT_MB << 10]; /path/to/tested_binary ...

AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES=1 AFL_SKIP_CPUFREQ=1 py-afl-fuzz -m 5000 -x "$dictfile" -i "$inputfile" -o "$outputfile" -- /usr/bin/python3 /faucet-src/tests/generative/fuzzer/fuzz_config.py
