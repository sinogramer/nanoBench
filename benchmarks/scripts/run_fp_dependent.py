#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path


def march_for_extension(extension: str) -> str:
    extension = extension.lower()

    march_by_extension = {
        "f": "rv64gc",
        "d": "rv64gc",
    }

    try:
        return march_by_extension[extension]
    except KeyError as error:
        raise ValueError(
            f"unsupported FP extension: {extension}"
        ) from error


def move_instruction(precision: str) -> str:
    if precision == "s":
        return "fmv.w.x"

    if precision == "d":
        return "fmv.d.x"

    raise ValueError(f"unsupported FP precision: {precision}")


def fp_bits(value_name: str, precision: str) -> str:
    values = {
        "s": {
            "half": "0x3f000000",
            "one": "0x3f800000",
            "one_point_five": "0x3fc00000",
            "two": "0x40000000",
            "three": "0x40400000",
            "four": "0x40800000",
            "negative_two": "0xc0000000",
        },
        "d": {
            "half": "0x3fe0000000000000",
            "one": "0x3ff0000000000000",
            "one_point_five": "0x3ff8000000000000",
            "two": "0x4000000000000000",
            "three": "0x4008000000000000",
            "four": "0x4010000000000000",
            "negative_two": "0xc000000000000000",
        },
    }

    try:
        return values[precision][value_name]
    except KeyError as error:
        raise ValueError(
            f"unsupported FP value: precision={precision}, "
            f"value={value_name}"
        ) from error


def generate_latency_asm(row: dict[str, str]) -> str:
    mnemonic = row["mnemonic"]
    operand_form = row["operand_form"]

    if operand_form == "fd-fs1-fs2":
        return (
            f"{mnemonic} ft2,ft0,ft1; "
            f"{mnemonic} ft0,ft2,ft1"
        )
    
    if operand_form == "fd-fs1-fs2-fs3":
        return (
            f"{mnemonic} ft2,ft0,ft1,ft3; "
            f"{mnemonic} ft0,ft2,ft1,ft3"
        )

    raise ValueError(
        f"{row['name']}: unsupported FP latency operand form: "
        f"{operand_form}"
    )


def generate_add_latency_init(row: dict[str, str]) -> str:
    precision = row["precision"]
    move = move_instruction(precision)

    return (
        f"li t2,{fp_bits('one', precision)}; "
        f"{move} ft1,t2; "
        f"li t2,{fp_bits('two', precision)}; "
        f"{move} ft0,t2; "
        f"{move} ft2,t2"
    )
    
def generate_mul_latency_init(row: dict[str, str]) -> str:
    precision = row["precision"]
    move = move_instruction(precision)

    return (
        f"li t2,{fp_bits('one', precision)}; "
        f"{move} ft1,t2; "
        f"li t2,{fp_bits('one_point_five', precision)}; "
        f"{move} ft0,t2; "
        f"{move} ft2,t2"
    )

def generate_fma_latency_init(row: dict[str, str]) -> str:
    precision = row["precision"]
    move = move_instruction(precision)

    return (
        f"li t2,{fp_bits('one', precision)}; "
        f"{move} ft1,t2; "
        f"li t2,{fp_bits('half', precision)}; "
        f"{move} ft3,t2; "
        f"li t2,{fp_bits('one_point_five', precision)}; "
        f"{move} ft0,t2; "
        f"{move} ft2,t2"
    )

def generate_sign_minmax_latency_init(
    row: dict[str, str],
) -> str:
    precision = row["precision"]
    move = move_instruction(precision)

    return (
        f"li t2,{fp_bits('negative_two', precision)}; "
        f"{move} ft1,t2; "
        f"li t2,{fp_bits('one_point_five', precision)}; "
        f"{move} ft0,t2; "
        f"{move} ft2,t2"
    )

def generate_latency_init(row: dict[str, str]) -> str:
    profile = row["input_profile"]

    if profile in {
        "add",
        "add_s",
        "add_d",
        "sub",
        "sub_s",
        "sub_d",
    }:
        return generate_add_latency_init(row)

    if profile in {"mul", "mul_s", "mul_d"}:
        return generate_mul_latency_init(row)

    if profile.startswith("fma"):
        return generate_fma_latency_init(row)
    
    if profile.startswith(("sign", "minmax")):
        return generate_sign_minmax_latency_init(row)

    raise ValueError(
        f"{row['name']}: unsupported FP input profile: {profile}"
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
            
            if row["input_profile"].startswith(("div", "sqrt", "feq", "flt", "fle")):
                continue

            march = march_for_extension(row["extension"])
            asm = generate_latency_asm(row)
            init = generate_latency_init(row)

            command = [
                "sudo",
                str(wrapper),
                "-march",
                march,
                "-asm",
                asm,
                "-asm_init",
                init,
                "-name",
                f"{row['name']}_latency",
                "-measurement",
                "fp_latency",
                "-instructions_per_block",
                "2",
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

            run_command(
                command,
                root,
                f"{row['name']}: latency",
            )


if __name__ == "__main__":
    main()