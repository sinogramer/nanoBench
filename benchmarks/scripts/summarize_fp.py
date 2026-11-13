#!/usr/bin/env python3

import argparse
import csv
import math
import re
from collections import defaultdict
from pathlib import Path


def parse_latency_code(code: str) -> str:
    suffix = "_latency"

    if not code.endswith(suffix):
        raise ValueError(f"invalid FP latency benchmark name: {code}")

    return code[:-len(suffix)]


def parse_throughput_code(code: str) -> tuple[str, int]:
    match = re.fullmatch(r"(.+)_throughput_(\d+)", code)

    if match is None:
        raise ValueError(f"invalid FP throughput benchmark name: {code}")

    return match.group(1), int(match.group(2))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def read_spec(path: Path) -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}

    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row.get("enabled", "1") != "1":
                continue

            name = row["name"]

            if name in entries:
                raise ValueError(f"duplicate FP spec entry: {name}")

            entries[name] = row

    return entries


def close_enough(
    value: float,
    reference: float,
    relative_tolerance: float,
) -> bool:
    return math.isclose(
        value,
        reference,
        rel_tol=relative_tolerance,
        abs_tol=0.01,
    )


def format_samples(samples: list[tuple[int, float]]) -> str:
    return ";".join(
        f"{chains}:{value:.6f}"
        for chains, value in sorted(samples)
    )


