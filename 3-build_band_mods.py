import argparse
import csv
import hashlib
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build easy/medium/hard mod.paragraphs files from shortlist_candidates.csv"
    )
    parser.add_argument("--shortlist", type=Path, default=Path("shortlist_candidates.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("band_mods"))
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--target-per-band", type=int, default=10)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/poem_pages"))
    return parser.parse_args()


def clean_poem_lines(lines: list[str], title: str) -> list[str]:
    cleaned: list[str] = []
    dropped_title = False
    dropped_byline = False

    normalized_title = re.sub(r"\s+", " ", title).strip().lower()

    for line in lines:
        text = re.sub(r"\s+", " ", line).strip()
        if not text:
            continue

        if not dropped_title and text.lower() == normalized_title:
            dropped_title = True
            continue

        if not dropped_byline and re.match(r"^By\s+", text, flags=re.IGNORECASE):
            dropped_byline = True
            continue

        if "Sponsored Links" in text or text.startswith("Public Domain Poetry"):
            continue

        cleaned.append(text)

    return cleaned


def extract_poem_text(html: str, title: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    blocks: list[list[str]] = []

    for td in soup.find_all("td"):
        raw_text = td.get_text("\n", strip=True)
        if len(raw_text) < 250:
            continue
        if "Main Menu" in raw_text or "Sponsored Links" in raw_text:
            continue
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        if len(lines) < 6:
            continue
        blocks.append(lines)

    if not blocks:
        for td in soup.find_all("td"):
            raw_text = td.get_text("\n", strip=True)
            if len(raw_text) < 180:
                continue
            lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
            if len(lines) >= 6:
                blocks.append(lines)

    if not blocks:
        return ""

    best_lines = max(blocks, key=lambda lines: sum(len(x) for x in lines))
    cleaned_lines = clean_poem_lines(best_lines, title)
    text = " ".join(cleaned_lines)
    text = re.sub(r"\s*Extra\s+Info:.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*Printable\s+Page\s+This\s+page\s+viewed\s+\d+\s+times\.?$", "", text, flags=re.IGNORECASE)

    if title:
        title_pattern = re.escape(re.sub(r"\s+", " ", title).strip())
        text = re.sub(
            rf"^\s*{title_pattern}\s+By\s+[A-Z][\w'.\-]*(?:\s+[A-Z][\w'.\-]*(?:\s*\([^)]+\))?)*\s+",
            "",
            text,
            flags=re.IGNORECASE,
        )

    # Keep the 'By Author', as it's nice to have and also very hard to properly strip it out without accidentally dropping real poem lines.
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _cache_path(cache_dir: Path, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return cache_dir / f"{digest}.html"


def fetch_html_cached(
    session: requests.Session,
    url: str,
    timeout: float,
    cache_dir: Path,
) -> str:
    cache_file = _cache_path(cache_dir, url)
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8", errors="ignore")

    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    html = response.text
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(html, encoding="utf-8")
    return html


def clean_sample_text(text: str) -> str:
    cleaned = re.sub(r"\s*Extra\s+Info:.*$", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def read_shortlist(path: Path) -> dict[str, list[dict[str, str]]]:
    by_band: dict[str, list[dict[str, str]]] = {"easy": [], "medium": [], "hard": []}
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            band = (row.get("band") or "").strip().lower()
            if band not in by_band:
                continue
            by_band[band].append(row)
    return by_band


def write_mod_file(path: Path, paragraphs: list[str]) -> None:
    payload = {"mod": paragraphs}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    by_band = read_shortlist(args.shortlist)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; GlyphicaBandMods/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )

    for band in ("easy", "medium", "hard"):
        paragraphs: list[str] = []
        for row in by_band.get(band, []):
            if len(paragraphs) >= args.target_per_band:
                break
            title = (row.get("title") or "").strip()
            link = (row.get("link") or "").strip()
            if not link:
                continue
            poem_text = ""
            for attempt in range(3):
                try:
                    html = fetch_html_cached(session, link, args.timeout, args.cache_dir)
                    poem_text = extract_poem_text(html, title)
                    if poem_text:
                        break
                except Exception:
                    pass
                time.sleep(0.5 * (attempt + 1))
            if poem_text:
                paragraphs.append(poem_text)
            else:
                fallback = clean_sample_text((row.get("sample_text") or "").strip())
                if fallback:
                    paragraphs.append(fallback)
                    print(f"{band}: fallback sample_text for {title} ({link})")
                else:
                    print(f"{band}: skipped {title} ({link})")

        out_path = args.out_dir / f"mod.paragraphs.{band}"
        write_mod_file(out_path, paragraphs)
        print(f"{band}: wrote {len(paragraphs)} paragraphs -> {out_path}")


if __name__ == "__main__":
    main()
