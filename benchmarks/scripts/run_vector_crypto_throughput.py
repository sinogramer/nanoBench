
#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path


CHAIN_COUNTS = [1, 2, 3, 4, 6, 8]

DESTINATIONS_BY_FORM = {
    "vd-vs2": [
        "v2",
        "v3",
        "v4",
        "v5",
        "v6",
        "v7",
        "v8",
        "v9",
    ],
    "vd-vs2-vs1": [
        "v3",
        "v4",
        "v5",
        "v6",
        "v7",
        "v8",
        "v9",
        "v10",
    ],
}

SOURCE_1 = "v1"
SOURCE_2 = "v2"

INITIAL_VALUES = [
    3,
    5,
    7,
    9,
    11,
    13,
    15,
    -15,
]


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


def selected_destinations(
    row: dict[str, str],
    chain_count: int,
) -> list[str]:

    operand_form = row["operand_form"]

    try:
        available = DESTINATIONS_BY_FORM[operand_form]
    except KeyError as error:
        raise ValueError(
            f"{row['name']}: unsupported Crypto operand form: "
            f"{operand_form}"
        ) from error

    destinations = available[:chain_count]

    if len(destinations) != chain_count:
        raise ValueError(
            f"{row['name']}: requested {chain_count} chains, "
            f"but only {len(destinations)} are available"
        )

    return destinations


def generate_throughput_asm(
    row: dict[str, str],
    chain_count: int,
) -> str:

    mnemonic = row["mnemonic"]
    operand_form = row["operand_form"]
    destinations = selected_destinations(row, chain_count)

    if operand_form == "vd-vs2":
        return "; ".join(
            f"{mnemonic} {destination},{SOURCE_1}"
            for destination in destinations
        )

    if operand_form == "vd-vs2-vs1":
        return "; ".join(
            f"{mnemonic} {destination},{SOURCE_2},{SOURCE_1}"
            for destination in destinations
        )

    raise ValueError(
        f"{row['name']}: unsupported Crypto operand form: "
        f"{operand_form}"
    )


def destination_initializers(
    row: dict[str, str],
    destinations: list[str],
) -> list[str]:

    destination_count = len(destinations)

    if destination_count > len(INITIAL_VALUES):
        raise ValueError(
            f"{row['name']}: insufficient destination "
            "initializers"
        )

    values = INITIAL_VALUES[:destination_count]

    return [
        f"vmv.v.i {destination},{value}"
        for destination, value in zip(
            destinations,
            values,
            strict=True,
        )
    ]


def generate_throughput_init(
    row: dict[str, str],
    chain_count: int,
) -> str:

    operand_form = row["operand_form"]
    destinations = selected_destinations(row, chain_count)
    instructions = generate_vector_config(row)

    instructions.append(f"vmv.v.i {SOURCE_1},1")

    if operand_form == "vd-vs2-vs1":
        instructions.append(f"vmv.v.i {SOURCE_2},2")
    elif operand_form != "vd-vs2":
        raise ValueError(
            f"{row['name']}: unsupported Crypto operand form: "
            f"{operand_form}"
        )

    instructions.extend(
        destination_initializers(row, destinations)
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

    subprocess.run(
        command,
        cwd=root,
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )

    parser.add_argument(
        "--spec",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--result",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--cpu",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--unroll-count",
        type=int,
        default=64,
    )

    parser.add_argument(
        "--loop-count",
        type=int,
        default=16,
    )

    args = parser.parse_args()

    root = args.root.resolve()
    wrapper = root / "nanoBench-riscv.sh"
    config = root / "configs/riscv/x100-basic.txt"

    result = args.result.resolve()
    result.parent.mkdir(parents=True, exist_ok=True)

    with args.spec.open(
        newline="",
        encoding="utf-8",
    ) as file:

        for row in csv.DictReader(file):

            if row.get("enabled", "1") != "1":
                continue

            if row.get("throughput", "1") != "1":
                continue

            validate_crypto_config(row)

            march = march_for_extension(row["extension"])

            for chain_count in CHAIN_COUNTS:

                asm = generate_throughput_asm(
                    row,
                    chain_count,
                )

                init = generate_throughput_init(
                    row,
                    chain_count,
                )

                generated_count = count_generated_instructions(
                    asm
                )

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
                    march,
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
                    "vector_crypto_throughput",
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

                run_command(
                    command,
                    root,
                    (
                        f"{row['name']}: throughput, "
                        f"chains={chain_count}"
                    ),
                )


if __name__ == "__main__":
    main()
