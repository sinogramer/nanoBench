#!/usr/bin/env python3

import argparse
import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemoryInstruction:
    kind: str
    width: int
    latency_supported: bool


def read_spec(path: Path) -> dict[str, MemoryInstruction]:
    instructions: dict[str, MemoryInstruction] = {}

    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            instructions[row["name"]] = MemoryInstruction(
                kind=row["kind"],
                width=int(row["width"]),
                latency_supported=row.get("latency_supported", "0") == "1",
            )

    return instructions


def parse_code_name(code: str) -> tuple[str, int]:
    pattern = r"(.+)_throughput_(\d+)(?:_stride_\d+)?"
    match = re.fullmatch(pattern, code)

    if match is None:
        raise ValueError(f"invalid memory benchmark name: {code}")

    instruction = match.group(1)
    instruction_count = int(match.group(2))

    return instruction, instruction_count


def read_latency_file(path: Path | None) -> dict[str, float]:
    latencies: dict[str, float] = {}

    if path is None:
        return latencies

    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["measurement"] != "latency":
                continue

            if row["event"] != "Core cycles":
                continue

            code = row["code"]

            for suffix in ("_dependency_chain", "_latency"):
                if code.endswith(suffix):
                    code = code[:-len(suffix)]
                    break

            latencies[code] = float(row["value_per_instruction"])

    return latencies


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--throughput", type=Path, required=True)
    parser.add_argument("--latency", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=0.03)
    parser.add_argument("--unroll-count", type=int, default=64)
    parser.add_argument("--loop-count", type=int, default=16)
    args = parser.parse_args()

    instruction_spec = read_spec(args.spec)
    latencies = read_latency_file(args.latency)

    cycles: dict[str, list[tuple[int, float]]] = defaultdict(list)
    retired: dict[str, dict[int, float]] = defaultdict(dict)
    issued: dict[str, dict[int, float]] = defaultdict(dict)
    memory: dict[str, dict[int, float]] = defaultdict(dict)

    with args.throughput.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["measurement"] != "throughput":
                continue

            if int(row["unroll_count"]) != args.unroll_count:
                continue

            if int(row["loop_count"]) != args.loop_count:
                continue

            instruction, count = parse_code_name(row["code"])
            value = float(row["value_per_instruction"])

            if row["event"] == "Core cycles":
                cycles[instruction].append((count, value))
            elif row["event"] == "Instructions retired":
                retired[instruction][count] = value
            elif row["event"] == "Issued instructions":
                issued[instruction][count] = value
            elif row["event"] == "Memory instructions":
                memory[instruction][count] = value

    fieldnames = [
        "instruction",
        "kind",
        "width",
        "latency",
        "reciprocal_throughput",
        "max_throughput",
        "saturation_count",
        "retired_per_instruction",
        "issued_per_instruction",
        "memory_per_instruction",
    ]

    output_rows: list[dict[str, object]] = []

    for instruction in sorted(instruction_spec):
        samples = sorted(cycles.get(instruction, []))

        if not samples:
            print(f"warning: no throughput data for {instruction}")
            continue

        reciprocal_throughput = min(value for _, value in samples)
        max_throughput = 1.0 / reciprocal_throughput

        saturation_count = min(
            count
            for count, value in samples
            if close_enough(
                value,
                reciprocal_throughput,
                args.tolerance,
            )
        )

        spec = instruction_spec[instruction]
        latency = latencies.get(instruction)

        output_rows.append({
            "instruction": instruction,
            "kind": spec.kind,
            "width": spec.width,
            "latency": "" if latency is None else f"{latency:.6f}",
            "reciprocal_throughput": f"{reciprocal_throughput:.6f}",
            "max_throughput": f"{max_throughput:.6f}",
            "saturation_count": saturation_count,
            "retired_per_instruction": (
                f"{retired[instruction][saturation_count]:.6f}"
            ),
            "issued_per_instruction": (
                f"{issued[instruction][saturation_count]:.6f}"
            ),
            "memory_per_instruction": (
                f"{memory[instruction][saturation_count]:.6f}"
            ),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)


if __name__ == "__main__":
    main()