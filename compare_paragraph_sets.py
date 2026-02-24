import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median

import matplotlib.pyplot as plt


DEFAULT_DATASETS = [
    (
        "vanilla",
        r"c:\Users\elec0\Documents\Sphere Saves\aliasblack.glyphica\mods\new_mod_1771905747820\content\mod.paragraphs",
    ),
    ("easy", "band_mods/mod.paragraphs.easy"),
    ("medium", "band_mods/mod.paragraphs.medium"),
    ("hard", "band_mods/mod.paragraphs.hard"),
]


@dataclass
class ParagraphMetrics:
    dataset: str
    index: int
    raw_chars: int
    typed_chars: int
    words: int
    unique_words: int
    avg_word_len: float
    punctuation_removed: int
    punctuation_ratio: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare vanilla vs mod paragraph sets and generate metric charts."
    )
    parser.add_argument(
        "--dataset",
        action="append",
        default=[],
        help="Dataset spec in the form NAME=PATH. Can be passed multiple times.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("analysis_graphs"))
    return parser.parse_args()


def parse_dataset_specs(specs: list[str]) -> list[tuple[str, Path]]:
    if not specs:
        return [(name, Path(path)) for name, path in DEFAULT_DATASETS]

    parsed: list[tuple[str, Path]] = []
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"Invalid --dataset value '{spec}'. Expected NAME=PATH")
        name, path = spec.split("=", 1)
        name = name.strip()
        path = path.strip()
        if not name or not path:
            raise ValueError(f"Invalid --dataset value '{spec}'. Expected NAME=PATH")
        parsed.append((name, Path(path)))
    return parsed


def normalize_typed_text(text: str) -> str:
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compute_metrics(dataset: str, index: int, text: str) -> ParagraphMetrics:
    raw_chars = len(text)
    typed_text = normalize_typed_text(text)
    typed_chars = len(typed_text)
    words_list = re.findall(r"\w+", typed_text, flags=re.UNICODE)
    words = len(words_list)
    unique_words = len({word.lower() for word in words_list})
    avg_word_len = mean([len(word) for word in words_list]) if words_list else 0.0
    punctuation_removed = max(raw_chars - typed_chars, 0)
    punctuation_ratio = (punctuation_removed / raw_chars) if raw_chars else 0.0

    return ParagraphMetrics(
        dataset=dataset,
        index=index,
        raw_chars=raw_chars,
        typed_chars=typed_chars,
        words=words,
        unique_words=unique_words,
        avg_word_len=avg_word_len,
        punctuation_removed=punctuation_removed,
        punctuation_ratio=punctuation_ratio,
    )


def load_paragraphs(path: Path) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    paragraphs = payload.get("mod")
    if not isinstance(paragraphs, list):
        raise ValueError(f"File {path} does not contain a 'mod' list")
    return [str(p) for p in paragraphs]


def write_metrics_csv(path: Path, all_metrics: list[ParagraphMetrics]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "dataset",
                "index",
                "raw_chars",
                "typed_chars",
                "words",
                "unique_words",
                "avg_word_len",
                "punctuation_removed",
                "punctuation_ratio",
            ],
        )
        writer.writeheader()
        for row in all_metrics:
            writer.writerow(
                {
                    "dataset": row.dataset,
                    "index": row.index,
                    "raw_chars": row.raw_chars,
                    "typed_chars": row.typed_chars,
                    "words": row.words,
                    "unique_words": row.unique_words,
                    "avg_word_len": f"{row.avg_word_len:.4f}",
                    "punctuation_removed": row.punctuation_removed,
                    "punctuation_ratio": f"{row.punctuation_ratio:.6f}",
                }
            )


