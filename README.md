# Earnings Transcripts

Automated earnings call transcript fetcher using [API Ninjas](https://api-ninjas.com/api/earningscalltranscript), running on GitHub Actions.

## Overview

This repository automatically fetches earnings call transcripts for S&P 100 companies and stores them as JSON files. The fetcher runs daily via GitHub Actions and commits new transcripts to this repository.

## Data Source

**API Ninjas** - Free tier covers S&P 100 companies (top 100 US stocks by market cap).

Includes: Apple, Microsoft, Amazon, Google, Meta, Tesla, Nvidia, JPMorgan, and 90+ more major companies.

## Setup

### 1. Get API Key

1. Sign up at [api-ninjas.com/register](https://api-ninjas.com/register)
2. Copy your API key from the dashboard

### 2. Add Secret to GitHub

1. Go to your repository Settings
2. Navigate to Secrets and variables → Actions
3. Click "New repository secret"
4. Name: `API_NINJAS_KEY`
5. Value: Your API key

### 3. Enable Actions Permissions

1. Go to Settings → Actions → General
2. Under "Workflow permissions", select "Read and write permissions"
3. Save

## Usage

### Automatic Fetching

The workflow runs daily at 6 AM UTC and fetches the latest transcript for each S&P 100 company.

### Manual Trigger

1. Go to Actions tab
2. Select "Fetch Earnings Transcripts"
3. Click "Run workflow"
4. Options:
   - **tickers**: Comma-separated list (e.g., `AAPL,MSFT,GOOGL`) or leave empty for all
   - **latest_only**: `true` for latest only, `false` for all available

### Local Development

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/earnings-transcripts.git
cd earnings-transcripts

# Setup
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run (set your API key)
export API_NINJAS_KEY="your_api_key_here"
python scrape_transcripts.py

# Or fetch specific tickers
TICKERS="AAPL,MSFT" python scrape_transcripts.py
```

## Transcript Format

Files are saved as `{TICKER}_{YEAR}_Q{QUARTER}.json`:

```json
{
  "ticker": "AAPL",
  "year": 2024,
  "quarter": 4,
  "date": "2024-10-31",
  "transcript": "...",
  "participants": [...],
  "fetched_at": "2024-11-01T06:00:00",
  "source": "api-ninjas"
}
```

## S&P 500 Earnings Calendar

A daily-updated calendar of upcoming S&P 500 earnings calls.

- **[View the Calendar](calendar/EARNINGS_CALENDAR.md)** — human-readable Markdown
- **[JSON Data](calendar/earnings_calendar.json)** — machine-readable structured data

**Data source:** Yahoo Finance via [yfinance](https://pypi.org/project/yfinance/). Updated daily at 8 AM UTC by GitHub Actions.

```bash
# Run locally
python scripts/update_earnings_calendar.py

# Test with a few tickers
python scripts/update_earnings_calendar.py --limit 10

# Refresh S&P 500 list from Wikipedia
python scripts/update_earnings_calendar.py --update-tickers
```

## License

MIT
