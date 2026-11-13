#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path

CHAIN_REGISTERS = ["t3", "t4", "t5", "t6", "a0", "a1", "a2", "a3"]
CHAIN_COUNTS = [1, 2, 3, 4, 6, 8]
COMMON_SOURCE = "t2"

def march_for_extension(extension: str) -> str:
    extension = extension.lower()

    march_by_extension = {
        "i": "rv64gc",
        "m": "rv64gc",
        "zba": "rv64gc_zba",
        "zbb": "rv64gc_zbb",
        "zbc": "rv64gc_zbc",
        "zbs": "rv64gc_zbs",
    }

    try:
        return march_by_extension[extension]
    except KeyError as error:
        raise ValueError(
            f"unsupported ISA extension: {extension}"
        ) from error

def generate_throughput_asm(
    row: dict[str, str],
    chain_count: int,
) -> str:
    mnemonic = row["mnemonic"]
    operand_form = row["operand_form"]
    operand_value = row.get("operand_value", "")
    registers = CHAIN_REGISTERS[:chain_count]

    if operand_form == "rd-rs1-rs2":
        return "; ".join(
            f"{mnemonic} {rd}, {rd}, {COMMON_SOURCE}"
            for rd in registers
        )

    if operand_form in {"rd-rs1-imm", "rd-rs1-shamt"}:
        if operand_value == "":
            raise ValueError(
                f"{row['name']}: operand_value is required"
            )

        return "; ".join(
            f"{mnemonic} {rd}, {rd}, {operand_value}"
            for rd in registers
        )

    if operand_form == "rd-rs1":
        return "; ".join(
            f"{mnemonic} {rd}, {rd}"
            for rd in registers
        )

    if operand_form == "rd-imm":
        if operand_value == "":
            raise ValueError(
                f"{row['name']}: operand_value is required"
            )

        return "; ".join(
            f"{mnemonic} {rd}, {operand_value}"
            for rd in registers
        )

    raise ValueError(
        f"{row['name']}: unsupported throughput operand form: "
        f"{operand_form}"
    )


def generate_throughput_init(
    row: dict[str, str],
    chain_count: int,
) -> str:
    operand_form = row["operand_form"]
    instructions = []

    if operand_form == "rd-rs1-rs2":
        instructions.append(f"li {COMMON_SOURCE}, 3")

    if operand_form != "rd-imm":
        for index, register in enumerate(
            CHAIN_REGISTERS[:chain_count],
            start=1,
        ):
            instructions.append(f"li {register}, {index * 5}")

    if not instructions:
        return "nop"

    return "; ".join(instructions)


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
            for chain_count in CHAIN_COUNTS:
                march = march_for_extension(row["extension"])
                asm = generate_throughput_asm(row, chain_count)
                init = generate_throughput_init(row, chain_count)

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
                    f"{row['name']}_throughput_{chain_count}",
                    "-measurement",
                    "throughput",
                    "-instructions_per_block",
                    str(chain_count),
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

                print(f"=== {row['name']}: chains={chain_count} ===", flush=True)
                print(shlex.join(command), flush=True)
                subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()