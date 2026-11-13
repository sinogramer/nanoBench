#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path


RESTORE_LATENCY = 4


def move_instruction(precision: str) -> str:
    if precision == "s":
        return "fmv.w.x"

    if precision == "d":
        return "fmv.d.x"

    raise ValueError(f"unsupported FP precision: {precision}")


def fp_bits(value: str, precision: str) -> str:
    values = {
        "s": {
            "one_point_five": "0x3fc00000",
            "two": "0x40000000",
            "three": "0x40400000",
            "four": "0x40800000",
        },
        "d": {
            "one_point_five": "0x3ff8000000000000",
            "two": "0x4000000000000000",
            "three": "0x4008000000000000",
            "four": "0x4010000000000000",
        },
    }

    try:
        return values[precision][value]
    except KeyError as error:
        raise ValueError(
            f"unsupported FP value: precision={precision}, value={value}"
        ) from error


def generate_latency_asm(row: dict[str, str]) -> str:
    mnemonic = row["mnemonic"]
    precision = row["precision"]
    profile = row["input_profile"]

    if profile.startswith("div"):
        return (
            f"{mnemonic} ft2,ft0,ft1; "
            f"fmul.{precision} ft0,ft2,ft1"
        )

    if profile.startswith("sqrt"):
        return (
            f"{mnemonic} ft2,ft0; "
            f"fmul.{precision} ft0,ft2,ft2"
        )

    raise ValueError(
        f"{row['name']}: unsupported long-latency profile: {profile}"
    )


def generate_latency_init(row: dict[str, str]) -> str:
    precision = row["precision"]
    profile = row["input_profile"]
    move = move_instruction(precision)

    if profile.startswith("div"):
        return (
            f"li t2,{fp_bits('three', precision)}; "
            f"{move} ft0,t2; "
            f"li t2,{fp_bits('one_point_five', precision)}; "
            f"{move} ft1,t2; "
            f"li t2,{fp_bits('two', precision)}; "
            f"{move} ft2,t2"
        )

    if profile.startswith("sqrt"):
        return (
            f"li t2,{fp_bits('four', precision)}; "
            f"{move} ft0,t2; "
            f"li t2,{fp_bits('two', precision)}; "
            f"{move} ft2,t2"
        )

    raise ValueError(
        f"{row['name']}: unsupported long-latency profile: {profile}"
    )


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
    parser.add_argument("--unroll-count", type=int, default=64)
    parser.add_argument("--loop-count", type=int, default=16)
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

            if row.get("latency", "1") != "1":
                continue

            profile = row["input_profile"]

            if not profile.startswith(("div", "sqrt")):
                continue

            asm = generate_latency_asm(row)
            init = generate_latency_init(row)

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
                f"{row['name']}_latency_restore_{RESTORE_LATENCY}",
                "-measurement",
                "fp_long_latency",
                "-instructions_per_block",
                "1",
                "-config",
                str(config),
                "-fixed_counters",
                "-unroll_count",
                str(args.unroll_count),
                "-loop_count",
                str(args.loop_count),
                "-initial_warm_up_count",
                "0",
                "-cpu",
                str(args.cpu),
                "-median",
                "-csv",
                str(result),
            ]

            print(f"=== {row['name']}: long latency ===", flush=True)
            print(shlex.join(command), flush=True)
            subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()