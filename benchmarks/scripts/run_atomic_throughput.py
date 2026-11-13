#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path


ATOMIC_COUNTS = [1, 4, 8, 12]
ADDRESS_REGISTERS = [
    "t2", "t3", "t4", "t5", "t6",
    "a0", "a1", "a2",
    "a4", "a5", "a6", "a7",
]
VALUE_REGISTER = "a3"

LAYOUTS = [
    "same",
    "distinct_word_same_line",
    "distinct_line",
]


def generate_same_address_asm(mnemonic: str, count: int) -> str:
    return "; ".join(
        f"{mnemonic} zero,{VALUE_REGISTER},(s9)"
        for _ in range(count)
    )


def generate_same_address_init() -> str:
    return f"li {VALUE_REGISTER},1; sd zero,0(s9)"


def stride_for_layout(layout: str) -> int:
    if layout == "distinct_word_same_line":
        return 8

    if layout == "distinct_line":
        return 64

    raise ValueError(f"layout has no stride: {layout}")


def generate_distinct_asm(mnemonic: str, count: int) -> str:
    return "; ".join(
        f"{mnemonic} zero,{VALUE_REGISTER},({register})"
        for register in ADDRESS_REGISTERS[:count]
    )


def generate_distinct_init(count: int, stride: int) -> str:
    instructions = [f"li {VALUE_REGISTER},1"]

    for index, register in enumerate(ADDRESS_REGISTERS[:count]):
        offset = index * stride
        instructions.append(f"addi {register},s9,{offset}")
        instructions.append(f"sd zero,{offset}(s9)")

    return "; ".join(instructions)


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
    parser.add_argument("--layouts", nargs="+", choices=LAYOUTS, default=LAYOUTS)
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

            for layout in args.layouts:
                for count in ATOMIC_COUNTS:
                    if layout == "same":
                        asm = generate_same_address_asm(
                            row["mnemonic"],
                            count,
                        )
                        init = generate_same_address_init()
                    else:
                        stride = stride_for_layout(layout)
                        asm = generate_distinct_asm(
                            row["mnemonic"],
                            count,
                        )
                        init = generate_distinct_init(
                            count,
                            stride,
                        )

                    name = (
                        f"{row['name']}_{layout}_"
                        f"throughput_{count}"
                    )

                    command = [
                        "sudo",
                        str(wrapper),
                        "-march",
                        "rv64gc",
                        "-asm",
                        asm,
                        "-asm_init",
                        init,
                        "-name",
                        name,
                        "-measurement",
                        "atomic_throughput",
                        "-instructions_per_block",
                        str(count),
                        "-config",
                        str(config),
                        "-fixed_counters",
                        "-unroll_count",
                        "64",
                        "-loop_count",
                        "16",
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
                        f"{row['name']}: {layout}, count={count}",
                    )


if __name__ == "__main__":
    main()