#!/usr/bin/env python3

import argparse
import csv
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path


LAYOUTS = (
    "distinct_word_same_line",
    "distinct_line",
    "same",
)

MIN_STEADY_STATE_COUNT = 4


def parse_code(code: str) -> tuple[str, str, int]:
    layout_pattern = "|".join(
        re.escape(layout)
        for layout in LAYOUTS
    )

    match = re.fullmatch(
        rf"(.+)_({layout_pattern})_throughput_(\d+)",
        code,
    )

    if match is None:
        raise ValueError(f"invalid atomic benchmark name: {code}")

    instruction = match.group(1)
    layout = match.group(2)
    count = int(match.group(3))

    return instruction, layout, count


def close_enough(value: float, reference: float) -> bool:
    return math.isclose(
        value,
        reference,
        rel_tol=0.03,
        abs_tol=0.02,
    )


def format_samples(samples: list[tuple[int, float]]) -> str:
    return ";".join(
        f"{count}:{value:.6f}"
        for count, value in sorted(samples)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--min-steady-state-count",
        type=int,
        default=MIN_STEADY_STATE_COUNT,
    )
    args = parser.parse_args()

    if args.min_steady_state_count <= 0:
        raise ValueError(
            "--min-steady-state-count must be greater than zero"
        )

    cycles: dict[
        tuple[str, str],
        list[tuple[int, float]],
    ] = defaultdict(list)

    retired: dict[
        tuple[str, str],
        dict[int, float],
    ] = defaultdict(dict)

    issued: dict[
        tuple[str, str],
        dict[int, float],
    ] = defaultdict(dict)

    memory: dict[
        tuple[str, str],
        dict[int, float],
    ] = defaultdict(dict)

    alu: dict[
        tuple[str, str],
        dict[int, float],
    ] = defaultdict(dict)

    seen_keys: set[tuple[str, str, int, str]] = set()

    with args.input.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["measurement"] != "atomic_throughput":
                continue

            instruction, layout, count = parse_code(row["code"])
            event = row["event"]
            key = (instruction, layout)
            duplicate_key = (
                instruction,
                layout,
                count,
                event,
            )

            if duplicate_key in seen_keys:
                raise ValueError(
                    "duplicate atomic result: "
                    f"instruction={instruction}, "
                    f"layout={layout}, "
                    f"count={count}, "
                    f"event={event}"
                )

            seen_keys.add(duplicate_key)
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
            elif event == "ALU instructions":
                alu[key][count] = value

    fieldnames = [
        "instruction",
        "layout",
        "reciprocal_throughput",
        "max_throughput",
        "steady_state_reached",
        "first_steady_state_count",
        "retired_per_instruction",
        "issued_event_per_instruction",
        "memory_event_per_instruction",
        "alu_event_per_instruction",
        "throughput_samples",
    ]

    output_rows: list[dict[str, object]] = []

    for key in sorted(cycles):
        instruction, layout = key
        samples = sorted(cycles[key])

        steady_samples = [
            (count, value)
            for count, value in samples
            if count >= args.min_steady_state_count
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

        last_two_values = [
            value
            for _, value in steady_samples[-2:]
        ]

        steady_state_reached = (
            len(last_two_values) >= 2
            and close_enough(last_two_values[-1], last_two_values[-2])
        )

        output_rows.append({
            "instruction": instruction,
            "layout": layout,
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
            "alu_event_per_instruction": (
                f"{alu[key].get(representative_count, float('nan')):.6f}"
            ),
            "throughput_samples": format_samples(samples),
            "steady_state_reached": (
                "1" if steady_state_reached else "0"
            ),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)


if __name__ == "__main__":
    main()