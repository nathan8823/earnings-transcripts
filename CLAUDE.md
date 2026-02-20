# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository scrapes earnings call transcripts from The Motley Fool and stores them as JSON files. It runs automatically via GitHub Actions and feeds data to the companion [earnings-podcasts](https://github.com/nathan8823/earnings-podcasts) repository.

## Commands

```bash
# Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run scraper (fetches 10 transcripts by default)
python scrape_transcripts.py

# Fetch specific tickers
TICKERS="AAPL,MSFT" python scrape_transcripts.py

# Change transcript limit
TRANSCRIPT_LIMIT=20 python scrape_transcripts.py

# Update earnings calendar (all S&P 500)
python scripts/update_earnings_calendar.py

# Calendar with limited tickers (for testing)
python scripts/update_earnings_calendar.py --limit 10

# Refresh S&P 500 list from Wikipedia
python scripts/update_earnings_calendar.py --update-tickers

# Dry run (no file writes)
python scripts/update_earnings_calendar.py --dry-run
```

## Architecture

**Single-file scraper**: `scrape_transcripts.py` contains the complete scraping logic.

**MotleyFoolScraper class**:
- `get_transcripts_from_sitemap()` - Discovers transcript URLs via `fool.com/sitemap/YYYY/MM` (checks current + previous month)
- `_extract_ticker_from_slug()` - Extracts ticker from URL slug (e.g., `walmart-wmt-q4-2026-...` → `WMT`). Special-cases `BRK-B`.
- `scrape_transcript()` - Parses individual transcript pages using BeautifulSoup
- `transcript_exists()` - Deduplication via URL hash matching against existing files
- `save_transcript()` - Stores as JSON with metadata

**Data flow**:
1. Fetch monthly sitemaps at `fool.com/sitemap/YYYY/MM` (current + previous month)
2. Filter URLs matching `/earnings/call-transcripts/` and extract tickers from URL slugs
3. Filter by target ticker list (from `TICKERS` env var)
4. Fetch full transcript content, separating prepared remarks from Q&A
5. Save as `{TICKER}_{YEAR}_Q{QUARTER}_{url_hash}.json`

**Why sitemap instead of listing page?** The listing page at `fool.com/earnings-call-transcripts/` only shows today's transcripts (~20). Transcripts from previous days are not accessible. The sitemap has ALL transcripts for the entire month.

**Rate limiting**: 2-second delay between requests (`RATE_LIMIT_SECONDS`)

## Transcript JSON Format

```json
{
  "ticker": "AAPL",
  "company": "Apple",
  "year": 2024,
  "quarter": 4,
  "transcript": "full text...",
  "prepared_remarks": "...",
  "qa_section": "...",
  "url": "source URL",
  "source": "motley-fool"
}
```

## Earnings Calendar

**Script**: `scripts/update_earnings_calendar.py` — fetches upcoming earnings dates for all S&P 500 companies.

**EarningsCalendarUpdater class**:
- `fetch_sp500_list()` — scrapes Wikipedia, saves `calendar/sp500_tickers.json`
- `fetch_earnings_dates()` — queries yfinance for each ticker's next earnings date
- `generate_json()` — writes `calendar/earnings_calendar.json` (sorted by date, with weekly buckets)
- `generate_markdown()` — writes `calendar/EARNINGS_CALENDAR.md` (week-by-week tables)

**Data source**: Yahoo Finance via yfinance (no API key needed).

**Rate limiting**: 0.5s between tickers. Full run (~500 tickers) takes ~5 minutes.

**Output files**:
- `calendar/sp500_tickers.json` — S&P 500 constituent list (refresh with `--update-tickers`)
- `calendar/earnings_calendar.json` — structured earnings data (consumed by betafinch.com)
- `calendar/EARNINGS_CALENDAR.md` — human-readable calendar viewable on GitHub

**Consumer**: The earnings-podcasts website fetches `earnings_calendar.json` from this repo's raw GitHub URL to display "Next Episode" dates on individual podcast pages (`website/src/data/earningsCalendar.ts`).

## GitHub Actions

**scrape.yml**: Transcript scraper, daily at 6 AM UTC. Uses Motley Fool sitemap (`fool.com/sitemap/YYYY/MM`) to discover all transcripts for the current and previous month, filtered by target ticker list (116 tickers). On success, triggers podcast generation in `earnings-podcasts` repo via `repository_dispatch`. Manual triggers accept `transcript_limit` and `tickers` parameters.

**calendar.yml**: Earnings calendar updater, daily at 8 AM UTC. Manual trigger accepts `update_tickers` (bool) and `limit` (number) inputs.
