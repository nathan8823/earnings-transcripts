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
```

## Architecture

**Single-file scraper**: `scrape_transcripts.py` contains the complete scraping logic.

**MotleyFoolScraper class**:
- `get_recent_transcripts()` - Fetches transcript URLs from the main listings page
- `scrape_transcript()` - Parses individual transcript pages using BeautifulSoup
- `transcript_exists()` - Deduplication via URL hash matching against existing files
- `save_transcript()` - Stores as JSON with metadata

**Data flow**:
1. Scrape listing page at `fool.com/earnings-call-transcripts/`
2. Extract ticker, quarter, year from title (regex pattern: `Company (TICKER) Q# YYYY`)
3. Fetch full transcript content, separating prepared remarks from Q&A
4. Save as `{TICKER}_{YEAR}_Q{QUARTER}_{url_hash}.json`

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

## GitHub Actions

Workflow runs daily at 6 AM UTC. Manual triggers accept `transcript_limit` and `tickers` parameters.
