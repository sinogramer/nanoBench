#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path

DIV_DESTINATIONS = ["t4", "t5", "t6", "a0", "a1", "a2", "a3", "a4"]
NUMERATOR_REGISTER = "t2"
DENOMINATOR_REGISTER = "t3"
DIV_COUNTS = [1, 2, 3, 4, 6, 8]


def generate_latency_asm(row: dict[str, str]) -> tuple[str, int]:
    mnemonic = row["mnemonic"]
    operation = row["operation"]
    width = int(row["width"])

    if operation == "div":
        restore = "mulw" if width == 32 else "mul"
        asm = (
            f"{mnemonic} t5, t4, t3; "
            f"{restore} t4, t5, t3"
        )
        restore_latency = 2 if width == 32 else 3
        return asm, restore_latency

    if operation == "rem":
        restore = "addiw" if width == 32 else "addi"
        restore_value = row["remainder_restore"]

        asm = (
            f"{mnemonic} t5, t4, t3; "
            f"{restore} t4, t5, {restore_value}"
        )
        return asm, 1

    raise ValueError(f"unsupported operation: {operation}")


def generate_latency_init(row: dict[str, str]) -> str:
    return (
        f"li t3, {row['denominator']}; "
        f"li t4, {row['numerator']}; "
        "li t5, 0"
    )


def generate_throughput_asm(
    row: dict[str, str],
    instruction_count: int,
) -> str:
    mnemonic = row["mnemonic"]

    return "; ".join(
        f"{mnemonic} {rd}, {NUMERATOR_REGISTER}, "
        f"{DENOMINATOR_REGISTER}"
        for rd in DIV_DESTINATIONS[:instruction_count]
    )


def generate_throughput_init(row: dict[str, str]) -> str:
    return (
        f"li {NUMERATOR_REGISTER}, {row['numerator']}; "
        f"li {DENOMINATOR_REGISTER}, {row['denominator']}"
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
    parser.add_argument("--latency-result", type=Path, required=True)
    parser.add_argument("--throughput-result", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=0)
    args = parser.parse_args()

    root = args.root.resolve()
    wrapper = root / "nanoBench-riscv.sh"
    config = root / "configs/riscv/x100-basic.txt"

    latency_result = args.latency_result.resolve()
    throughput_result = args.throughput_result.resolve()

    latency_result.parent.mkdir(parents=True, exist_ok=True)
    throughput_result.parent.mkdir(parents=True, exist_ok=True)

    with args.spec.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row.get("enabled", "1") != "1":
                continue

            latency_asm, restore_latency = generate_latency_asm(row)
            latency_init = generate_latency_init(row)

            latency_command = [
                "sudo",
                str(wrapper),
                "-asm",
                latency_asm,
                "-asm_init",
                latency_init,
                "-name",
                f"{row['name']}_latency_restore_{restore_latency}",
                "-measurement",
                "division_latency",
                "-instructions_per_block",
                "1",
                "-config",
                str(config),
                "-fixed_counters",
                "-unroll_count",
                "64",
                "-loop_count",
                "16",
                "-cpu",
                str(args.cpu),
                "-median",
                "-csv",
                str(latency_result),
            ]

            run_command(
                latency_command,
                root,
                f"{row['name']}: latency",
            )

            for instruction_count in DIV_COUNTS:
                throughput_asm = generate_throughput_asm(
                    row,
                    instruction_count,
                )

                throughput_init = generate_throughput_init(row)

                throughput_command = [
                    "sudo",
                    str(wrapper),
                    "-asm",
                    throughput_asm,
                    "-asm_init",
                    throughput_init,
                    "-name",
                    (
                        f"{row['name']}_throughput_"
                        f"{instruction_count}"
                    ),
                    "-measurement",
                    "throughput",
                    "-instructions_per_block",
                    str(instruction_count),
                    "-config",
                    str(config),
                    "-fixed_counters",
                    "-unroll_count",
                    "64",
                    "-loop_count",
                    "16",
                    "-cpu",
                    str(args.cpu),
                    "-median",
                    "-csv",
                    str(throughput_result),
                ]

                run_command(
                    throughput_command,
                    root,
                    (
                        f"{row['name']}: throughput, "
                        f"count={instruction_count}"
                    ),
                )


if __name__ == "__main__":
    main()