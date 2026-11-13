#!/usr/bin/env python3

import argparse
import csv
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path


MIN_STEADY_STATE_COUNT = 4


def parse_latency_code(code: str) -> tuple[str, float]:
    match = re.fullmatch(r"(.+)_latency_restore_(\d+)", code)

    if match is None:
        raise ValueError(f"invalid division latency code: {code}")

    return match.group(1), float(match.group(2))


def parse_throughput_code(code: str) -> tuple[str, int]:
    match = re.fullmatch(r"(.+)_throughput_(\d+)", code)

    if match is None:
        raise ValueError(f"invalid division throughput code: {code}")

    return match.group(1), int(match.group(2))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def close_enough(value: float, reference: float) -> bool:
    return math.isclose(value, reference, rel_tol=0.03, abs_tol=0.01)


def format_samples(samples: list[tuple[int, float]]) -> str:
    return ";".join(
        f"{count}:{value:.6f}"
        for count, value in sorted(samples)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latency", type=Path, required=True)
    parser.add_argument("--throughput", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--min-steady-state-count",
        type=int,
        default=MIN_STEADY_STATE_COUNT,
    )
    args = parser.parse_args()

    if args.min_steady_state_count <= 0:
        raise ValueError("--min-steady-state-count must be greater than zero")

    block_cycles: dict[str, float] = {}
    restore_latencies: dict[str, float] = {}

    throughput_cycles: dict[str, list[tuple[int, float]]] = defaultdict(list)
    retired: dict[str, dict[int, float]] = defaultdict(dict)
    issued: dict[str, dict[int, float]] = defaultdict(dict)
    alu: dict[str, dict[int, float]] = defaultdict(dict)

    for row in read_csv(args.latency):
        if row["measurement"] != "division_latency":
            continue

        if row["event"] != "Core cycles":
            continue

        instruction, restore_latency = parse_latency_code(row["code"])

        if instruction in block_cycles:
            raise ValueError(
                f"duplicate division latency result: {instruction}"
            )

        block_cycles[instruction] = float(row["value"])
        restore_latencies[instruction] = restore_latency

    seen_throughput_keys: set[tuple[str, int, str]] = set()

    for row in read_csv(args.throughput):
        if row["measurement"] != "throughput":
            continue

        instruction, count = parse_throughput_code(row["code"])
        event = row["event"]
        key = (instruction, count, event)

        if key in seen_throughput_keys:
            raise ValueError(
                f"duplicate throughput result: "
                f"{instruction}, count={count}, event={event}"
            )

        seen_throughput_keys.add(key)
        value = float(row["value_per_instruction"])

        if event == "Core cycles":
            if value <= 0.0:
                raise ValueError(
                    f"invalid cycle value: "
                    f"{instruction}, count={count}, value={value}"
                )

            throughput_cycles[instruction].append((count, value))
        elif event == "Instructions retired":
            retired[instruction][count] = value
        elif event == "Issued instructions":
            issued[instruction][count] = value
        elif event == "ALU instructions":
            alu[instruction][count] = value

    fieldnames = [
        "instruction",
        "measured_block_cycles",
        "restore_latency",
        "latency",
        "reciprocal_throughput",
        "max_throughput",
        "saturation_count",
        "retired_per_instruction",
        "issued_per_instruction",
        "alu_per_instruction",
        "throughput_samples",
    ]

    output_rows: list[dict[str, object]] = []

    instruction_names = set(block_cycles) | set(throughput_cycles)

    for instruction in sorted(instruction_names):
        samples = sorted(throughput_cycles.get(instruction, []))

        if not samples:
            print(f"warning: no throughput samples for {instruction}")
            continue

        steady_state_samples = [
            (count, value)
            for count, value in samples
            if count >= args.min_steady_state_count
        ]

        if not steady_state_samples:
            steady_state_samples = samples

        reciprocal_throughput = statistics.median(
            value for _, value in steady_state_samples
        )

        max_throughput = 1.0 / reciprocal_throughput

        matching_counts = [
            count
            for count, value in samples
            if close_enough(value, reciprocal_throughput)
        ]

        if matching_counts:
            saturation_count = min(matching_counts)
        else:
            saturation_count = min(
                samples,
                key=lambda sample: abs(
                    sample[1] - reciprocal_throughput
                ),
            )[0]

        measured = block_cycles.get(instruction)
        restore = restore_latencies.get(instruction)

        latency = None

        if measured is not None and restore is not None:
            latency = measured - restore

            if latency < 0.0:
                raise ValueError(
                    f"negative latency for {instruction}: "
                    f"block={measured}, restore={restore}"
                )

        ret_val = retired[instruction].get(
            saturation_count,
            float("nan"),
        )
        iss_val = issued[instruction].get(
            saturation_count,
            float("nan"),
        )
        alu_val = alu[instruction].get(
            saturation_count,
            float("nan"),
        )

        output_rows.append({
            "instruction": instruction,
            "measured_block_cycles": (
                "" if measured is None else f"{measured:.6f}"
            ),
            "restore_latency": (
                "" if restore is None else f"{restore:.6f}"
            ),
            "latency": (
                "" if latency is None else f"{latency:.6f}"
            ),
            "reciprocal_throughput": (
                f"{reciprocal_throughput:.6f}"
            ),
            "max_throughput": f"{max_throughput:.6f}",
            "saturation_count": saturation_count,
            "retired_per_instruction": f"{ret_val:.6f}",
            "issued_per_instruction": f"{iss_val:.6f}",
            "alu_per_instruction": f"{alu_val:.6f}",
            "throughput_samples": format_samples(samples),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)


if __name__ == "__main__":
    main()