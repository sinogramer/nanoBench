#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path

BRANCH_COUNTS = [1, 2, 3, 4, 6, 8]
RS1 = "t2"
RS2 = "t3"


def generate_branch_asm(
    mnemonic: str,
    branch_count: int,
) -> str:
    instructions = []

    for _ in range(branch_count):
        instructions.append(f"{mnemonic} {RS1}, {RS2}, 1f")
        instructions.append("1:")

    return "; ".join(instructions)


def generate_branch_init(row: dict[str, str]) -> str:
    return (
        f"li {RS1}, {row['rs1_value']}; "
        f"li {RS2}, {row['rs2_value']}"
    )


def run_command(
    command: list[str],
    root: Path,
    description: str,
) -> None:
    print(f"=== {description} ===", flush=True)
    print(shlex.join(command), flush=True)
    subprocess.run(command, cwd=root, check=True)


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

            init = generate_branch_init(row)

            for branch_count in BRANCH_COUNTS:
                asm = generate_branch_asm(
                    row["mnemonic"],
                    branch_count,
                )

                name = f"{row['name']}_throughput_{branch_count}"

                command = [
                    "sudo",
                    str(wrapper),
                    "-march",
                    "rv64gc",
                    "-asm",
                    asm,
                    "-asm_init",
                    init,
                    "-name",
                    name,
                    "-measurement",
                    "branch_throughput",
                    "-instructions_per_block",
                    str(branch_count),
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

                run_command(
                    command,
                    root,
                    f"{row['name']}: count={branch_count}",
                )


if __name__ == "__main__":
    main()