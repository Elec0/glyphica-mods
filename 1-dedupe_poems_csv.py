import argparse
import csv
from pathlib import Path
from tempfile import NamedTemporaryFile


DEFAULT_COLUMNS = ["title", "link", "lines", "views", "source_page"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove duplicate rows from the scraper CSV output."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("poems.csv"),
        help="Input CSV file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output CSV path. If omitted, rewrites --input in-place.",
    )
    parser.add_argument(
        "--key-columns",
        nargs="+",
        default=DEFAULT_COLUMNS,
        help="Columns used to determine duplicates (default: all scraper columns).",
    )
    return parser.parse_args()


def dedupe_csv(input_path: Path, output_path: Path, key_columns: list[str]) -> tuple[int, int]:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    seen: set[tuple[str, ...]] = set()
    total = 0
    kept = 0

    with input_path.open("r", newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise ValueError("Input CSV has no header row.")

        missing = [col for col in key_columns if col not in reader.fieldnames]
        if missing:
            raise ValueError(f"Missing key columns in CSV header: {', '.join(missing)}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=reader.fieldnames)
            writer.writeheader()

            for row in reader:
                total += 1
                key = tuple((row.get(col) or "").strip() for col in key_columns)
                if key in seen:
                    continue
                seen.add(key)
                writer.writerow(row)
                kept += 1

    return total, kept


def dedupe_in_place(input_path: Path, key_columns: list[str]) -> tuple[int, int]:
    with NamedTemporaryFile("w", delete=False, suffix=".csv", encoding="utf-8", newline="") as tmp:
        temp_path = Path(tmp.name)

    try:
        total, kept = dedupe_csv(input_path, temp_path, key_columns)
        temp_path.replace(input_path)
        return total, kept
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def main() -> None:
    args = parse_args()

    if args.output is None:
        total, kept = dedupe_in_place(args.input, args.key_columns)
        print(f"Done. Kept {kept}/{total} rows in {args.input}")
    else:
        total, kept = dedupe_csv(args.input, args.output, args.key_columns)
        print(f"Done. Kept {kept}/{total} rows in {args.output}")


if __name__ == "__main__":
    main()
