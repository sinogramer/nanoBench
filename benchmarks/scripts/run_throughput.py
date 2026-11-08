#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path

CHAIN_REGISTERS = ["t3", "t4", "t5", "t6", "a0", "a1", "a2", "a3"]
CHAIN_COUNTS = [1, 2, 3, 4, 6, 8]
COMMON_SOURCE = "t2"


def generate_throughput_asm(mnemonic: str, chain_count: int) -> str:
    registers = CHAIN_REGISTERS[:chain_count]
    return "; ".join(f"{mnemonic} {rd}, {rd}, {COMMON_SOURCE}" for rd in registers)


def generate_throughput_init(chain_count: int) -> str:
    instructions = [f"li {COMMON_SOURCE}, 3"]

    for index, register in enumerate(CHAIN_REGISTERS[:chain_count], start=1):
        instructions.append(f"li {register}, {index * 5}")

    return "; ".join(instructions)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=0)
    args = parser.parse_args()

    root = args.root.resolve()
    wrapper = root / "nanoBench-riscv.sh"
    config = root / "configs/riscv/x100-basic.txt"
    result = args.result.resolve()
    result.parent.mkdir(parents=True, exist_ok=True)

    with args.spec.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row.get("enabled", "1") != "1":
                continue
            for chain_count in CHAIN_COUNTS:
                asm = generate_throughput_asm(row["mnemonic"], chain_count)
                init = generate_throughput_init(chain_count)

                command = [
                    "sudo",
                    str(wrapper),
                    "-asm",
                    asm,
                    "-asm_init",
                    init,
                    "-name",
                    f"{row['name']}_throughput_{chain_count}",
                    "-measurement",
                    "throughput",
                    "-instructions_per_block",
                    str(chain_count),
                    "-config",
                    str(config),
                    "-fixed_counters",
                    "-unroll_count",
                    "1000",
                    "-loop_count",
                    "0",
                    "-cpu",
                    str(args.cpu),
                    "-median",
                    "-csv",
                    str(result),
                ]

                print(f"=== {row['name']}: chains={chain_count} ===", flush=True)
                print(shlex.join(command), flush=True)
                subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()