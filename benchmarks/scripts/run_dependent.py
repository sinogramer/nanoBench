#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path

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

def generate_latency_asm(row: dict[str, str]) -> str:
    mnemonic = row["mnemonic"]
    operand_form = row["operand_form"]
    operand_value = row.get("operand_value", "")

    if operand_form == "rd-rs1-rs2":
        return (
            f"{mnemonic} t5, t4, t3; "
            f"{mnemonic} t4, t5, t3"
        )

    if operand_form in {"rd-rs1-imm", "rd-rs1-shamt"}:
        if operand_value == "":
            raise ValueError(
                f"{row['name']}: operand_value is required"
            )

        return (
            f"{mnemonic} t5, t4, {operand_value}; "
            f"{mnemonic} t4, t5, {operand_value}"
        )
    
    if operand_form == "rd-rs1":
        return (
            f"{mnemonic} t5, t4; "
            f"{mnemonic} t4, t5"
        )

    raise ValueError(
        f"{row['name']}: unsupported latency operand form: "
        f"{operand_form}"
    )


def generate_latency_init(row: dict[str, str]) -> str:
    if row["operand_form"] == "rd-rs1":
        return (
            "li t3, 3; "
            "li t4, 0x123456789abcdef0; "
            "li t5, 0x0fedcba987654321"
        )

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
            
            if row.get("latency", "1") != "1":
                continue

            name = row["name"]
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