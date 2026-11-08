#!/usr/bin/env bash

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
RESULT="$ROOT/results/x100-integer.csv"
CONFIG="$ROOT/configs/riscv/x100-basic.txt"

mkdir -p "$ROOT/results"

for code in "$ROOT"/benchmarks/generated/bin/*_dependent.bin; do
    init="${code%_dependent.bin}_init.bin"

    sudo "$ROOT/user/nanoBench" \
        -code "$code" \
        -code_init "$init" \
        -config "$CONFIG" \
        -fixed_counters \
        -unroll_count 1000 \
        -loop_count 0 \
        -cpu 0 \
        -median \
        -csv "$RESULT"
done