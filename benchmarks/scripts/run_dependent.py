#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path


def generate_latency_asm(mnemonic: str) -> str:
    return f"{mnemonic} t5, t4, t3; {mnemonic} t4, t5, t3"


def generate_latency_init() -> str:
    return "li t3, 3; li t4, 5; li t5, 7"


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

            name = row["name"]
            mnemonic = row["mnemonic"]
            asm = generate_latency_asm(mnemonic)
            init = generate_latency_init()

            command = [
                "sudo",
                str(wrapper),
                "-asm",
                asm,
                "-asm_init",
                init,
                "-name",
                f"{name}_latency",
                "-measurement",
                "latency",
                "-instructions_per_block",
                "2",
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

            print(f"=== {name}: latency ===", flush=True)
            print(shlex.join(command), flush=True)
            subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()