#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path

COUNTS = [1, 2, 3, 4, 6, 8]
REGISTERS = ["t0", "t1", "t2", "t3", "t4", "t5", "t6", "a0"]


def generate_loads(mnemonic: str, count: int, stride: int) -> str:
    return "; ".join(
        f"{mnemonic} {register},{index * stride}(s9)"
        for index, register in enumerate(REGISTERS[:count])
    )


def generate_load_init(count: int, stride: int) -> str:
    return "; ".join(
        f"ld zero,{index * stride}(s9)"
        for index in range(count)
    )


def generate_stores(mnemonic: str, count: int, stride: int) -> str:
    return "; ".join(
        f"{mnemonic} {register},{index * stride}(s9)"
        for index, register in enumerate(REGISTERS[:count])
    )


def generate_store_init(count: int, stride: int) -> str:
    instructions = [
        f"li {register},{index + 1}"
        for index, register in enumerate(REGISTERS[:count])
    ]

    instructions.extend(
        f"sd zero,{index * stride}(s9)"
        for index in range(count)
    )

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
    parser.add_argument("--stride", type=int, default=8)
    args = parser.parse_args()

    root = args.root.resolve()
    wrapper = root / "nanoBench-riscv.sh"
    config = root / "configs/riscv/x100-basic.txt"
    result = args.result.resolve()
    result.parent.mkdir(parents=True, exist_ok=True)

    with args.spec.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            for count in COUNTS:
                if row["kind"] == "load":
                    asm = generate_loads(row["mnemonic"], count, args.stride)
                    init = generate_load_init(count, args.stride)
                elif row["kind"] == "store":
                    asm = generate_stores(row["mnemonic"], count, args.stride)
                    init = generate_store_init(count, args.stride)
                else:
                    raise ValueError(f"unknown memory operation: {row['kind']}")

                name = f"{row['name']}_throughput_{count}"

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
                    "throughput",
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

                print(f"=== {name}, stride={args.stride} ===", flush=True)
                print(shlex.join(command), flush=True)
                subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()