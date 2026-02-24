import argparse
import csv
import json
import logging
import random
import time
from pathlib import Path
from typing import Dict, List
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL_TEMPLATE = "https://www.public-domain-poetry.com/listpoetry.php?letter=All&page={page}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape poem title/link/lines/views from public-domain-poetry.com"
    )
    parser.add_argument("--start-page", type=int, default=1, help="First page to fetch")
    parser.add_argument("--end-page", type=int, default=771, help="Last page to fetch")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("poems.csv"),
        help="CSV output path",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=Path("checkpoint.json"),
        help="Checkpoint file path",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Base delay in seconds between successful requests",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=8,
        help="Max retries per page for transient/rate-limit responses",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Resume from checkpoint if it exists (default: true)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="Ignore checkpoint and start from --start-page",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    return parser.parse_args()


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def load_checkpoint(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        next_page = data.get("next_page")
        if isinstance(next_page, int) and next_page >= 1:
            return next_page
    except Exception as exc:
        logging.warning("Could not read checkpoint %s: %s", path, exc)
    return None


def save_checkpoint(path: Path, next_page: int) -> None:
    path.write_text(json.dumps({"next_page": next_page}, indent=2), encoding="utf-8")


def ensure_csv_header(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["title", "link", "lines", "views", "source_page"],
            )
            writer.writeheader()


def parse_poem_rows(html: str, page: int, base_url: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")

    target_table = None
    for table in soup.find_all("table"):
        header_cells = [
            c.get_text(" ", strip=True).lower() for c in table.find_all("tr")[0].find_all(["td", "th"])
        ] if table.find_all("tr") else []
        if {"poem title", "author", "lines", "views"}.issubset(set(header_cells)):
            target_table = table
            break

    if target_table is None:
        raise ValueError(f"Could not find poems table on page {page}")

    rows: List[Dict[str, str]] = []
    tr_list = target_table.find_all("tr")
    for tr in tr_list[1:]:
        cells = tr.find_all("td")
        if len(cells) < 4:
            continue

        title_cell = cells[0]
        title = title_cell.get_text(" ", strip=True)
        anchor = title_cell.find("a", href=True)
        link = urljoin(base_url, anchor["href"]) if anchor else ""

        lines = cells[2].get_text(" ", strip=True)
        views = cells[3].get_text(" ", strip=True)

        if not title:
            continue

        rows.append(
            {
                "title": title,
                "link": link,
                "lines": lines,
                "views": views,
                "source_page": str(page),
            }
        )

    return rows


def compute_backoff_seconds(response: requests.Response | None, attempt: int, base_delay: float) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass

    # Exponential backoff with jitter
    exp = min(60.0, base_delay * (2 ** (attempt - 1)))
    jitter = random.uniform(0, 0.5 * base_delay + 0.1)
    return exp + jitter


def fetch_html_with_retries(
    session: requests.Session,
    url: str,
    timeout: float,
    max_retries: int,
    base_delay: float,
) -> str:
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        response = None
        try:
            response = session.get(url, timeout=timeout)
            status = response.status_code

            if status == 200:
                return response.text

            if status in {429, 500, 502, 503, 504}:
                wait_s = compute_backoff_seconds(response, attempt, base_delay)
                logging.warning(
                    "Transient HTTP %s for %s (attempt %s/%s). Waiting %.2fs.",
                    status,
                    url,
                    attempt,
                    max_retries,
                    wait_s,
                )
                time.sleep(wait_s)
                continue

            response.raise_for_status()

        except requests.RequestException as exc:
            last_error = exc
            wait_s = compute_backoff_seconds(response, attempt, base_delay)
            logging.warning(
                "Request error for %s (attempt %s/%s): %s. Waiting %.2fs.",
                url,
                attempt,
                max_retries,
                exc,
                wait_s,
            )
            time.sleep(wait_s)

    raise RuntimeError(f"Failed to fetch {url} after {max_retries} attempts") from last_error


def append_rows_to_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["title", "link", "lines", "views", "source_page"],
        )
        writer.writerows(rows)
        f.flush()


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)

    if args.end_page < args.start_page:
        raise ValueError("--end-page must be >= --start-page")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)

    ensure_csv_header(args.output)

    start_page = args.start_page
    if args.resume:
        checkpoint_page = load_checkpoint(args.checkpoint)
        if checkpoint_page is not None:
            start_page = max(start_page, checkpoint_page)
            logging.info("Resuming from checkpoint page %s", start_page)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; PoetryScraper/1.0; +https://example.com)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )

    run_start = time.monotonic()
    total_pages = args.end_page - start_page + 1

    for page in range(start_page, args.end_page + 1):
        url = BASE_URL_TEMPLATE.format(page=page)
        logging.info("Fetching page %s/%s: %s", page, args.end_page, url)

        html = fetch_html_with_retries(
            session=session,
            url=url,
            timeout=args.timeout,
            max_retries=args.max_retries,
            base_delay=args.delay,
        )

        rows = parse_poem_rows(html, page=page, base_url=url)
        append_rows_to_csv(args.output, rows)

        save_checkpoint(args.checkpoint, next_page=page + 1)
        completed_pages = page - start_page + 1
        elapsed_seconds = time.monotonic() - run_start
        avg_seconds_per_page = elapsed_seconds / completed_pages
        remaining_pages = total_pages - completed_pages
        eta_seconds = avg_seconds_per_page * remaining_pages

        logging.info(
            "Saved %s rows from page %s | Progress: %s/%s | Elapsed: %s | ETA: %s",
            len(rows),
            page,
            completed_pages,
            total_pages,
            format_duration(elapsed_seconds),
            format_duration(eta_seconds),
        )

        if args.delay > 0:
            time.sleep(args.delay)

    logging.info("Done. Data written to %s", args.output)


if __name__ == "__main__":
    main()
