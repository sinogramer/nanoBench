#!/usr/bin/env python3

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path


COMMON_METRICS = {
    "latency": "cycles",
    "reciprocal_throughput": "cycles/instruction",
    "max_throughput": "instructions/cycle",
    "bytes_per_cycle": "bytes/cycle",
    "blocks_per_cycle": "blocks/cycle",
    "retired_per_instruction": "events/instruction",
    "issued_event_per_instruction": "events/instruction",
    "memory_event_per_instruction": "events/instruction",
    "vector_event_per_instruction": "events/instruction",
    "fp_event_per_instruction": "events/instruction",
    "alu_event_per_instruction": "events/instruction",
    "retired_per_branch": "events/instruction",
    "issued_per_branch": "events/instruction",
    "alu_per_branch": "events/instruction",
    "retired_per_unit": "events/unit",
    "issued_per_unit": "events/unit",
    "alu_per_unit": "events/unit",
}

CONFIGURATION_COLUMNS = [
    "mnemonic",
    "extension",
    "precision",
    "operand_form",
    "input_profile",
    "profile",
    "kind",
    "width",
    "layout",
    "stride",
    "sew",
    "eew",
    "lmul",
    "vl",
    "vector_bits",
    "egw",
    "element_groups",
    "bytes_per_instruction",
]

DETAIL_COLUMNS = [
    "saturation_chains",
    "first_steady_state_count",
    "steady_state_reached",
    "throughput_samples",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def parse_manifest(
    path: Path,
    root: Path,
) -> list[tuple[str, Path]]:
    entries: list[tuple[str, Path]] = []

    for row in read_csv(path):
        category = row["category"].strip()
        result_path = Path(row["path"])

        if not result_path.is_absolute():
            result_path = root / result_path

        if not category:
            raise ValueError("manifest contains an empty category")

        if not result_path.exists():
            print(
                f"warning: result file does not exist: {result_path}"
            )
            continue

        entries.append((category, result_path))

    return entries


def instruction_name(row: dict[str, str]) -> str:
    for column in ("instruction", "benchmark", "code", "name"):
        value = row.get(column, "").strip()

        if value:
            return value

    raise ValueError(
        "summary row has no instruction, benchmark, code, or name"
    )


def configuration_text(row: dict[str, str]) -> str:
    values = []

    for column in CONFIGURATION_COLUMNS:
        value = row.get(column, "").strip()

        if value:
            values.append(f"{column}={value}")

    return ";".join(values)


def detail_text(row: dict[str, str]) -> str:
    values = []

    for column in DETAIL_COLUMNS:
        value = row.get(column, "").strip()

        if value:
            values.append(f"{column}={value}")

    return ";".join(values)


def parse_number(value: str) -> float | None:
    value = value.strip()

    if not value:
        return None

    try:
        number = float(value)
    except ValueError:
        return None

    if not math.isfinite(number):
        return None

    return number


def collect_measurements(
    entries: list[tuple[str, Path]],
) -> list[dict[str, str]]:
    output_rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()

    for category, path in entries:
        for row in read_csv(path):
            instruction = instruction_name(row)
            configuration = configuration_text(row)
            details = detail_text(row)

            for metric, unit in COMMON_METRICS.items():
                number = parse_number(row.get(metric, ""))

                if number is None:
                    continue

                key = (
                    category,
                    instruction,
                    configuration,
                    metric,
                )

                if key in seen:
                    raise ValueError(
                        "duplicate integrated result: "
                        f"category={category}, "
                        f"instruction={instruction}, "
                        f"metric={metric}"
                    )

                seen.add(key)

                output_rows.append({
                    "category": category,
                    "instruction": instruction,
                    "configuration": configuration,
                    "metric": metric,
                    "value": f"{number:.6f}",
                    "unit": unit,
                    "details": details,
                    "source": str(path),
                })

    return output_rows


def write_long_csv(
    path: Path,
    rows: list[dict[str, str]],
) -> None:
    fieldnames = [
        "category",
        "instruction",
        "configuration",
        "metric",
        "value",
        "unit",
        "details",
        "source",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def metric_map(
    rows: list[dict[str, str]],
) -> dict[tuple[str, str, str], dict[str, str]]:
    measurements: dict[
        tuple[str, str, str],
        dict[str, str],
    ] = defaultdict(dict)

    for row in rows:
        key = (
            row["category"],
            row["instruction"],
            row["configuration"],
        )
        measurements[key][row["metric"]] = row["value"]

    return measurements


def markdown_value(
    metrics: dict[str, str],
    name: str,
) -> str:
    value = metrics.get(name)

    if value is None:
        return ""

    return f"{float(value):.3f}"


def write_markdown(
    path: Path,
    rows: list[dict[str, str]],
) -> None:
    by_category: dict[
        str,
        list[tuple[str, str, dict[str, str]]],
    ] = defaultdict(list)

    for key, metrics in metric_map(rows).items():
        category, instruction, configuration = key
        by_category[category].append(
            (instruction, configuration, metrics)
        )

    lines = [
        "# X100 nanoBench measurement summary",
        "",
        "Values are generated from the command-specific summary CSV files.",
        "",
    ]

    for category in sorted(by_category):
        lines.extend([
            f"## {category}",
            "",
            "| Instruction | Configuration | Latency | Reciprocal throughput "
            "| Maximum throughput | Bytes/cycle | Blocks/cycle |",
            "|---|---|---:|---:|---:|---:|---:|",
        ])

        entries = sorted(
            by_category[category],
            key=lambda entry: (entry[0], entry[1]),
        )

        for instruction, configuration, metrics in entries:
            lines.append(
                f"| `{instruction}` "
                f"| {configuration} "
                f"| {markdown_value(metrics, 'latency')} "
                f"| {markdown_value(metrics, 'reciprocal_throughput')} "
                f"| {markdown_value(metrics, 'max_throughput')} "
                f"| {markdown_value(metrics, 'bytes_per_cycle')} "
                f"| {markdown_value(metrics, 'blocks_per_cycle')} |"
            )

        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_category_counts(
    rows: list[dict[str, str]],
) -> None:
    instructions: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        instructions[row["category"]].add(row["instruction"])

    print("Integrated result summary:")

    for category in sorted(instructions):
        print(
            f"  {category}: "
            f"{len(instructions[category])} instructions"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()

    manifest = args.manifest

    if not manifest.is_absolute():
        manifest = root / manifest

    output_csv = args.output_csv

    if not output_csv.is_absolute():
        output_csv = root / output_csv

    output_markdown = args.output_markdown

    if not output_markdown.is_absolute():
        output_markdown = root / output_markdown

    entries = parse_manifest(manifest, root)
    rows = collect_measurements(entries)

    if not rows:
        raise ValueError("no measurements were collected")

    rows.sort(
        key=lambda row: (
            row["category"],
            row["instruction"],
            row["configuration"],
            row["metric"],
        )
    )

    write_long_csv(output_csv, rows)
    write_markdown(output_markdown, rows)
    write_category_counts(rows)

    print(f"Wrote {output_csv}")
    print(f"Wrote {output_markdown}")


if __name__ == "__main__":
    main()