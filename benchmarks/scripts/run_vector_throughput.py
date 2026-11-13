#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path


VECTOR_COMMON_SOURCE_BY_LMUL = {
    "m1": "v1",
    "m2": "v2",
    "m4": "v4",
    "m8": "v0",
}

VECTOR_CHAIN_REGISTERS_BY_LMUL = {
    "m1": [
        "v2",
        "v3",
        "v4",
        "v5",
        "v6",
        "v7",
        "v8",
        "v9",
    ],
    "m2": [
        "v4",
        "v6",
        "v8",
        "v10",
        "v12",
        "v14",
        "v16",
        "v18",
    ],
    "m4": [
        "v8",
        "v12",
        "v16",
        "v20",
        "v24",
        "v28",
    ],
    "m8": [
        "v8",
        "v16",
        "v24",
    ],
}

CHAIN_COUNTS_BY_LMUL = {
    "m1": [1, 2, 3, 4, 6, 8],
    "m2": [1, 2, 3, 4, 6, 8],
    "m4": [1, 2, 3, 4, 6],
    "m8": [1, 2, 3],
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

VECTOR_MUL_INITIAL_VALUES = [
    5,
    7,
    9,
    11,
    13,
    15,
    -15,
    -13,
]


def generate_vector_config(row: dict[str, str]) -> list:
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


def vector_registers(
    row: dict[str, str],
) -> tuple[str, list[str]]:
    lmul = row["lmul"]

    try:
        common_source = VECTOR_COMMON_SOURCE_BY_LMUL[lmul]
        chain_registers = VECTOR_CHAIN_REGISTERS_BY_LMUL[lmul]
    except KeyError as error:
        raise ValueError(
            f"{row['name']}: unsupported LMUL: {lmul}"
        ) from error

    return common_source, chain_registers


def chain_counts_for_row(
    row: dict[str, str],
) -> list:
    lmul = row["lmul"]

    try:
        return CHAIN_COUNTS_BY_LMUL[lmul]
    except KeyError as error:
        raise ValueError(
            f"{row['name']}: unsupported LMUL: {lmul}"
        ) from error


def selected_chain_registers(
    row: dict[str, str],
    chain_count: int,
) -> tuple[str, list[str]]:
    common_source, available_registers = vector_registers(row)
    registers = available_registers[:chain_count]

    if len(registers) != chain_count:
        raise ValueError(
            f"{row['name']}: requested {chain_count} chains, "
            f"but only {len(registers)} are available"
        )

    return common_source, registers


def generate_throughput_asm(
    row: dict[str, str],
    chain_count: int,
) -> str:
    mnemonic = row["mnemonic"]
    operand_form = row["operand_form"]
    common_source, registers = selected_chain_registers(
        row,
        chain_count,
    )

    if operand_form == "vd-vs2-vs1":
        return "; ".join(
            f"{mnemonic} {register},{register},{common_source}"
            for register in registers
        )

    if operand_form == "vd-vs2-rs1":
        return "; ".join(
            f"{mnemonic} {register},{register},"
            f"{VECTOR_SCALAR_SOURCE}"
            for register in registers
        )

    raise ValueError(
        f"{row['name']}: unsupported Vector operand form: "
        f"{operand_form}"
    )


def vector_vector_initial_values(
    profile: str,
) -> tuple[int, int]:
    if profile == "integer_mul":
        return 3, 5

    if profile in {
        "integer_add",
        "integer_logic",
        "integer_minmax",
    }:
        return 1, 2

    raise ValueError(
        f"unsupported Vector-Vector profile: {profile}"
    )


def vector_scalar_initial_values(
    profile: str,
) -> tuple[int, int]:
    if profile == "integer_mul_vx":
        return 3, 5

    if profile in {
        "integer_add_vx",
        "integer_logic_vx",
        "integer_minmax_vx",
    }:
        return 1, 2

    raise ValueError(
        f"unsupported Vector-Scalar profile: {profile}"
    )


def generate_chain_initializers(
    registers: list[str],
    first_value: int,
    step: int,
) -> list[str]:
    return [
        f"vmv.v.i {register},{first_value + step * index}"
        for index, register in enumerate(registers)
    ]

def validate_vector_immediate(
    row: dict[str, str],
    value: int,
) -> None:
    if not -16 <= value <= 15:
        raise ValueError(
            f"{row['name']}: vmv.v.i immediate {value} "
            "is outside the valid range -16..15"
        )

def generate_mul_chain_initializers(
    row: dict[str, str],
    registers: list[str],
) -> list[str]:
    register_count = len(registers)

    if register_count > len(VECTOR_MUL_INITIAL_VALUES):
        raise ValueError(
            f"{row['name']}: requested {register_count} multiply "
            f"initializers, but only "
            f"{len(VECTOR_MUL_INITIAL_VALUES)} are available"
        )

    values = VECTOR_MUL_INITIAL_VALUES[:register_count]

    instructions = []

    for register, value in zip(
        registers,
        values,
        strict=True,
    ):
        validate_vector_immediate(row, value)
        instructions.append(
            f"vmv.v.i {register},{value}"
        )

    return instructions


def generate_vector_vector_throughput_init(
    row: dict[str, str],
    chain_count: int,
) -> str:
    profile = row["input_profile"]
    common_source, registers = selected_chain_registers(
        row,
        chain_count,
    )

    common_value, first_value = (
        vector_vector_initial_values(profile)
    )

    instructions = generate_vector_config(row)
    instructions.append(
        f"vmv.v.i {common_source},{common_value}"
    )

    if profile == "integer_mul":
        instructions.extend(
            generate_mul_chain_initializers(row, registers)
        )
    else:
        instructions.extend(
            generate_chain_initializers(
                registers,
                first_value,
                1,
            )
        )

    return "; ".join(instructions)


def generate_vector_scalar_throughput_init(
    row: dict[str, str],
    chain_count: int,
) -> str:
    profile = row["input_profile"]
    _, registers = selected_chain_registers(
        row,
        chain_count,
    )

    scalar_value, first_value = (
        vector_scalar_initial_values(profile)
    )

    instructions = generate_vector_config(row)
    instructions.append(
        f"li {VECTOR_SCALAR_SOURCE},{scalar_value}"
    )

    if profile == "integer_mul_vx":
        instructions.extend(
            generate_mul_chain_initializers(row, registers)
        )
    else:
        instructions.extend(
            generate_chain_initializers(
                registers,
                first_value,
                1,
            )
        )

    return "; ".join(instructions)


def generate_throughput_init(
    row: dict[str, str],
    chain_count: int,
) -> str:
    profile = row["input_profile"]
    operand_form = row["operand_form"]

    if operand_form == "vd-vs2-vs1":
        if profile not in VECTOR_VECTOR_PROFILES:
            raise ValueError(
                f"{row['name']}: profile {profile} is not valid "
                f"for operand form {operand_form}"
            )

        return generate_vector_vector_throughput_init(
            row,
            chain_count,
        )

    if operand_form == "vd-vs2-rs1":
        if profile not in VECTOR_SCALAR_PROFILES:
            raise ValueError(
                f"{row['name']}: profile {profile} is not valid "
                f"for operand form {operand_form}"
            )

        return generate_vector_scalar_throughput_init(
            row,
            chain_count,
        )

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

            if row.get("throughput", "1") != "1":
                continue

            chain_counts = chain_counts_for_row(row)

            for chain_count in chain_counts:
                asm = generate_throughput_asm(
                    row,
                    chain_count,
                )
                init = generate_throughput_init(
                    row,
                    chain_count,
                )

                generated_count = count_generated_instructions(asm)

                if generated_count != chain_count:
                    raise ValueError(
                        f"{row['name']}: generated "
                        f"{generated_count} instructions, "
                        f"expected {chain_count}"
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
                    (
                        f"{row['name']}_throughput_"
                        f"{chain_count}"
                    ),
                    "-measurement",
                    "vector_throughput",
                    "-instructions_per_block",
                    str(chain_count),
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

                print(
                    f"=== {row['name']}: throughput, "
                    f"chains={chain_count} ===",
                    flush=True,
                )
                print(shlex.join(command), flush=True)
                subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()