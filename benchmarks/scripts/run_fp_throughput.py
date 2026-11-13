#!/usr/bin/env python3

import argparse
import csv
import shlex
import subprocess
from pathlib import Path



FP_CHAIN_REGISTERS = [
    "ft0",
    "ft1",
    "ft2",
    "ft3",
    "ft4",
    "ft5",
    "ft6",
    "ft7",
]

FP_COMMON_SOURCE = "ft11"

FP_LONG_DESTINATIONS = [
    "ft0",
    "ft1",
    "ft2",
    "ft3",
    "ft4",
    "ft5",
    "ft6",
    "ft7",
]

FP_NUMERATOR = "ft10"
FP_DENOMINATOR = "ft11"

FP_FMA_DESTINATIONS = [
    "ft0",
    "ft1",
    "ft2",
    "ft3",
    "ft4",
    "ft5",
    "ft6",
    "ft7",
    "fa0",
    "fa1",
    "fa2",
    "fa3",
]

FP_FMA_SOURCE_1 = "ft9"
FP_FMA_SOURCE_2 = "ft10"
FP_FMA_SOURCE_3 = "ft11"

INTEGER_DESTINATIONS = [
    "t2",
    "t3",
    "t4",
    "t5",
    "t6",
    "a0",
    "a1",
    "a2",
]

INTEGER_SOURCES = [
    "t2",
    "t3",
    "t4",
    "t5",
    "t6",
    "a0",
    "a1",
    "a2",
]

DEFAULT_CHAIN_COUNTS = [1, 2, 3, 4, 6, 8]
FMA_CHAIN_COUNTS = [1, 2, 3, 4, 6, 8, 10, 12]

def march_for_extension(extension: str) -> str:
    extension = extension.lower()

    march_by_extension = {
        "f": "rv64gc",
        "d": "rv64gc",
    }

    try:
        return march_by_extension[extension]
    except KeyError as error:
        raise ValueError(
            f"unsupported FP extension: {extension}"
        ) from error


def move_instruction(precision: str) -> str:
    if precision == "s":
        return "fmv.w.x"

    if precision == "d":
        return "fmv.d.x"

    raise ValueError(f"unsupported FP precision: {precision}")


def fp_bits(value_name: str, precision: str) -> str:
    values = {
        "s": {
            "half": "0x3f000000",
            "one": "0x3f800000",
            "one_point_five": "0x3fc00000",
            "two": "0x40000000",
            "three": "0x40400000",
            "four": "0x40800000",
            "negative_two": "0xc0000000",
        },
        "d": {
            "half": "0x3fe0000000000000",
            "one": "0x3ff0000000000000",
            "one_point_five": "0x3ff8000000000000",
            "two": "0x4000000000000000",
            "three": "0x4008000000000000",
            "four": "0x4010000000000000",
            "negative_two": "0xc000000000000000",
        },
    }

    try:
        return values[precision][value_name]
    except KeyError as error:
        raise ValueError(
            f"unsupported FP value: "
            f"precision={precision}, value={value_name}"
        ) from error


