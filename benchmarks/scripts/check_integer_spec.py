#!/usr/bin/env python3

import argparse
import csv
import subprocess
import tempfile
from pathlib import Path


def march_for_extension(extension: str) -> str:
    march_by_extension = {
        "i": "rv64gc",
        "m": "rv64gc",
        "zba": "rv64gc_zba",
        "zbb": "rv64gc_zbb",
        "zbc": "rv64gc_zbc",
        "zbs": "rv64gc_zbs",
    }

    extension = extension.lower()

    try:
        return march_by_extension[extension]
    except KeyError as error:
        raise ValueError(
            f"unsupported ISA extension: {extension}"
        ) from error


def sample_instruction(row: dict[str, str]) -> str:
    mnemonic = row["mnemonic"]
    operand_form = row["operand_form"]
    value = row.get("operand_value", "")

    if operand_form == "rd-rs1-rs2":
        return f"{mnemonic} t5,t4,t3"

    if operand_form in {"rd-rs1-imm", "rd-rs1-shamt"}:
        return f"{mnemonic} t5,t4,{value}"

    if operand_form == "rd-rs1":
        return f"{mnemonic} t5,t4"

    if operand_form == "rd-imm":
        return f"{mnemonic} t5,{value}"

    raise ValueError(
        f"{row['name']}: unsupported operand form: {operand_form}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()

    failures = 0

    with args.spec.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row.get("enabled", "1") != "1":
                continue

            instruction = sample_instruction(row)
            march = march_for_extension(row["extension"])

            assembly = (
                ".text\n"
                ".option norvc\n"
                ".globl benchmark\n"
                "benchmark:\n"
                f"    {instruction}\n"
                "    ret\n"
            )

            with tempfile.TemporaryDirectory() as directory:
                directory_path = Path(directory)
                source = directory_path / "test.S"
                output = directory_path / "test.o"
                source.write_text(assembly, encoding="utf-8")

                result = subprocess.run(
                    [
                        args.cc,
                        "-c",
                        f"-march={march}",
                        "-mabi=lp64d",
                        "-o",
                        str(output),
                        str(source),
                    ],
                    capture_output=True,
                    text=True,
                )

            if result.returncode == 0:
                print(f"OK   {row['name']}: {instruction}")
            else:
                failures += 1
                print(f"FAIL {row['name']}: {instruction}")
                print(result.stderr.rstrip())

    if failures != 0:
        raise SystemExit(f"{failures} instruction(s) failed")


if __name__ == "__main__":
    main()