#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path

JUMP_COUNTS = [1, 2, 3, 4, 6, 8]


def generate_jal_to_next(count: int) -> str:
    instructions = []

    for _ in range(count):
        instructions.append("jal zero,1f")
        instructions.append("1:")

    return "; ".join(instructions)

def generate_jal_skip_one(count: int) -> str:
    instructions = []

    for _ in range(count):
        instructions.append("jal zero,1f")
        instructions.append("nop")
        instructions.append("1:")

    return "; ".join(instructions)

def generate_jalr_to_next_pair(count: int) -> str:
    instructions = []

    for _ in range(count):
        instructions.append("auipc t2, 0")
        instructions.append("jalr zero, 8(t2)")

    return "; ".join(instructions)

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
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

            for count in JUMP_COUNTS:
                if row["kind"] == "jal_to_next":
                    asm = generate_jal_to_next(count)
                    instructions_per_block = count
                elif row["kind"] == "jal_skip_one":
                    asm = generate_jal_skip_one(count)
                    instructions_per_block = count
                elif row["kind"] == "jalr_to_next_pair":
                    asm = generate_jalr_to_next_pair(count)
                    instructions_per_block = count * 2
                else:
                    raise ValueError(f"unsupported jump kind: {row['kind']}")

                command = [
                    "sudo",
                    str(wrapper),
                    "-march",
                    "rv64gc",
                    "-asm",
                    asm,
                    "-name",
                    f"{row['name']}_throughput_{count}",
                    "-measurement",
                    "jump_throughput",
                    "-instructions_per_block",
                    str(count),
                    "-config",
                    str(config),
                    "-fixed_counters",
                    "-unroll_count",
                    "64",
                    "-loop_count",
                    "16",
                    "-initial_warm_up_count",
                    "0",
                    "-cpu",
                    str(args.cpu),
                    "-median",
                    "-csv",
                    str(result),
                ]

                print(
                    f"=== {row['name']}: count={count} ===",
                    flush=True,
                )
                print(shlex.join(command), flush=True)
                subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()