def generate_throughput_asm(
    row: dict[str, str],
    chain_count: int,
) -> str:
    mnemonic = row["mnemonic"]
    operand_form = row["operand_form"]
    profile = row["input_profile"]

    if profile.startswith("div"):
        destinations = FP_CHAIN_REGISTERS[:chain_count]

        if len(destinations) != chain_count:
            raise ValueError(
                f"{row['name']}: requested {chain_count} destinations, "
                f"but only {len(destinations)} are available"
            )

        return "; ".join(
            f"{mnemonic} {register},{FP_NUMERATOR},{FP_DENOMINATOR}"
            for register in destinations
        )

    if profile.startswith("sqrt"):
        destinations = FP_CHAIN_REGISTERS[:chain_count]

        if len(destinations) != chain_count:
            raise ValueError(
                f"{row['name']}: requested {chain_count} destinations, "
                f"but only {len(destinations)} are available"
            )

        return "; ".join(
            f"{mnemonic} {register},{FP_DENOMINATOR}"
            for register in destinations
        )

    if operand_form == "fd-fs1-fs2-fs3":
        destinations = FP_FMA_DESTINATIONS[:chain_count]

        if len(destinations) != chain_count:
            raise ValueError(
                f"{row['name']}: requested {chain_count} destinations, "
                f"but only {len(destinations)} are available"
            )

        return "; ".join(
            f"{mnemonic} {register},"
            f"{FP_FMA_SOURCE_1},"
            f"{FP_FMA_SOURCE_2},"
            f"{FP_FMA_SOURCE_3}"
            for register in destinations
        )

    if operand_form == "fd-fs1-fs2":
        registers = FP_CHAIN_REGISTERS[:chain_count]

        if len(registers) != chain_count:
            raise ValueError(
                f"{row['name']}: requested {chain_count} chains, "
                f"but only {len(registers)} are available"
            )

        return "; ".join(
            f"{mnemonic} {register},{register},{FP_COMMON_SOURCE}"
            for register in registers
        )
    
    if operand_form == "rd-fs1":
        destinations = INTEGER_DESTINATIONS[:chain_count]

        if len(destinations) != chain_count:
            raise ValueError(
                f"{row['name']}: requested {chain_count} destinations, "
                f"but only {len(destinations)} are available"
            )

        return "; ".join(
            f"{mnemonic} {register},ft11"
            for register in destinations
        )
    
    if operand_form == "fd-rs1":
        destinations = FP_CHAIN_REGISTERS[:chain_count]
        sources = INTEGER_SOURCES[:chain_count]

        if len(destinations) != chain_count:
            raise ValueError(
                f"{row['name']}: insufficient FP destinations"
            )

        if len(sources) != chain_count:
            raise ValueError(
                f"{row['name']}: insufficient integer sources"
            )

        return "; ".join(
            f"{mnemonic} {destination},{source}"
            for destination, source in zip(
                destinations,
                sources,
                strict=True,
            )
        )

    if operand_form == "rd-fs1-fs2":
        destinations = INTEGER_DESTINATIONS[:chain_count]

        if len(destinations) != chain_count:
            raise ValueError(
                f"{row['name']}: requested {chain_count} destinations, "
                f"but only {len(destinations)} are available"
            )

        return "; ".join(
            f"{mnemonic} {register},ft10,ft11"
            for register in destinations
        )
    
    if operand_form == "fd-fs1":
        destinations = FP_CHAIN_REGISTERS[:chain_count]

        if len(destinations) != chain_count:
            raise ValueError(
                f"{row['name']}: requested {chain_count} destinations, "
                f"but only {len(destinations)} are available"
            )

        return "; ".join(
            f"{mnemonic} {destination},ft11"
            for destination in destinations
        )

    raise ValueError(
        f"{row['name']}: unsupported FP throughput operand form: "
        f"{operand_form}"
    )


def generate_add_throughput_init(
    row: dict[str, str],
    chain_count: int,
) -> str:
    precision = row["precision"]
    move = move_instruction(precision)

    instructions = [
        f"li t2,{fp_bits('one', precision)}",
        f"{move} {FP_COMMON_SOURCE},t2",
        f"li t2,{fp_bits('two', precision)}",
    ]

    instructions.extend(
        f"{move} {register},t2"
        for register in FP_CHAIN_REGISTERS[:chain_count]
    )

    return "; ".join(instructions)

def generate_mul_throughput_init(
    row: dict[str, str],
    chain_count: int,
) -> str:
    precision = row["precision"]
    move = move_instruction(precision)

    instructions = [
        f"li t2,{fp_bits('one', precision)}",
        f"{move} {FP_COMMON_SOURCE},t2",
        f"li t2,{fp_bits('one_point_five', precision)}",
    ]

    instructions.extend(
        f"{move} {register},t2"
        for register in FP_CHAIN_REGISTERS[:chain_count]
    )

    return "; ".join(instructions)

def generate_div_throughput_init(row: dict[str, str]) -> str:
    precision = row["precision"]
    move = move_instruction(precision)

    return (
        f"li t2,{fp_bits('three', precision)}; "
        f"{move} {FP_NUMERATOR},t2; "
        f"li t2,{fp_bits('one_point_five', precision)}; "
        f"{move} {FP_DENOMINATOR},t2"
    )

def generate_sqrt_throughput_init(row: dict[str, str]) -> str:
    precision = row["precision"]
    move = move_instruction(precision)

    return (
        f"li t2,{fp_bits('four', precision)}; "
        f"{move} {FP_DENOMINATOR},t2"
    )

