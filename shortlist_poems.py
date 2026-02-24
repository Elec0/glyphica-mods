import argparse
import csv
import hashlib
import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import quantiles

import requests
from bs4 import BeautifulSoup


DEFAULT_MOD_PARAGRAPHS = Path(
    r"c:\Users\elec0\Documents\Sphere Saves\aliasblack.glyphica\mods\new_mod_1771905747820\content\mod.paragraphs"
)


@dataclass
class Candidate:
    title: str
    link: str
    lines: int
    views: int
    typed_chars: int
    words: int
    text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a balanced shortlist of poems by typing difficulty (ignoring punctuation)."
    )
    parser.add_argument("--poems-csv", type=Path, default=Path("poems.csv"))
    parser.add_argument("--mod-paragraphs", type=Path, default=DEFAULT_MOD_PARAGRAPHS)
    parser.add_argument("--per-band", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("shortlist_candidates.csv"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--max-fetch", type=int, default=300)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/poem_pages"))
    return parser.parse_args()


def normalize_for_difficulty(text: str) -> str:
    text = re.sub(r"[^\w\s]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def score_text(text: str) -> tuple[int, int]:
    normalized = normalize_for_difficulty(text)
    words = len(re.findall(r"\w+", normalized, flags=re.UNICODE))
    return len(normalized), words


def load_baseline_ranges(mod_path: Path) -> dict[str, tuple[tuple[int, int], tuple[int, int]]]:
    data = json.loads(mod_path.read_text(encoding="utf-8"))
    passages = data.get("mod", [])
    if not passages:
        raise ValueError(f"No passages found in {mod_path}")

    metrics = [score_text(text) for text in passages]
    char_values = sorted(chars for chars, _ in metrics)
    word_values = sorted(words for _, words in metrics)

    char_q1, char_q2 = quantiles(char_values, n=3, method="inclusive")
    word_q1, word_q2 = quantiles(word_values, n=3, method="inclusive")

    char_min = min(char_values)
    char_max = max(char_values)
    word_min = min(word_values)
    word_max = max(word_values)

    return {
        "easy": ((char_min, int(char_q1)), (word_min, int(word_q1))),
        "medium": ((int(char_q1) + 1, int(char_q2)), (int(word_q1) + 1, int(word_q2))),
        "hard": ((int(char_q2) + 1, char_max + 80), (int(word_q2) + 1, word_max + 20)),
    }


def load_poems(csv_path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen_links: set[str] = set()

    with csv_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = (row.get("title") or "").strip()
            link = (row.get("link") or "").strip()
            lines_raw = (row.get("lines") or "").strip()
            views_raw = (row.get("views") or "").strip()

            if not title or not link or title.startswith("Sponsored Links"):
                continue
            if not lines_raw.isdigit():
                continue
            if link in seen_links:
                continue

            seen_links.add(link)
            rows.append(
                {
                    "title": title,
                    "link": link,
                    "lines": int(lines_raw),
                    "views": int(views_raw) if views_raw.isdigit() else 0,
                }
            )

    return rows


def extract_poem_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []
    for td in soup.find_all("td"):
        text = td.get_text("\n", strip=True)
        if len(text) < 250:
            continue
        if "Main Menu" in text or "Sponsored Links" in text:
            continue
        candidates.append(text)

    if not candidates:
        return ""

    best = max(candidates, key=len)
    lines = [line.strip() for line in best.splitlines() if line.strip()]

    drop_prefixes = (
        "Public Domain Poetry",
        "By ",
        "Read, rate",
        "Main Menu",
    )
    cleaned: list[str] = []
    for line in lines:
        if any(line.startswith(prefix) for prefix in drop_prefixes):
            continue
        cleaned.append(line)

    return " ".join(cleaned)


def fetch_candidate_text(session: requests.Session, url: str, timeout: float) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return extract_poem_text(response.text)


def _cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.html"


def fetch_candidate_text_cached(
    session: requests.Session,
    url: str,
    timeout: float,
    cache_dir: Path,
) -> str:
    cache_file = _cache_path(cache_dir, url)
    if cache_file.exists():
        html = cache_file.read_text(encoding="utf-8", errors="ignore")
        return extract_poem_text(html)

    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    html = response.text
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(html, encoding="utf-8")
    return extract_poem_text(html)


def in_band(candidate: Candidate, band: tuple[tuple[int, int], tuple[int, int]]) -> bool:
    (char_min, char_max), (word_min, word_max) = band
    return (
        char_min <= candidate.typed_chars <= char_max
        and word_min <= candidate.words <= word_max
    )


def main() -> None:
    args = parse_args()
    random.seed(args.seed)

    bands = load_baseline_ranges(args.mod_paragraphs)
    all_poems = load_poems(args.poems_csv)

    rough_pool = [row for row in all_poems if 8 <= int(row["lines"]) <= 60]
    rough_pool.sort(key=lambda row: (int(row["views"]), -int(row["lines"])), reverse=True)

    shortlisted: dict[str, list[Candidate]] = {"easy": [], "medium": [], "hard": []}
    attempted = 0

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; GlyphicaShortlist/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )

    for row in rough_pool:
        if all(len(shortlisted[name]) >= args.per_band for name in shortlisted):
            break
        if attempted >= args.max_fetch:
            break

        attempted += 1
        try:
            text = fetch_candidate_text_cached(
                session,
                str(row["link"]),
                args.timeout,
                args.cache_dir,
            )
        except Exception:
            continue

        if not text:
            continue

        typed_chars, words = score_text(text)
        candidate = Candidate(
            title=str(row["title"]),
            link=str(row["link"]),
            lines=int(row["lines"]),
            views=int(row["views"]),
            typed_chars=typed_chars,
            words=words,
            text=text,
        )

        for band_name, band in bands.items():
            if len(shortlisted[band_name]) >= args.per_band:
                continue
            if in_band(candidate, band):
                shortlisted[band_name].append(candidate)
                break

        time.sleep(args.delay)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "band",
            "title",
            "link",
            "lines",
            "views",
            "typed_chars",
            "words",
            "sample_text",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for band_name in ["easy", "medium", "hard"]:
            for candidate in shortlisted[band_name]:
                writer.writerow(
                    {
                        "band": band_name,
                        "title": candidate.title,
                        "link": candidate.link,
                        "lines": candidate.lines,
                        "views": candidate.views,
                        "typed_chars": candidate.typed_chars,
                        "words": candidate.words,
                        "sample_text": candidate.text[:300],
                    }
                )

    print("Baseline bands (typed_chars / words):")
    for name in ["easy", "medium", "hard"]:
        char_band, word_band = bands[name]
        print(f"  {name}: chars={char_band}, words={word_band}, selected={len(shortlisted[name])}")
    print(f"Attempted fetches: {attempted}")
    print(f"Wrote: {args.output}")


if __name__ == "__main__":
    main()
