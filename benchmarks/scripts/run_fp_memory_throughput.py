#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path


MEMORY_COUNTS = [1, 2, 3, 4, 6, 8]

FP_REGISTERS = [
    "ft0",
    "ft1",
    "ft2",
    "ft3",
    "ft4",
    "ft5",
    "ft6",
    "ft7",
]


def march_for_extension(extension: str) -> str:
    extension = extension.lower()

    if extension in {"f", "d"}:
        return "rv64gc"

    raise ValueError(f"unsupported FP extension: {extension}")


def move_instruction(precision: str) -> str:
    if precision == "s":
        return "fmv.w.x"

    if precision == "d":
        return "fmv.d.x"

    raise ValueError(f"unsupported FP precision: {precision}")


def fp_bits(precision: str) -> str:
    if precision == "s":
        return "0x3fc00000"

    if precision == "d":
        return "0x3ff8000000000000"

    raise ValueError(f"unsupported FP precision: {precision}")


def generate_load_asm(
    mnemonic: str,
    count: int,
    stride: int,
) -> str:
    registers = FP_REGISTERS[:count]

    if len(registers) != count:
        raise ValueError(
            f"requested {count} FP registers, "
            f"but only {len(registers)} are available"
        )

    return "; ".join(
        f"{mnemonic} {register},{index * stride}(s9)"
        for index, register in enumerate(registers)
    )


def generate_store_asm(
    mnemonic: str,
    count: int,
    stride: int,
) -> str:
    registers = FP_REGISTERS[:count]

    if len(registers) != count:
        raise ValueError(
            f"requested {count} FP registers, "
            f"but only {len(registers)} are available"
        )

    return "; ".join(
        f"{mnemonic} {register},{index * stride}(s9)"
        for index, register in enumerate(registers)
    )


def generate_load_init(
    count: int,
    stride: int,
) -> str:
    return "; ".join(
        f"sd zero,{index * stride}(s9)"
        for index in range(count)
    )


def generate_store_init(
    precision: str,
    count: int,
    stride: int,
) -> str:
    move = move_instruction(precision)
    bits = fp_bits(precision)

    instructions = [f"li t2,{bits}"]

    instructions.extend(
        f"{move} {register},t2"
        for register in FP_REGISTERS[:count]
    )

    instructions.extend(
        f"sd zero,{index * stride}(s9)"
        for index in range(count)
    )

    return "; ".join(instructions)


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
    parser.add_argument("--stride", type=int, default=8)
    parser.add_argument("--cpu", type=int, default=0)
    parser.add_argument("--unroll-count", type=int, default=64)
    parser.add_argument("--loop-count", type=int, default=16)
    args = parser.parse_args()

    if args.stride <= 0:
        raise ValueError("--stride must be greater than zero")

    root = args.root.resolve()
    wrapper = root / "nanoBench-riscv.sh"
    config = root / "configs/riscv/x100-basic.txt"
    result = args.result.resolve()
    result.parent.mkdir(parents=True, exist_ok=True)

    with args.spec.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row.get("enabled", "1") != "1":
                continue

            width = int(row["width"])

            if args.stride < width:
                raise ValueError(
                    f"{row['name']}: stride {args.stride} is smaller "
                    f"than access width {width}"
                )

            march = march_for_extension(row["extension"])

            for count in MEMORY_COUNTS:
                if row["kind"] == "load":
                    asm = generate_load_asm(
                        row["mnemonic"],
                        count,
                        args.stride,
                    )
                    init = generate_load_init(
                        count,
                        args.stride,
                    )
                elif row["kind"] == "store":
                    asm = generate_store_asm(
                        row["mnemonic"],
                        count,
                        args.stride,
                    )
                    init = generate_store_init(
                        row["precision"],
                        count,
                        args.stride,
                    )
                else:
                    raise ValueError(
                        f"{row['name']}: unsupported memory kind: "
                        f"{row['kind']}"
                    )

                generated_count = count_generated_instructions(asm)

                if generated_count != count:
                    raise ValueError(
                        f"{row['name']}: generated "
                        f"{generated_count} instructions, expected {count}"
                    )

                name = (
                    f"{row['name']}_throughput_{count}_"
                    f"stride_{args.stride}"
                )

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
                    name,
                    "-measurement",
                    "fp_memory_throughput",
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
                        f"stride={args.stride}"
                    ),
                )


if __name__ == "__main__":
    main()