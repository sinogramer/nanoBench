#!/usr/bin/env python3

import argparse
import csv
import math
import re
from collections import defaultdict
from pathlib import Path


def parse_code(code: str) -> tuple[str, int, int]:
    match = re.fullmatch(
        r"(.+)_throughput_(\d+)_stride_(\d+)",
        code,
    )

    if match is None:
        raise ValueError(
            f"invalid FP memory benchmark name: {code}"
        )

    return (
        match.group(1),
        int(match.group(2)),
        int(match.group(3)),
    )


def read_spec(path: Path) -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}

    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row.get("enabled", "1") != "1":
                continue

            name = row["name"]

            if name in entries:
                raise ValueError(
                    f"duplicate FP memory spec entry: {name}"
                )

            entries[name] = row

    return entries


def close_enough(value: float, reference: float) -> bool:
    return math.isclose(
        value,
        reference,
        rel_tol=0.03,
        abs_tol=0.01,
    )


def format_samples(samples: list[tuple[int, float]]) -> str:
    return ";".join(
        f"{count}:{value:.6f}"
        for count, value in sorted(samples)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    spec = read_spec(args.spec)

    cycles: dict[
        tuple[str, int],
        list[tuple[int, float]],
    ] = defaultdict(list)

    retired: dict[
        tuple[str, int],
        dict[int, float],
    ] = defaultdict(dict)

    issued: dict[
        tuple[str, int],
        dict[int, float],
    ] = defaultdict(dict)

    memory: dict[
        tuple[str, int],
        dict[int, float],
    ] = defaultdict(dict)

    fp: dict[
        tuple[str, int],
        dict[int, float],
    ] = defaultdict(dict)

    alu: dict[
        tuple[str, int],
        dict[int, float],
    ] = defaultdict(dict)

    seen: set[tuple[str, int, int, str]] = set()

    with args.input.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["measurement"] != "fp_memory_throughput":
                continue

            instruction, count, stride = parse_code(row["code"])
            event = row["event"]
            key = (instruction, stride)
            duplicate_key = (
                instruction,
                stride,
                count,
                event,
            )

            if duplicate_key in seen:
                raise ValueError(
                    f"duplicate FP memory result: "
                    f"instruction={instruction}, "
                    f"stride={stride}, count={count}, "
                    f"event={event}"
                )

            seen.add(duplicate_key)
            value = float(row["value_per_instruction"])

            if event == "Core cycles":
                if value <= 0.0:
                    raise ValueError(
                        f"invalid cycle value: {row['code']}: {value}"
                    )

                cycles[key].append((count, value))
            elif event == "Instructions retired":
                retired[key][count] = value
            elif event == "Issued instructions":
                issued[key][count] = value
            elif event == "Memory instructions":
                memory[key][count] = value
            elif event == "FP instructions":
                fp[key][count] = value
            elif event == "ALU instructions":
                alu[key][count] = value

    fieldnames = [
        "instruction",
        "mnemonic",
        "extension",
        "kind",
        "width",
        "precision",
        "stride",
        "reciprocal_throughput",
        "max_throughput",
        "first_steady_state_count",
        "retired_per_instruction",
        "issued_event_per_instruction",
        "memory_event_per_instruction",
        "fp_event_per_instruction",
        "alu_event_per_instruction",
        "throughput_samples",
    ]

    output_rows: list[dict[str, object]] = []

    for key in sorted(cycles):
        instruction, stride = key
        samples = sorted(cycles[key])

        if instruction not in spec:
            raise ValueError(
                f"result has no matching spec entry: {instruction}"
            )

        reciprocal_throughput = min(
            value for _, value in samples
        )
        max_throughput = 1.0 / reciprocal_throughput

        matching_counts = [
            count
            for count, value in samples
            if close_enough(value, reciprocal_throughput)
        ]

        if matching_counts:
            representative_count = min(matching_counts)
        else:
            representative_count = min(
                samples,
                key=lambda sample: abs(
                    sample[1] - reciprocal_throughput
                ),
            )[0]

        row_spec = spec[instruction]

        output_rows.append({
            "instruction": instruction,
            "mnemonic": row_spec["mnemonic"],
            "extension": row_spec["extension"],
            "kind": row_spec["kind"],
            "width": row_spec["width"],
            "precision": row_spec["precision"],
            "stride": stride,
            "reciprocal_throughput": (
                f"{reciprocal_throughput:.6f}"
            ),
            "max_throughput": f"{max_throughput:.6f}",
            "first_steady_state_count": representative_count,
            "retired_per_instruction": (
                f"{retired[key].get(representative_count, float('nan')):.6f}"
            ),
            "issued_event_per_instruction": (
                f"{issued[key].get(representative_count, float('nan')):.6f}"
            ),
            "memory_event_per_instruction": (
                f"{memory[key].get(representative_count, float('nan')):.6f}"
            ),
            "fp_event_per_instruction": (
                f"{fp[key].get(representative_count, float('nan')):.6f}"
            ),
            "alu_event_per_instruction": (
                f"{alu[key].get(representative_count, float('nan')):.6f}"
            ),
            "throughput_samples": format_samples(samples),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)


if __name__ == "__main__":
    main()