def get_event_value(
    values: dict[str, dict[int, float]],
    instruction: str,
    chain_count: int,
) -> float:
    return values[instruction].get(chain_count, float("nan"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--latency", type=Path, required=True)
    parser.add_argument("--throughput", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=0.03)
    parser.add_argument("--min-chains", type=int, default=2)
    parser.add_argument("--long-latency", type=Path)
    args = parser.parse_args()

    if args.tolerance < 0.0:
        raise ValueError("--tolerance must not be negative")

    if args.min_chains <= 0:
        raise ValueError("--min-chains must be greater than zero")

    spec = read_spec(args.spec)

    latency_by_instruction: dict[str, float] = {}

    throughput_by_instruction: dict[
        str,
        list[tuple[int, float]],
    ] = defaultdict(list)

    retired_by_instruction: dict[
        str,
        dict[int, float],
    ] = defaultdict(dict)

    issued_by_instruction: dict[
        str,
        dict[int, float],
    ] = defaultdict(dict)

    fp_by_instruction: dict[
        str,
        dict[int, float],
    ] = defaultdict(dict)

    alu_by_instruction: dict[
        str,
        dict[int, float],
    ] = defaultdict(dict)

    seen_latency: set[tuple[str, str]] = set()
    seen_throughput: set[tuple[str, int, str]] = set()

    for row in read_csv(args.latency):
        if row["measurement"] != "fp_latency":
            continue

        instruction = parse_latency_code(row["code"])
        event = row["event"]
        key = (instruction, event)

        if key in seen_latency:
            raise ValueError(
                f"duplicate FP latency result: "
                f"instruction={instruction}, event={event}"
            )

        seen_latency.add(key)

        if event == "Core cycles":
            latency_by_instruction[instruction] = float(
                row["value_per_instruction"]
            )
    if args.long_latency is not None:
        for row in read_csv(args.long_latency):
            if row["measurement"] != "fp_long_latency":
                continue

            if row["event"] != "Core cycles":
                continue

            match = re.fullmatch(
                r"(.+)_latency_restore_(\d+)",
                row["code"],
            )

            if match is None:
                raise ValueError(
                    f"invalid FP long-latency benchmark name: "
                    f"{row['code']}"
                )

            instruction = match.group(1)
            restore_latency = float(match.group(2))
            measured_cycles = float(row["value_per_instruction"])
            latency = measured_cycles - restore_latency

            if latency < 0.0:
                raise ValueError(
                    f"negative FP latency: instruction={instruction}, "
                    f"measured={measured_cycles}, "
                    f"restore={restore_latency}"
                )

            if instruction in latency_by_instruction:
                raise ValueError(
                    f"duplicate FP latency result: {instruction}"
                )

            latency_by_instruction[instruction] = latency

    for row in read_csv(args.throughput):
        if row["measurement"] != "fp_throughput":
            continue

        instruction, chain_count = parse_throughput_code(row["code"])
        event = row["event"]
        key = (instruction, chain_count, event)

        if key in seen_throughput:
            raise ValueError(
                f"duplicate FP throughput result: "
                f"instruction={instruction}, "
                f"chains={chain_count}, event={event}"
            )

        seen_throughput.add(key)
        value = float(row["value_per_instruction"])

        if event == "Core cycles":
            if value <= 0.0:
                raise ValueError(
                    f"invalid FP cycle value: "
                    f"instruction={instruction}, "
                    f"chains={chain_count}, value={value}"
                )

            throughput_by_instruction[instruction].append(
                (chain_count, value)
            )
        elif event == "Instructions retired":
            retired_by_instruction[instruction][chain_count] = value
        elif event == "Issued instructions":
            issued_by_instruction[instruction][chain_count] = value
        elif event == "FP instructions":
            fp_by_instruction[instruction][chain_count] = value
        elif event == "ALU instructions":
            alu_by_instruction[instruction][chain_count] = value

    fieldnames = [
        "instruction",
        "mnemonic",
        "extension",
        "precision",
        "operand_form",
        "input_profile",
        "latency",
        "reciprocal_throughput",
        "max_throughput",
        "saturation_chains",
        "retired_per_instruction",
        "issued_event_per_instruction",
        "fp_event_per_instruction",
        "alu_event_per_instruction",
        "throughput_samples",
    ]

    instruction_names = (
        set(latency_by_instruction)
        | set(throughput_by_instruction)
    )

    output_rows: list[dict[str, object]] = []

    for instruction in sorted(instruction_names):
        if instruction not in spec:
            raise ValueError(
                f"FP result has no matching spec entry: {instruction}"
            )

        samples = sorted(
            throughput_by_instruction.get(instruction, [])
        )

        if not samples:
            print(f"warning: no FP throughput data for {instruction}")
            continue

        valid_samples = [
            (chains, value)
            for chains, value in samples
            if chains >= args.min_chains
        ]

        if not valid_samples:
            valid_samples = samples

        reciprocal_throughput = min(
            value for _, value in valid_samples
        )
        max_throughput = 1.0 / reciprocal_throughput

        matching_chains = [
            chains
            for chains, value in samples
            if close_enough(
                value,
                reciprocal_throughput,
                args.tolerance,
            )
        ]

        if matching_chains:
            saturation_chains = min(matching_chains)
        else:
            saturation_chains = min(
                samples,
                key=lambda sample: abs(
                    sample[1] - reciprocal_throughput
                ),
            )[0]

        row_spec = spec[instruction]
        latency = latency_by_instruction.get(instruction)

        retired = get_event_value(
            retired_by_instruction,
            instruction,
            saturation_chains,
        )
        issued = get_event_value(
            issued_by_instruction,
            instruction,
            saturation_chains,
        )
        fp_event = get_event_value(
            fp_by_instruction,
            instruction,
            saturation_chains,
        )
        alu = get_event_value(
            alu_by_instruction,
            instruction,
            saturation_chains,
        )

        output_rows.append({
            "instruction": instruction,
            "mnemonic": row_spec["mnemonic"],
            "extension": row_spec["extension"],
            "precision": row_spec["precision"],
            "operand_form": row_spec["operand_form"],
            "input_profile": row_spec["input_profile"],
            "latency": (
                "" if latency is None else f"{latency:.6f}"
            ),
            "reciprocal_throughput": (
                f"{reciprocal_throughput:.6f}"
            ),
            "max_throughput": f"{max_throughput:.6f}",
            "saturation_chains": saturation_chains,
            "retired_per_instruction": f"{retired:.6f}",
            "issued_event_per_instruction": f"{issued:.6f}",
            "fp_event_per_instruction": f"{fp_event:.6f}",
            "alu_event_per_instruction": f"{alu:.6f}",
            "throughput_samples": format_samples(samples),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)


if __name__ == "__main__":
    main()