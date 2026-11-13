#!/usr/bin/env python3

import argparse
import csv
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path


MIN_STEADY_STATE_COUNT = 2


def parse_code(code: str) -> tuple[str, int]:
    match = re.fullmatch(
        r"(.+)_throughput_(\d+)",
        code,
    )

    if match is None:
        raise ValueError(
            f"invalid Vector memory benchmark name: {code}"
        )

    return match.group(1), int(match.group(2))


def read_spec(path: Path) -> dict[str, dict[str, str]]:
    entries: dict[str, dict[str, str]] = {}

    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row.get("enabled", "1") != "1":
                continue

            name = row["name"]

            if name in entries:
                raise ValueError(
                    f"duplicate Vector memory spec entry: {name}"
                )

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


def bytes_per_instruction(
    row: dict[str, str],
) -> int:
    vl = int(row["vl"])
    eew = int(row["eew"])

    if eew <= 0 or eew % 8 != 0:
        raise ValueError(
            f"{row['name']}: invalid EEW: {eew}"
        )

    return vl * eew // 8


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--min-steady-state-count",
        type=int,
        default=MIN_STEADY_STATE_COUNT,
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.03,
    )
    args = parser.parse_args()

    if args.min_steady_state_count <= 0:
        raise ValueError(
            "--min-steady-state-count must be greater than zero"
        )

    if args.tolerance < 0.0:
        raise ValueError(
            "--tolerance must not be negative"
        )

    spec = read_spec(args.spec)

    cycles: dict[
        str,
        list[tuple[int, float]],
    ] = defaultdict(list)

    retired: dict[
        str,
        dict[int, float],
    ] = defaultdict(dict)

    issued: dict[
        str,
        dict[int, float],
    ] = defaultdict(dict)

    memory: dict[
        str,
        dict[int, float],
    ] = defaultdict(dict)

    vector: dict[
        str,
        dict[int, float],
    ] = defaultdict(dict)

    alu: dict[
        str,
        dict[int, float],
    ] = defaultdict(dict)

    fp: dict[
        str,
        dict[int, float],
    ] = defaultdict(dict)

    seen: set[tuple[str, int, str]] = set()

    with args.input.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["measurement"] != "vector_memory_throughput":
                continue

            instruction, count = parse_code(row["code"])
            event = row["event"]
            duplicate_key = (
                instruction,
                count,
                event,
            )

            if duplicate_key in seen:
                raise ValueError(
                    f"duplicate Vector memory result: "
                    f"instruction={instruction}, "
                    f"count={count}, event={event}"
                )

            seen.add(duplicate_key)
            value = float(row["value_per_instruction"])

            if event == "Core cycles":
                if value <= 0.0:
                    raise ValueError(
                        f"invalid Vector memory cycle value: "
                        f"instruction={instruction}, "
                        f"count={count}, value={value}"
                    )

                cycles[instruction].append(
                    (count, value)
                )
            elif event == "Instructions retired":
                retired[instruction][count] = value
            elif event == "Issued instructions":
                issued[instruction][count] = value
            elif event == "Memory instructions":
                memory[instruction][count] = value
            elif event == "Vector instructions":
                vector[instruction][count] = value
            elif event == "ALU instructions":
                alu[instruction][count] = value
            elif event == "FP instructions":
                fp[instruction][count] = value

    fieldnames = [
        "instruction",
        "mnemonic",
        "kind",
        "eew",
        "sew",
        "lmul",
        "vl",
        "bytes_per_instruction",
        "reciprocal_throughput",
        "max_throughput",
        "bytes_per_cycle",
        "steady_state_reached",
        "first_steady_state_count",
        "retired_per_instruction",
        "issued_event_per_instruction",
        "memory_event_per_instruction",
        "vector_event_per_instruction",
        "alu_event_per_instruction",
        "fp_event_per_instruction",
        "throughput_samples",
    ]

    output_rows: list[dict[str, object]] = []

    for instruction in sorted(cycles):
        if instruction not in spec:
            raise ValueError(
                f"Vector memory result has no spec entry: "
                f"{instruction}"
            )

        samples = sorted(cycles[instruction])

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

        if reciprocal_throughput <= 0.0:
            raise ValueError(
                f"{instruction}: reciprocal throughput "
                f"must be greater than zero"
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

        last_two_values = [
            value
            for _, value in steady_samples[-2:]
        ]

        steady_state_reached = (
            len(last_two_values) >= 2
            and close_enough(
                last_two_values[-1],
                last_two_values[-2],
                args.tolerance,
            )
        )

        row_spec = spec[instruction]
        byte_count = bytes_per_instruction(row_spec)
        bandwidth = byte_count / reciprocal_throughput

        retired_value = get_event_value(
            retired,
            instruction,
            representative_count,
        )
        issued_value = get_event_value(
            issued,
            instruction,
            representative_count,
        )
        memory_value = get_event_value(
            memory,
            instruction,
            representative_count,
        )
        vector_value = get_event_value(
            vector,
            instruction,
            representative_count,
        )
        alu_value = get_event_value(
            alu,
            instruction,
            representative_count,
        )
        fp_value = get_event_value(
            fp,
            instruction,
            representative_count,
        )

        output_rows.append({
            "instruction": instruction,
            "mnemonic": row_spec["mnemonic"],
            "kind": row_spec["kind"],
            "eew": row_spec["eew"],
            "sew": row_spec["sew"],
            "lmul": row_spec["lmul"],
            "vl": row_spec["vl"],
            "bytes_per_instruction": byte_count,
            "reciprocal_throughput": (
                f"{reciprocal_throughput:.6f}"
            ),
            "max_throughput": (
                f"{max_throughput:.6f}"
            ),
            "bytes_per_cycle": f"{bandwidth:.6f}",
            "steady_state_reached": (
                "1" if steady_state_reached else "0"
            ),
            "first_steady_state_count": (
                representative_count
            ),
            "retired_per_instruction": (
                f"{retired_value:.6f}"
            ),
            "issued_event_per_instruction": (
                f"{issued_value:.6f}"
            ),
            "memory_event_per_instruction": (
                f"{memory_value:.6f}"
            ),
            "vector_event_per_instruction": (
                f"{vector_value:.6f}"
            ),
            "alu_event_per_instruction": (
                f"{alu_value:.6f}"
            ),
            "fp_event_per_instruction": (
                f"{fp_value:.6f}"
            ),
            "throughput_samples": format_samples(samples),
        })

    args.output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

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