#!/usr/bin/env bash

set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
CC=${CC:-gcc}
OBJCOPY=${OBJCOPY:-objcopy}

MARCH=${MARCH:-rv64gc}
MABI=${MABI:-lp64d}

ASM=""
ASM_INIT=""
KEEP_TEMP=0
ARGS=()

while (($# > 0)); do
    case "$1" in
        -asm)
            ASM=$2
            shift 2
            ;;
        -asm_init)
            ASM_INIT=$2
            shift 2
            ;;
        -march)
            MARCH=$2
            shift 2
            ;;
        -mabi)
            MABI=$2
            shift 2
            ;;
        -keep_temp)
            KEEP_TEMP=1
            shift
            ;;
        *)
            ARGS+=("$1")
            shift
            ;;
    esac
done

if [[ -z "$ASM" ]]; then
    echo "nanoBench-riscv.sh: -asm is required" >&2
    exit 1
fi

TMPDIR=$(mktemp -d "${TMPDIR:-/tmp}/nanobench-riscv.XXXXXX")

cleanup()
{
    if ((KEEP_TEMP == 0)); then
        rm -rf "$TMPDIR"
    else
        echo "Temporary files: $TMPDIR" >&2
    fi
}

trap cleanup EXIT

write_asm()
{
    local output=$1
    local symbol=$2
    local body=$3

    {
        echo '.text'
        echo '.option norvc'
        echo ".globl $symbol"
        echo ".type $symbol, @function"
        echo "$symbol:"
        tr ';' '\n' <<< "$body"
        echo ".size $symbol, .-$symbol"
    } > "$output"
}

write_asm "$TMPDIR/code.S" benchmark "$ASM"
"$CC" -c -march="$MARCH" -mabi="$MABI" -o "$TMPDIR/code.o" "$TMPDIR/code.S"
"$OBJCOPY" -O binary -j .text "$TMPDIR/code.o" "$TMPDIR/code.bin"

if [[ -n "$ASM_INIT" ]]; then
    write_asm "$TMPDIR/init.S" benchmark_init "$ASM_INIT"
    "$CC" -c -march="$MARCH" -mabi="$MABI" -o "$TMPDIR/init.o" "$TMPDIR/init.S"
    "$OBJCOPY" -O binary -j .text "$TMPDIR/init.o" "$TMPDIR/init.bin"
    ARGS+=(-code_init "$TMPDIR/init.bin")
fi

"$ROOT/user/nanoBench" -code "$TMPDIR/code.bin" "${ARGS[@]}"