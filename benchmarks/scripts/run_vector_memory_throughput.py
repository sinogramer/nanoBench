#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path


VECTOR_MEMORY_REGISTERS_BY_LMUL = {
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
        "v2",
        "v4",
        "v6",
        "v8",
        "v10",
        "v12",
        "v14",
        "v16",
    ],
    "m4": [
        "v4",
        "v8",
        "v12",
        "v16",
        "v20",
        "v24",
        "v28",
    ],
    "m8": [
        "v0",
        "v8",
        "v16",
        "v24",
    ],
}

MEMORY_COUNTS_BY_LMUL = {
    "m1": [1, 2, 3, 4, 6, 8],
    "m2": [1, 2, 3, 4, 6, 8],
    "m4": [1, 2, 3, 4, 6],
    "m8": [1, 2, 3, 4],
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


def memory_registers(
    row: dict[str, str],
    count: int,
) -> list[str]:
    lmul = row["lmul"]

    try:
        available_registers = (
            VECTOR_MEMORY_REGISTERS_BY_LMUL[lmul]
        )
    except KeyError as error:
        raise ValueError(
            f"{row['name']}: unsupported LMUL: {lmul}"
        ) from error

    registers = available_registers[:count]

    if len(registers) != count:
        raise ValueError(
            f"{row['name']}: requested {count} Vector registers, "
            f"but only {len(registers)} are available"
        )

    return registers


def memory_counts(row: dict[str, str]) -> list[int]:
    lmul = row["lmul"]

    try:
        return MEMORY_COUNTS_BY_LMUL[lmul]
    except KeyError as error:
        raise ValueError(
            f"{row['name']}: unsupported LMUL: {lmul}"
        ) from error


def bytes_per_instruction(row: dict[str, str]) -> int:
    vl = int(row["vl"])
    eew = int(row["eew"])

    if eew <= 0 or eew % 8 != 0:
        raise ValueError(
            f"{row['name']}: EEW must be a positive "
            "multiple of 8"
        )

    return vl * eew // 8


def generate_memory_asm(
    row: dict[str, str],
    count: int,
) -> str:
    registers = memory_registers(row, count)
    mnemonic = row["mnemonic"]

    return "; ".join(
        f"{mnemonic} {register},(s9)"
        for register in registers
    )


def generate_memory_initialization(
    row: dict[str, str],
) -> list[str]:
    byte_count = bytes_per_instruction(row)
    instructions: list[str] = []

    full_doublewords = byte_count // 8
    remaining_bytes = byte_count % 8

    for index in range(full_doublewords):
        instructions.append(
            f"sd zero,{index * 8}(s9)"
        )

    base_offset = full_doublewords * 8

    for index in range(remaining_bytes):
        instructions.append(
            f"sb zero,{base_offset + index}(s9)"
        )

    return instructions


def generate_load_init(
    row: dict[str, str],
) -> str:
    instructions = generate_vector_config(row)
    instructions.extend(
        generate_memory_initialization(row)
    )

    return "; ".join(instructions)


def generate_store_init(
    row: dict[str, str],
    count: int,
) -> str:
    registers = memory_registers(row, count)
    instructions = generate_vector_config(row)

    for index, register in enumerate(registers):
        value = index + 1

        if value > 15:
            raise ValueError(
                f"{row['name']}: vmv.v.i value {value} "
                "is outside the supported range"
            )

        instructions.append(
            f"vmv.v.i {register},{value}"
        )

    instructions.extend(
        generate_memory_initialization(row)
    )

    return "; ".join(instructions)


def generate_memory_init(
    row: dict[str, str],
    count: int,
) -> str:
    kind = row["kind"]

    if kind == "load":
        return generate_load_init(row)

    if kind == "store":
        return generate_store_init(row, count)

    raise ValueError(
        f"{row['name']}: unsupported memory kind: {kind}"
    )


def count_generated_instructions(asm: str) -> int:
    return len([
        instruction
        for instruction in asm.split(";")
        if instruction.strip()
    ])


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

    if args.unroll_count <= 0:
        raise ValueError(
            "--unroll-count must be greater than zero"
        )

    if args.loop_count <= 0:
        raise ValueError(
            "--loop-count must be greater than zero"
        )

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

            if row["input_profile"] not in {
                "unit_stride_load",
                "unit_stride_store",
            }:
                raise ValueError(
                    f"{row['name']}: unsupported input profile: "
                    f"{row['input_profile']}"
                )

            expected_profile = (
                "unit_stride_load"
                if row["kind"] == "load"
                else "unit_stride_store"
            )

            if row["input_profile"] != expected_profile:
                raise ValueError(
                    f"{row['name']}: kind={row['kind']} does not "
                    f"match profile={row['input_profile']}"
                )

            for count in memory_counts(row):
                asm = generate_memory_asm(row, count)
                init = generate_memory_init(row, count)

                generated_count = count_generated_instructions(asm)

                if generated_count != count:
                    raise ValueError(
                        f"{row['name']}: generated "
                        f"{generated_count} instructions, "
                        f"expected {count}"
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
                    f"{row['name']}_throughput_{count}",
                    "-measurement",
                    "vector_memory_throughput",
                    "-instructions_per_block",
                    str(count),
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
                    (
                        f"{row['name']}: count={count}, "
                        f"bytes={bytes_per_instruction(row)}"
                    ),
                )


if __name__ == "__main__":
    main()