#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path


DESTINATION_BY_FORM = {
    "vd-vs2": "v2",
    "vd-vs2-vs1": "v3",
}

SOURCE_1 = "v1"
SOURCE_2 = "v2"


def march_for_extension(extension: str) -> str:
    march_by_extension = {
        "zvkned": "rv64gcv_zvkned",
        "zvkg": "rv64gcv_zvkg",
    }

    try:
        return march_by_extension[extension.lower()]
    except KeyError as error:
        raise ValueError(
            f"unsupported Vector Crypto extension: {extension}"
        ) from error


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


def validate_crypto_config(row: dict[str, str]) -> None:
    sew = int(row["sew"])
    vl = int(row["vl"])
    egw = int(row["egw"])
    vector_bits = sew * vl

    if sew != 32:
        raise ValueError(
            f"{row['name']}: current Crypto generator "
            f"requires SEW=32, received {sew}"
        )

    if egw <= 0 or vector_bits % egw != 0:
        raise ValueError(
            f"{row['name']}: vector width {vector_bits} is not "
            f"a multiple of EGW {egw}"
        )

    if vl % 4 != 0:
        raise ValueError(
            f"{row['name']}: VL must be a multiple of four"
        )


def generate_latency_asm(row: dict[str, str]) -> str:
    mnemonic = row["mnemonic"]
    operand_form = row["operand_form"]

    try:
        destination = DESTINATION_BY_FORM[operand_form]
    except KeyError as error:
        raise ValueError(
            f"{row['name']}: unsupported Crypto operand form: "
            f"{operand_form}"
        ) from error

    if operand_form == "vd-vs2":
        return f"{mnemonic} {destination},{SOURCE_1}"

    if operand_form == "vd-vs2-vs1":
        return (
            f"{mnemonic} {destination},{SOURCE_2},{SOURCE_1}"
        )

    raise ValueError(
        f"{row['name']}: unsupported Crypto operand form: "
        f"{operand_form}"
    )


def generate_latency_init(row: dict[str, str]) -> str:
    operand_form = row["operand_form"]
    instructions = generate_vector_config(row)

    if operand_form == "vd-vs2":
        instructions.extend([
            f"vmv.v.i {SOURCE_1},1",
            "vmv.v.i v2,2",
        ])
    elif operand_form == "vd-vs2-vs1":
        instructions.extend([
            f"vmv.v.i {SOURCE_1},1",
            f"vmv.v.i {SOURCE_2},2",
            "vmv.v.i v3,3",
        ])
    else:
        raise ValueError(
            f"{row['name']}: unsupported Crypto operand form: "
            f"{operand_form}"
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

            validate_crypto_config(row)

            asm = generate_latency_asm(row)
            init = generate_latency_init(row)

            generated_count = count_generated_instructions(asm)

            if generated_count != 1:
                raise ValueError(
                    f"{row['name']}: generated {generated_count} "
                    "instructions, expected 1"
                )

            command = [
                "sudo",
                str(wrapper),
                "-march",
                march_for_extension(row["extension"]),
                "-asm",
                asm,
                "-asm_init",
                init,
                "-name",
                f"{row['name']}_latency",
                "-measurement",
                "vector_crypto_latency",
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

            run_command(
                command,
                root,
                f"{row['name']}: latency",
            )


if __name__ == "__main__":
    main()