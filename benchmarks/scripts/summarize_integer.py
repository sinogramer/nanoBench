#!/usr/bin/env python3

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path


def instruction_name(code: str) -> str:
    for suffix in ("_latency", "_dependent"):
        if code.endswith(suffix):
            return code[:-len(suffix)]

    marker = "_throughput_"

    if marker in code:
        return code.split(marker, 1)[0]

    return code


def chain_count(code: str) -> int | None:
    marker = "_throughput_"

    if marker not in code:
        return None

    return int(code.rsplit(marker, 1)[1])


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def close_enough(a: float, b: float, relative_tolerance: float = 0.02) -> bool:
    return math.isclose(a, b, rel_tol=relative_tolerance, abs_tol=0.01)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latency", type=Path)
    parser.add_argument("--throughput", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    latency_rows = read_rows(args.latency) if args.latency is not None else []
    throughput_rows = read_rows(args.throughput)

    latency_by_instruction: dict[str, float] = {}
    throughput_by_instruction: dict[str, list[tuple[int, float]]] = defaultdict(list)
    retired_by_instruction: dict[str, list[tuple[int, float]]] = defaultdict(list)
    issued_by_instruction: dict[str, list[tuple[int, float]]] = defaultdict(list)
    alu_by_instruction: dict[str, list[tuple[int, float]]] = defaultdict(list)

    for row in latency_rows:
        if row["measurement"] != "latency":
            continue

        if row["event"] == "Core cycles":
            name = instruction_name(row["code"])
            latency_by_instruction[name] = float(row["value_per_instruction"])

    for row in throughput_rows:
        if row["measurement"] != "throughput":
            continue

        name = instruction_name(row["code"])
        chains = chain_count(row["code"])

        if chains is None:
            continue

        value = float(row["value_per_instruction"])

        if row["event"] == "Core cycles":
            throughput_by_instruction[name].append((chains, value))
        elif row["event"] == "Instructions retired":
            retired_by_instruction[name].append((chains, value))
        elif row["event"] == "Issued instructions":
            issued_by_instruction[name].append((chains, value))
        elif row["event"] == "ALU instructions":
            alu_by_instruction[name].append((chains, value))

    args.output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "instruction",
        "latency",
        "reciprocal_throughput",
        "max_throughput",
        "saturation_chains",
        "retired_per_instruction",
        "issued_per_instruction",
        "alu_per_instruction",
    ]

    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        instruction_names = (set(latency_by_instruction) | set(throughput_by_instruction))

        for name in sorted(instruction_names):
            samples = sorted(throughput_by_instruction.get(name, []))

            if not samples:
                continue

            retired_samples = dict(retired_by_instruction.get(name, []))
            issued_samples = dict(issued_by_instruction.get(name, []))

            valid_samples = [
                (chains, value)
                for chains, value in samples
                if close_enough(retired_samples.get(chains, 0.0), 1.0)
                and close_enough(issued_samples.get(chains, 0.0), 1.0)
            ]

            if not valid_samples:
                valid_samples = samples

            latency = latency_by_instruction.get(name)

            reciprocal_throughput = min(value for _, value in valid_samples)
            max_throughput = 1.0 / reciprocal_throughput

            saturation_chains = min(
                chains
                for chains, value in valid_samples
                if close_enough(value, reciprocal_throughput)
            )

            retired_samples = dict(retired_by_instruction.get(name, []))
            issued_samples = dict(issued_by_instruction.get(name, []))
            alu_samples = dict(alu_by_instruction.get(name, []))

            retired = retired_samples.get(saturation_chains, float("nan"))
            issued = issued_samples.get(saturation_chains, float("nan"))
            alu = alu_samples.get(saturation_chains, float("nan"))

            writer.writerow({
                "instruction": name,
                "latency": "" if latency is None else f"{latency:.6f}",
                "reciprocal_throughput": f"{reciprocal_throughput:.6f}",
                "max_throughput": f"{max_throughput:.6f}",
                "saturation_chains": saturation_chains,
                "retired_per_instruction": f"{retired:.6f}",
                "issued_per_instruction": f"{issued:.6f}",
                "alu_per_instruction": f"{alu:.6f}",
            })


if __name__ == "__main__":
    main()