def write_summary_json(path: Path, by_dataset: dict[str, list[ParagraphMetrics]]) -> None:
    summary: dict[str, dict[str, float | int]] = {}
    for name, rows in by_dataset.items():
        typed = [r.typed_chars for r in rows]
        words = [r.words for r in rows]
        uniq = [r.unique_words for r in rows]
        punct = [r.punctuation_ratio for r in rows]

        summary[name] = {
            "count": len(rows),
            "typed_chars_mean": round(mean(typed), 2),
            "typed_chars_median": round(median(typed), 2),
            "typed_chars_min": min(typed),
            "typed_chars_max": max(typed),
            "words_mean": round(mean(words), 2),
            "words_median": round(median(words), 2),
            "words_min": min(words),
            "words_max": max(words),
            "unique_words_mean": round(mean(uniq), 2),
            "punctuation_ratio_mean": round(mean(punct), 4),
        }

    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def plot_boxplots(path: Path, by_dataset: dict[str, list[ParagraphMetrics]]) -> None:
    names = list(by_dataset.keys())
    typed_data = [[r.typed_chars for r in by_dataset[name]] for name in names]
    word_data = [[r.words for r in by_dataset[name]] for name in names]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    axes[0].boxplot(typed_data, tick_labels=names)
    axes[0].set_title("Typed Characters (punctuation ignored)")
    axes[0].set_ylabel("Characters")

    axes[1].boxplot(word_data, tick_labels=names)
    axes[1].set_title("Word Count")
    axes[1].set_ylabel("Words")

    for ax in axes:
        ax.tick_params(axis="x", rotation=20)
        ax.grid(alpha=0.25)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_histograms(path: Path, by_dataset: dict[str, list[ParagraphMetrics]]) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    for name, rows in by_dataset.items():
        values = [r.typed_chars for r in rows]
        ax.hist(values, bins=8, alpha=0.5, label=name)

    ax.set_title("Distribution of Typed Characters")
    ax.set_xlabel("Typed characters")
    ax.set_ylabel("Count")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_scatter(path: Path, by_dataset: dict[str, list[ParagraphMetrics]]) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    for name, rows in by_dataset.items():
        x = [r.words for r in rows]
        y = [r.typed_chars for r in rows]
        ax.scatter(x, y, label=name, alpha=0.8)

    ax.set_title("Words vs Typed Characters")
    ax.set_xlabel("Words")
    ax.set_ylabel("Typed characters")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_mean_bars(path: Path, by_dataset: dict[str, list[ParagraphMetrics]]) -> None:
    names = list(by_dataset.keys())
    typed_means = [mean([r.typed_chars for r in by_dataset[name]]) for name in names]
    words_means = [mean([r.words for r in by_dataset[name]]) for name in names]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    axes[0].bar(names, typed_means)
    axes[0].set_title("Average Typed Characters")
    axes[0].set_ylabel("Characters")
    axes[0].tick_params(axis="x", rotation=20)
    axes[0].grid(axis="y", alpha=0.25)

    axes[1].bar(names, words_means)
    axes[1].set_title("Average Word Count")
    axes[1].set_ylabel("Words")
    axes[1].tick_params(axis="x", rotation=20)
    axes[1].grid(axis="y", alpha=0.25)

    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    dataset_specs = parse_dataset_specs(args.dataset)

    by_dataset: dict[str, list[ParagraphMetrics]] = {}
    all_rows: list[ParagraphMetrics] = []

    for name, path in dataset_specs:
        paragraphs = load_paragraphs(path)
        rows = [compute_metrics(name, index + 1, text) for index, text in enumerate(paragraphs)]
        by_dataset[name] = rows
        all_rows.extend(rows)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_metrics_csv(args.output_dir / "paragraph_metrics.csv", all_rows)
    write_summary_json(args.output_dir / "dataset_summary.json", by_dataset)

    plot_boxplots(args.output_dir / "boxplots_chars_words.png", by_dataset)
    plot_histograms(args.output_dir / "hist_typed_chars.png", by_dataset)
    plot_scatter(args.output_dir / "scatter_words_vs_chars.png", by_dataset)
    plot_mean_bars(args.output_dir / "means_chars_words.png", by_dataset)

    print(f"Wrote analysis outputs to: {args.output_dir}")
    for name, rows in by_dataset.items():
        typed = [r.typed_chars for r in rows]
        words = [r.words for r in rows]
        print(
            f"- {name}: count={len(rows)}, typed_chars_mean={mean(typed):.1f}, words_mean={mean(words):.1f}"
        )


if __name__ == "__main__":
    main()
