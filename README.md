# Public Domain Poetry Scraper

Scrapes poem metadata (title, link, lines, views) from:

`https://www.public-domain-poetry.com/listpoetry.php?letter=All&page=$pageNum`

## Setup

```bash
python -m pip install -r requirements.txt
```

## Run

```bash
python 0-scrape_poems.py
```

Default behavior:
- Fetches pages `1..771`
- Appends each page's rows immediately to `poems.csv`
- Saves resume state in `checkpoint.json` after every page
- Retries transient errors and honors HTTP `429` + `Retry-After`

## Useful options

```bash
python 0-scrape_poems.py --start-page 1 --end-page 771 --output poems.csv --checkpoint checkpoint.json
python 0-scrape_poems.py --no-resume
python 0-scrape_poems.py --delay 1.0 --max-retries 10
```

## Deduplicate CSV

If a crash occurs after writing a page but before checkpoint update, reruns may duplicate that page's rows. Use:

```bash
python 1-dedupe_poems_csv.py --input poems.csv
```

Optional custom key columns:

```bash
python 1-dedupe_poems_csv.py --input poems.csv --key-columns title link lines views source_page
```

## Output columns

- `title`
- `link`
- `lines`
- `views`
- `source_page`

## Build Glyphica boss paragraph mods by difficulty

This repo now includes tools to build three installable `mod.paragraphs` variants:

- `easy`
- `medium`
- `hard`

Difficulty matching is based on typing load with punctuation ignored.

### 1) Create a scored shortlist (cache-aware)

```bash
python 2-shortlist_poems.py --per-band 10 --output shortlist_candidates.csv --max-fetch 800
```

Notes:
- Uses on-disk HTML caching in `.cache/poem_pages` to avoid repeatedly requesting the same URLs.
- Re-running the command reuses cache whenever possible.

### 2) Build per-band `mod.paragraphs` files

```bash
python 3-build_band_mods.py --shortlist shortlist_candidates.csv --out-dir band_mods --target-per-band 10
```

Outputs:
- `band_mods/mod.paragraphs.easy`
- `band_mods/mod.paragraphs.medium`
- `band_mods/mod.paragraphs.hard`

### 3) Install one difficulty variant

1. Choose one file from `band_mods/`.
2. Copy it to your mod folder as `mod.paragraphs`.

Example target folder:

`.../mods/<your_mod>/content/mod.paragraphs`

Tip: Keep backups of each difficulty file so players can swap by replacing `mod.paragraphs`.

### 4) Compare vanilla vs modded paragraph stats (graphs)

```bash
python 4-compare_paragraph_sets.py
```

Outputs are written to `analysis_graphs/`.

## Resume behavior

If interrupted, rerun with default options (or `--resume`) and it continues from the saved `next_page` in `checkpoint.json`.
If interruption happens after writing a page but before checkpoint update, that page may be re-fetched on restart.
