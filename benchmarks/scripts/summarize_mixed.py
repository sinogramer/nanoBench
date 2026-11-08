#!/usr/bin/env python3

import argparse
import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstructionModel:
    latency: float
    reciprocal_throughput: float


@dataclass(frozen=True)
class PairDefinition:
    mnemonic_a: str
    mnemonic_b: str


def read_instruction_models(path: Path) -> dict[str, InstructionModel]:
    models: dict[str, InstructionModel] = {}

    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            models[row["instruction"]] = InstructionModel(
                latency=float(row["latency"]),
                reciprocal_throughput=float(row["reciprocal_throughput"]),
            )

    return models


def read_pair_definitions(path: Path) -> dict[str, PairDefinition]:
    pairs: dict[str, PairDefinition] = {}

    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            pairs[row["name"]] = PairDefinition(
                mnemonic_a=row["mnemonic_a"],
                mnemonic_b=row["mnemonic_b"],
            )

    return pairs


def parse_code_name(code: str) -> tuple[str, int, int]:
    match = re.fullmatch(r"(.+)_(\d+)_(\d+)", code)

    if match is None:
        raise ValueError(f"invalid mixed benchmark name: {code}")

    pair_name = match.group(1)
    count_a = int(match.group(2))
    count_b = int(match.group(3))

    return pair_name, count_a, count_b


def predict_cycles(
    model_a: InstructionModel,
    model_b: InstructionModel,
    count_a: int,
    count_b: int,
    issue_width: float,
) -> dict[str, float]:
    issue_bound = (count_a + count_b) / issue_width
    resource_a_bound = count_a * model_a.reciprocal_throughput
    resource_b_bound = count_b * model_b.reciprocal_throughput

    latency_a_bound = model_a.latency if count_a > 0 else 0.0
    latency_b_bound = model_b.latency if count_b > 0 else 0.0

    predicted = max(
        issue_bound,
        resource_a_bound,
        resource_b_bound,
        latency_a_bound,
        latency_b_bound,
    )

    return {
        "issue_bound": issue_bound,
        "resource_a_bound": resource_a_bound,
        "resource_b_bound": resource_b_bound,
        "latency_a_bound": latency_a_bound,
        "latency_b_bound": latency_b_bound,
        "predicted_cycles": predicted,
    }


def classify_ratio(ratio: float, tolerance: float) -> str:
    if math.isclose(ratio, 1.0, rel_tol=tolerance, abs_tol=0.02):
        return "explained"

    if ratio > 1.0:
        return "slower_than_model"

    return "faster_than_model"


def read_mixed_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["measurement"] != "mixed_throughput":
                continue

            if row["event"] != "Core cycles":
                continue

            rows.append(row)

    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--single-summary", type=Path, required=True)
    parser.add_argument("--pair-spec", type=Path, required=True)
    parser.add_argument("--mixed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--issue-width", type=float, default=3.0)
    parser.add_argument("--tolerance", type=float, default=0.03)
    args = parser.parse_args()

    if args.issue_width <= 0.0:
        raise ValueError("--issue-width must be greater than zero")

    models = read_instruction_models(args.single_summary)
    pairs = read_pair_definitions(args.pair_spec)
    mixed_rows = read_mixed_rows(args.mixed)

    output_rows: list[dict[str, object]] = []

    for row in mixed_rows:
        pair_name, count_a, count_b = parse_code_name(row["code"])

        if pair_name not in pairs:
            raise KeyError(f"pair not found in pair spec: {pair_name}")

        pair = pairs[pair_name]

        if pair.mnemonic_a not in models:
            raise KeyError(f"single-instruction model not found: {pair.mnemonic_a}")

        if pair.mnemonic_b not in models:
            raise KeyError(f"single-instruction model not found: {pair.mnemonic_b}")

        model_a = models[pair.mnemonic_a]
        model_b = models[pair.mnemonic_b]

        bounds = predict_cycles(
            model_a,
            model_b,
            count_a,
            count_b,
            args.issue_width,
        )

        measured_cycles = float(row["value"])
        predicted_cycles = bounds["predicted_cycles"]
        ratio = measured_cycles / predicted_cycles

        output_rows.append({
            "pair": pair_name,
            "instruction_a": pair.mnemonic_a,
            "instruction_b": pair.mnemonic_b,
            "count_a": count_a,
            "count_b": count_b,
            "total_instructions": count_a + count_b,
            "measured_cycles": measured_cycles,
            "issue_bound": bounds["issue_bound"],
            "resource_a_bound": bounds["resource_a_bound"],
            "resource_b_bound": bounds["resource_b_bound"],
            "latency_a_bound": bounds["latency_a_bound"],
            "latency_b_bound": bounds["latency_b_bound"],
            "predicted_cycles": predicted_cycles,
            "measured_over_predicted": ratio,
            "classification": classify_ratio(ratio, args.tolerance),
        })

    output_rows.sort(
        key=lambda row: (
            str(row["pair"]),
            int(row["count_a"]),
            int(row["count_b"]),
        )
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "pair",
        "instruction_a",
        "instruction_b",
        "count_a",
        "count_b",
        "total_instructions",
        "measured_cycles",
        "issue_bound",
        "resource_a_bound",
        "resource_b_bound",
        "latency_a_bound",
        "latency_b_bound",
        "predicted_cycles",
        "measured_over_predicted",
        "classification",
    ]

    with args.output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for row in output_rows:
            formatted = dict(row)

            for key in (
                "measured_cycles",
                "issue_bound",
                "resource_a_bound",
                "resource_b_bound",
                "latency_a_bound",
                "latency_b_bound",
                "predicted_cycles",
                "measured_over_predicted",
            ):
                formatted[key] = f"{float(row[key]):.6f}"

            writer.writerow(formatted)


if __name__ == "__main__":
    main()