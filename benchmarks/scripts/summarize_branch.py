#!/usr/bin/env python3

import argparse
import csv
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path


def parse_code(code: str) -> tuple[str, int]:
    match = re.fullmatch(r"(.+)_throughput_(\d+)", code)

    if match is None:
        raise ValueError(f"invalid branch benchmark name: {code}")

    return match.group(1), int(match.group(2))


def close_enough(value: float, reference: float) -> bool:
    return math.isclose(value, reference, rel_tol=0.03, abs_tol=0.01)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    cycles: dict[str, list[tuple[int, float]]] = defaultdict(list)
    retired: dict[str, dict[int, float]] = defaultdict(dict)
    issued: dict[str, dict[int, float]] = defaultdict(dict)
    alu: dict[str, dict[int, float]] = defaultdict(dict)

    with args.input.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["measurement"] not in {
                "branch_throughput",
                "jump_throughput",
            }:
                continue

            name, count = parse_code(row["code"])
            value = float(row["value_per_instruction"])

            if row["event"] == "Core cycles":
                cycles[name].append((count, value))
            elif row["event"] == "Instructions retired":
                retired[name][count] = value
            elif row["event"] == "Issued instructions":
                issued[name][count] = value
            elif row["event"] == "ALU instructions":
                alu[name][count] = value

    fieldnames = [
        "benchmark",
        "reciprocal_throughput",
        "max_throughput",
        "first_steady_state_count",
        "retired_per_branch",
        "issued_per_branch",
        "alu_per_branch",
        "throughput_samples",
    ]

    output_rows = []

    for name in sorted(cycles):
        samples = sorted(cycles[name])

        steady_samples = [
            (count, value)
            for count, value in samples
            if count >= 4
        ]

        if not steady_samples:
            steady_samples = samples

        reciprocal_throughput = statistics.median(
            value for _, value in steady_samples
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

        sample_text = ";".join(
            f"{count}:{value:.6f}"
            for count, value in samples
        )

        output_rows.append({
            "benchmark": name,
            "reciprocal_throughput": (
                f"{reciprocal_throughput:.6f}"
            ),
            "max_throughput": f"{max_throughput:.6f}",
            "first_steady_state_count": representative_count,
            "retired_per_branch": (
                f"{retired[name].get(representative_count, float('nan')):.6f}"
            ),
            "issued_per_branch": (
                f"{issued[name].get(representative_count, float('nan')):.6f}"
            ),
            "alu_per_branch": (
                f"{alu[name].get(representative_count, float('nan')):.6f}"
            ),
            "throughput_samples": sample_text,
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)


if __name__ == "__main__":
    main()