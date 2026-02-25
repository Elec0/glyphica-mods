import argparse
import csv
from pathlib import Path

BAND_ORDER = ["easy", "medium", "hard"]


def slug_to_author_name(link: str) -> str:
    """Extract and prettify the author slug from a public-domain-poetry URL."""
    parts = link.strip("/").split("/")
    if len(parts) < 2:
        return "Unknown Author"

    author_slug = parts[-2]
    return " ".join(word.capitalize() for word in author_slug.split("-"))


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [row for row in reader]


def build_output(rows: list[dict[str, str]]) -> str:
    grouped: dict[str, list[dict[str, str]]] = {band: [] for band in BAND_ORDER}

    for row in rows:
        band = (row.get("band") or "").strip().lower()
        if band in grouped:
            grouped[band].append(row)

    lines: list[str] = []
    for idx, band in enumerate(BAND_ORDER):
        lines.append(f"[h2]Poems included - {band}[/h2]")

        for row in grouped[band]:
            link = (row.get("link") or "").strip()
            title = (row.get("title") or "").strip()
            author = slug_to_author_name(link)
            lines.append(f"* [url={link}]{title} by {author}[/url]")

        if idx < len(BAND_ORDER) - 1:
            lines.append("")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Format shortlist_candidates.csv into forum-style poem lists."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("shortlist_candidates.csv"),
        help="Path to shortlist CSV (default: shortlist_candidates.csv)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output file path. Prints to stdout if omitted.",
    )

    args = parser.parse_args()
    rows = load_rows(args.input)
    formatted = build_output(rows)

    if args.output:
        args.output.write_text(formatted, encoding="utf-8")
    else:
        print(formatted, end="")


if __name__ == "__main__":
    main()
