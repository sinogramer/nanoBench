#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path

PATTERNS = [
    (1, 1),
    (2, 1),
    (1, 2),
    (3, 1),
    (1, 3),
    (2, 2),
    (3, 2),
    (2, 3),
    (3, 3),
    (4, 3),
    (6, 3),
]

REGISTERS = [
    "t0", "t1", "t3", "t4", "t5", "t6",
    "a0", "a1", "a2", "a3", "a4", "a5", "a6", "a7",
]
COMMON_SOURCE = "t2"


def generate_asm(mnemonic_a: str, mnemonic_b: str, count_a: int, count_b: int) -> str:
    instructions = []
    register_index = 0

    for _ in range(count_a):
        rd = REGISTERS[register_index]
        instructions.append(f"{mnemonic_a} {rd}, {rd}, {COMMON_SOURCE}")
        register_index += 1

    for _ in range(count_b):
        rd = REGISTERS[register_index]
        instructions.append(f"{mnemonic_b} {rd}, {rd}, {COMMON_SOURCE}")
        register_index += 1

    return "; ".join(instructions)


def generate_init(instruction_count: int) -> str:
    instructions = [f"li {COMMON_SOURCE}, 3"]

    for index, register in enumerate(REGISTERS[:instruction_count], start=1):
        instructions.append(f"li {register}, {index * 5}")

    return "; ".join(instructions)

def interleave_instructions(
    mnemonic_a: str,
    mnemonic_b: str,
    count_a: int,
    count_b: int,
) -> list[str]:
    instructions = []
    index_a = 0
    index_b = count_a

    while index_a < count_a or index_b < count_a + count_b:
        if index_a < count_a:
            rd = REGISTERS[index_a]
            instructions.append(f"{mnemonic_a} {rd}, {rd}, {COMMON_SOURCE}")
            index_a += 1

        if index_b < count_a + count_b:
            rd = REGISTERS[index_b]
            instructions.append(f"{mnemonic_b} {rd}, {rd}, {COMMON_SOURCE}")
            index_b += 1

    return instructions


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
            for count_a, count_b in PATTERNS:
                instruction_count = count_a + count_b
                instructions = interleave_instructions(
                    row["mnemonic_a"],
                    row["mnemonic_b"],
                    count_a,
                    count_b,
                )
                asm = "; ".join(instructions)
                init = generate_init(instruction_count)
                name = f"{row['name']}_{count_a}_{count_b}"

                command = [
                    "sudo",
                    str(wrapper),
                    "-asm",
                    asm,
                    "-asm_init",
                    init,
                    "-name",
                    name,
                    "-measurement",
                    "mixed_throughput",
                    "-instructions_per_block",
                    str(instruction_count),
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

                print(f"=== {name} ===", flush=True)
                print(shlex.join(command), flush=True)
                subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()