def generate_fma_throughput_init(row: dict[str, str]) -> str:
    precision = row["precision"]
    move = move_instruction(precision)

    return (
        f"li t2,{fp_bits('one', precision)}; "
        f"{move} {FP_FMA_SOURCE_1},t2; "
        f"{move} {FP_FMA_SOURCE_2},t2; "
        f"li t2,{fp_bits('half', precision)}; "
        f"{move} {FP_FMA_SOURCE_3},t2"
    )

def generate_sign_minmax_throughput_init(
    row: dict[str, str],
    chain_count: int,
) -> str:
    precision = row["precision"]
    move = move_instruction(precision)

    instructions = [
        f"li t2,{fp_bits('negative_two', precision)}",
        f"{move} {FP_COMMON_SOURCE},t2",
        f"li t2,{fp_bits('one_point_five', precision)}",
    ]

    instructions.extend(
        f"{move} {register},t2"
        for register in FP_CHAIN_REGISTERS[:chain_count]
    )

    return "; ".join(instructions)

def generate_compare_throughput_init(
    row: dict[str, str],
) -> str:
    precision = row["precision"]
    move = move_instruction(precision)

    return (
        f"li t2,{fp_bits('one_point_five', precision)}; "
        f"{move} ft10,t2; "
        f"li t2,{fp_bits('two', precision)}; "
        f"{move} ft11,t2"
    )

def generate_fp_to_integer_init(
    row: dict[str, str],
) -> str:
    precision = row["precision"]
    move = move_instruction(precision)

    return (
        f"li t2,{fp_bits('one_point_five', precision)}; "
        f"{move} ft11,t2"
    )

def generate_integer_to_fp_init(
    row: dict[str, str],
    chain_count: int,
) -> str:
    sources = INTEGER_SOURCES[:chain_count]

    if len(sources) != chain_count:
        raise ValueError(
            f"{row['name']}: requested {chain_count} integer sources, "
            f"but only {len(sources)} are available"
        )

    return "; ".join(
        f"li {register},3"
        for register in sources
    )

def generate_fp_precision_conversion_init(
    row: dict[str, str],
) -> str:
    profile = row["input_profile"]

    if profile == "cvt_d_to_s":
        return (
            f"li t2,{fp_bits('one_point_five', 'd')}; "
            "fmv.d.x ft11,t2"
        )

    if profile == "cvt_s_to_d":
        return (
            f"li t2,{fp_bits('one_point_five', 's')}; "
            "fmv.w.x ft11,t2"
        )

    raise ValueError(
        f"{row['name']}: unsupported FP conversion profile: {profile}"
    )

def generate_throughput_init(
    row: dict[str, str],
    chain_count: int,
) -> str:
    profile = row["input_profile"]

    if profile.startswith(("add", "sub")):
        return generate_add_throughput_init(row, chain_count)

    if profile.startswith("mul"):
        return generate_mul_throughput_init(row, chain_count)

    if profile.startswith("div"):
        return generate_div_throughput_init(row)

    if profile.startswith("sqrt"):
        return generate_sqrt_throughput_init(row)
    
    if profile.startswith("fma"):
        return generate_fma_throughput_init(row)
    
    if profile.startswith(("sign", "minmax")):
        return generate_sign_minmax_throughput_init(row, chain_count)
    
    if profile.startswith("compare"):
        return generate_compare_throughput_init(row)
    
    if profile.startswith(("cvt_s_to_int", "cvt_d_to_int")):
        return generate_fp_to_integer_init(row)

    if profile.startswith(("cvt_int_to_s", "cvt_int_to_d")):
        return generate_integer_to_fp_init(row, chain_count)

    if profile in {"cvt_d_to_s", "cvt_s_to_d"}:
        return generate_fp_precision_conversion_init(row)
    
    if profile.startswith(("class", "move_s_to_x", "move_d_to_x")):
        return generate_fp_to_integer_init(row)

    if profile.startswith(("move_x_to_s", "move_x_to_d")):
        return generate_integer_to_fp_init(row, chain_count)

    raise ValueError(
        f"{row['name']}: unsupported FP input profile: {profile}"
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
            
            march = march_for_extension(row["extension"])
            
            if row["operand_form"] == "fd-fs1-fs2-fs3":
                chain_counts = FMA_CHAIN_COUNTS
            else:
                chain_counts = DEFAULT_CHAIN_COUNTS

            for chain_count in chain_counts:
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
                    (
                        f"{row['name']}_throughput_"
                        f"{chain_count}"
                    ),
                    "-measurement",
                    "fp_throughput",
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