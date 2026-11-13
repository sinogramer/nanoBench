#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path


VECTOR_LATENCY_REGISTERS_BY_LMUL = {
    "m1": ("v1", "v2", "v3"),
    "m2": ("v2", "v4", "v6"),
    "m4": ("v4", "v8", "v12"),
    "m8": ("v0", "v8", "v16"),
}

VECTOR_SCALAR_SOURCE = "t2"

VECTOR_VECTOR_PROFILES = {
    "integer_add",
    "integer_logic",
    "integer_minmax",
    "integer_mul",
}

VECTOR_SCALAR_PROFILES = {
    "integer_add_vx",
    "integer_logic_vx",
    "integer_minmax_vx",
    "integer_mul_vx",
}


def generate_vector_config(row: dict[str, str]) -> list[str]:
    vl = int(row["vl"])
    sew = row["sew"]
    lmul = row["lmul"]

    if vl <= 0:
        raise ValueError(
            f"{row['name']}: VL must be greater than zero"
        )

    if vl <= 31:
        return [
            f"vsetivli zero,{vl},e{sew},{lmul},ta,ma"
        ]

    return [
        f"li t2,{vl}",
        f"vsetvli zero,t2,e{sew},{lmul},ta,ma",
    ]


def latency_registers(
    row: dict[str, str],
) -> tuple[str, str, str]:
    lmul = row["lmul"]

    try:
        return VECTOR_LATENCY_REGISTERS_BY_LMUL[lmul]
    except KeyError as error:
        raise ValueError(
            f"{row['name']}: unsupported LMUL: {lmul}"
        ) from error


def generate_latency_asm(row: dict[str, str]) -> str:
    mnemonic = row["mnemonic"]
    operand_form = row["operand_form"]
    common_source, first, second = latency_registers(row)

    if operand_form == "vd-vs2-vs1":
        return (
            f"{mnemonic} {second},{first},{common_source}; "
            f"{mnemonic} {first},{second},{common_source}"
        )

    if operand_form == "vd-vs2-rs1":
        return (
            f"{mnemonic} {second},{first},"
            f"{VECTOR_SCALAR_SOURCE}; "
            f"{mnemonic} {first},{second},"
            f"{VECTOR_SCALAR_SOURCE}"
        )

    raise ValueError(
        f"{row['name']}: unsupported Vector operand form: "
        f"{operand_form}"
    )


def vector_vector_initial_values(
    profile: str,
) -> tuple[int, int, int]:
    if profile == "integer_mul":
        return 3, 5, 5

    if profile in {
        "integer_add",
        "integer_logic",
        "integer_minmax",
    }:
        return 1, 2, 2

    raise ValueError(
        f"unsupported Vector-Vector profile: {profile}"
    )


def vector_scalar_initial_values(
    profile: str,
) -> tuple[int, int, int]:
    if profile == "integer_mul_vx":
        return 3, 5, 5

    if profile in {
        "integer_add_vx",
        "integer_logic_vx",
        "integer_minmax_vx",
    }:
        return 1, 2, 2

    raise ValueError(
        f"unsupported Vector-Scalar profile: {profile}"
    )


def generate_vector_vector_latency_init(
    row: dict[str, str],
) -> str:
    profile = row["input_profile"]
    common_source, first, second = latency_registers(row)

    common_value, first_value, second_value = (
        vector_vector_initial_values(profile)
    )

    instructions = generate_vector_config(row)
    instructions.extend([
        f"vmv.v.i {common_source},{common_value}",
        f"vmv.v.i {first},{first_value}",
        f"vmv.v.i {second},{second_value}",
    ])

    return "; ".join(instructions)


def generate_vector_scalar_latency_init(
    row: dict[str, str],
) -> str:
    profile = row["input_profile"]
    _, first, second = latency_registers(row)

    scalar_value, first_value, second_value = (
        vector_scalar_initial_values(profile)
    )

    instructions = generate_vector_config(row)
    instructions.extend([
        f"li {VECTOR_SCALAR_SOURCE},{scalar_value}",
        f"vmv.v.i {first},{first_value}",
        f"vmv.v.i {second},{second_value}",
    ])

    return "; ".join(instructions)


def generate_latency_init(row: dict[str, str]) -> str:
    profile = row["input_profile"]
    operand_form = row["operand_form"]

    if operand_form == "vd-vs2-vs1":
        if profile not in VECTOR_VECTOR_PROFILES:
            raise ValueError(
                f"{row['name']}: profile {profile} is not valid "
                f"for operand form {operand_form}"
            )

        return generate_vector_vector_latency_init(row)

    if operand_form == "vd-vs2-rs1":
        if profile not in VECTOR_SCALAR_PROFILES:
            raise ValueError(
                f"{row['name']}: profile {profile} is not valid "
                f"for operand form {operand_form}"
            )

        return generate_vector_scalar_latency_init(row)

    raise ValueError(
        f"{row['name']}: unsupported Vector operand form: "
        f"{operand_form}"
    )


def count_generated_instructions(asm: str) -> int:
    return len([
        instruction
        for instruction in asm.split(";")
        if instruction.strip()
    ])


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

            asm = generate_latency_asm(row)
            init = generate_latency_init(row)

            generated_count = count_generated_instructions(asm)

            if generated_count != 2:
                raise ValueError(          f"{row['name']}: generated {generated_count} "
                    "instructions, expected 2"
                )

            command = [
                "sudo",
                str(wrapper),
                "-march",
                "rv64gcv",
                "-asm",
                asm,
                "-asm_init",
                init,
                "-name",
                f"{row['name']}_latency",
                "-measurement",
                "vector_latency",
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

            print(f"=== {row['name']}: latency ===", flush=True)
            print(shlex.join(command), flush=True)
            subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()