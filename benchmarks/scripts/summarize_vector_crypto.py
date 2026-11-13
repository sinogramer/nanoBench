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
        raise ValueError(
            f"invalid Crypto latency benchmark name: {code}"
        )

    return code[:-len(suffix)]


def parse_throughput_code(code: str) -> tuple[str, int]:
    match = re.fullmatch(r"(.+)_throughput_(\d+)", code)

    if match is None:
        raise ValueError(
            f"invalid Crypto throughput benchmark name: {code}"
        )

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
                raise ValueError(
                    f"duplicate Crypto spec entry: {name}"
                )

            entries[name] = row

    return entries


def close_enough(
    value: float,
    reference: float,
    tolerance: float,
) -> bool:
    return math.isclose(
        value,
        reference,
        rel_tol=tolerance,
        abs_tol=0.01,
    )


def format_samples(
    samples: list[tuple[int, float]],
) -> str:
    return ";".join(
        f"{count}:{value:.6f}"
        for count, value in sorted(samples)
    )


def get_event_value(
    values: dict[str, dict[int, float]],
    instruction: str,
    count: int,
) -> float:
    return values[instruction].get(
        count,
        float("nan"),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--latency", type=Path, required=True)
    parser.add_argument("--throughput", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tolerance", type=float, default=0.03)
    parser.add_argument("--min-chains", type=int, default=2)
    args = parser.parse_args()

    if args.tolerance < 0:
        parser.error("--tolerance must be non-negative")
    if args.min_chains < 1:
        parser.error("--min-chains must be at least 1")

    spec = read_spec(args.spec)

    latency: dict[str, float] = {}

    cycles: dict[
        str,
        list[tuple[int, float]],
    ] = defaultdict(list)

    retired: dict[str, dict[int, float]] = defaultdict(dict)
    issued: dict[str, dict[int, float]] = defaultdict(dict)
    alu: dict[str, dict[int, float]] = defaultdict(dict)
    memory: dict[str, dict[int, float]] = defaultdict(dict)
    vector: dict[str, dict[int, float]] = defaultdict(dict)
    fp: dict[str, dict[int, float]] = defaultdict(dict)

    seen_latency: set[tuple[str, str]] = set()
    seen_throughput: set[tuple[str, int, str]] = set()

    for row in read_csv(args.latency):
        if row["measurement"] != "vector_crypto_latency":
            continue

        instruction = parse_latency_code(row["code"])
        event = row["event"]
        key = (instruction, event)

        if key in seen_latency:
            raise ValueError(
                f"duplicate Crypto latency result: "
                f"instruction={instruction}, event={event}"
            )

        seen_latency.add(key)

        if event == "Core cycles":
            latency[instruction] = float(
                row["value_per_instruction"]
            )

    for row in read_csv(args.throughput):
        if row["measurement"] != "vector_crypto_throughput":
            continue

        instruction, count = parse_throughput_code(row["code"])
        event = row["event"]
        key = (instruction, count, event)

        if key in seen_throughput:
            raise ValueError(
                f"duplicate Crypto throughput result: "
                f"instruction={instruction}, count={count}, "
                f"event={event}"
            )

        seen_throughput.add(key)
        value = float(row["value_per_instruction"])

        if not math.isfinite(value):
            raise ValueError(
                f"non-finite Crypto throughput value: "
                f"instruction={instruction}, count={count}, event={event}"
            )

        if event == "Core cycles" and value <= 0:
            raise ValueError(
                f"Core cycles must be positive: "
                f"instruction={instruction}, count={count}, value={value}"
            )

        if event == "Core cycles":
            cycles[instruction].append((count, value))
        elif event == "Instructions retired":
            retired[instruction][count] = value
        elif event == "Issued instructions":
            issued[instruction][count] = value
        elif event == "ALU instructions":
            alu[instruction][count] = value
        elif event == "Memory instructions":
            memory[instruction][count] = value
        elif event == "Vector instructions":
            vector[instruction][count] = value
        elif event == "FP instructions":
            fp[instruction][count] = value

    fieldnames = [
        "instruction",
        "mnemonic",
        "extension",
        "sew",
        "lmul",
        "vl",
        "egw",
        "vector_bits",
        "element_groups",
        "operand_form",
        "profile",
        "latency",
        "reciprocal_throughput",
        "max_throughput",
        "blocks_per_cycle",
        "first_steady_state_count",
        "retired_per_instruction",
        "issued_event_per_instruction",
        "alu_event_per_instruction",
        "memory_event_per_instruction",
        "vector_event_per_instruction",
        "fp_event_per_instruction",
        "throughput_samples",
    ]

    output_rows: list[dict[str, object]] = []

    instruction_names = set(latency) | set(cycles)

    for instruction in sorted(instruction_names):
        if instruction not in spec:
            raise ValueError(
                f"Crypto result has no spec entry: {instruction}"
            )

        samples = sorted(cycles.get(instruction, []))

        if not samples:
            raise ValueError(
                f"no Crypto throughput data for {instruction}"
            )

        valid_samples = [
            (count, value)
            for count, value in samples
            if count >= args.min_chains
        ]

        if not valid_samples:
            valid_samples = samples

        reciprocal_throughput = min(
            value for _, value in valid_samples
        )

        if reciprocal_throughput <= 0:
            raise ValueError(
                f"invalid reciprocal throughput for {instruction}: "
                f"{reciprocal_throughput}"
            )

        max_throughput = 1.0 / reciprocal_throughput

        matching_counts = [
            count
            for count, value in samples
            if close_enough(
                value,
                reciprocal_throughput,
                args.tolerance,
            )
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
        sew = int(row_spec["sew"])
        vl = int(row_spec["vl"])
        egw = int(row_spec["egw"])

        vector_bits = sew * vl
        element_groups = vector_bits // egw

        blocks_per_cycle = (
            element_groups / reciprocal_throughput
        )

        output_rows.append({
            "instruction": instruction,
            "mnemonic": row_spec["mnemonic"],
            "extension": row_spec["extension"],
            "sew": sew,
            "lmul": row_spec["lmul"],
            "vl": vl,
            "egw": egw,
            "vector_bits": vector_bits,
            "element_groups": element_groups,
            "operand_form": row_spec["operand_form"],
            "profile": row_spec["profile"],
            "latency": (
                ""
                if instruction not in latency
                else f"{latency[instruction]:.6f}"
            ),
            "reciprocal_throughput": (
                f"{reciprocal_throughput:.6f}"
            ),
            "max_throughput": f"{max_throughput:.6f}",
            "blocks_per_cycle": f"{blocks_per_cycle:.6f}",
            "first_steady_state_count": representative_count,
            "retired_per_instruction": (
                f"{get_event_value(
                    retired,
                    instruction,
                    representative_count,
                ):.6f}"
            ),
            "issued_event_per_instruction": (
                f"{get_event_value(
                    issued,
                    instruction,
                    representative_count,
                ):.6f}"
            ),
            "alu_event_per_instruction": (
                f"{get_event_value(
                    alu,
                    instruction,
                    representative_count,
                ):.6f}"
            ),
            "memory_event_per_instruction": (
                f"{get_event_value(
                    memory,
                    instruction,
                    representative_count,
                ):.6f}"
            ),
            "vector_event_per_instruction": (
                f"{get_event_value(
                    vector,
                    instruction,
                    representative_count,
                ):.6f}"
            ),
            "fp_event_per_instruction": (
                f"{get_event_value(
                    fp,
                    instruction,
                    representative_count,
                ):.6f}"
            ),
            "throughput_samples": format_samples(samples),
        })

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(output_rows)


if __name__ == "__main__":
    main()