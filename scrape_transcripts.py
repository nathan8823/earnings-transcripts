#!/usr/bin/env python3
"""
Earnings Call Transcript Fetcher

Fetches earnings call transcripts from API Ninjas and stores them as JSON files.
Designed to run via GitHub Actions on a schedule.

Free tier: S&P 100 companies only
Sign up for API key at: https://api-ninjas.com/register
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests

# Configuration
TRANSCRIPTS_DIR = Path("transcripts")
RATE_LIMIT_SECONDS = 1  # Delay between API requests
API_BASE_URL = "https://api.api-ninjas.com/v1"

# S&P 100 tickers (free tier limit)
# Update this list as needed - these are the largest US companies
SP100_TICKERS = [
    "AAPL", "MSFT", "AMZN", "NVDA", "GOOGL", "META", "TSLA", "BRK.B", "UNH", "XOM",
    "JPM", "JNJ", "V", "PG", "MA", "HD", "CVX", "MRK", "ABBV", "LLY",
    "PEP", "KO", "COST", "AVGO", "WMT", "MCD", "CSCO", "TMO", "ABT", "ACN",
    "DHR", "NEE", "VZ", "ADBE", "NKE", "PM", "TXN", "WFC", "RTX", "COP",
    "BMY", "UPS", "MS", "HON", "QCOM", "UNP", "LOW", "ORCL", "IBM", "GE",
    "CAT", "BA", "AMGN", "SBUX", "DE", "PLD", "INTC", "INTU", "GS", "BLK",
    "AMD", "GILD", "AXP", "MDLZ", "ADI", "ISRG", "SYK", "BKNG", "VRTX", "REGN",
    "CVS", "SCHW", "TJX", "PGR", "LRCX", "MMC", "CI", "C", "CB", "ZTS",
    "SO", "DUK", "MO", "TMUS", "EOG", "BSX", "BDX", "CME", "CL", "SLB",
    "NOC", "ITW", "FDX", "USB", "EMR", "PNC", "WM", "AON", "TGT", "FCX"
]


class TranscriptFetcher:
    """Fetcher for earnings call transcripts via API Ninjas."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": api_key,
            "Accept": "application/json",
        })
        TRANSCRIPTS_DIR.mkdir(exist_ok=True)

    def get_available_transcripts(self, ticker: str) -> list[dict]:
        """
        Get list of available transcript year/quarter combinations for a ticker.

        Args:
            ticker: Stock ticker symbol (e.g., 'AAPL')

        Returns:
            List of dicts with 'year' and 'quarter' keys
        """
        url = f"{API_BASE_URL}/earningstranscriptsearch"
        params = {"ticker": ticker}

        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching transcript list for {ticker}: {e}")
            return []

    def fetch_transcript(self, ticker: str, year: int = None, quarter: int = None) -> dict | None:
        """
        Fetch a single transcript from API Ninjas.

        Args:
            ticker: Stock ticker symbol
            year: Earnings year (optional, defaults to latest)
            quarter: Quarter 1-4 (optional, defaults to latest)

        Returns:
            Dict with transcript data or None if fetch fails
        """
        url = f"{API_BASE_URL}/earningstranscript"
        params = {"ticker": ticker}

        if year and quarter:
            params["year"] = year
            params["quarter"] = quarter

        try:
            time.sleep(RATE_LIMIT_SECONDS)
            response = self.session.get(url, params=params)
            response.raise_for_status()

            data = response.json()

            # API returns error message if no transcript found
            if isinstance(data, dict) and "error" in data:
                print(f"No transcript found for {ticker}: {data['error']}")
                return None

            return data

        except requests.RequestException as e:
            print(f"Error fetching transcript for {ticker}: {e}")
            return None

    def generate_filename(self, ticker: str, year: int, quarter: int) -> str:
        """Generate a unique filename for the transcript."""
        return f"{ticker}_{year}_Q{quarter}.json"

    def transcript_exists(self, ticker: str, year: int, quarter: int) -> bool:
        """Check if transcript has already been fetched."""
        filename = self.generate_filename(ticker, year, quarter)
        filepath = TRANSCRIPTS_DIR / filename
        return filepath.exists()

    def save_transcript(self, transcript: dict, ticker: str, year: int, quarter: int) -> str:
        """
        Save transcript to JSON file.

        Args:
            transcript: Dict containing transcript data
            ticker: Stock ticker symbol
            year: Earnings year
            quarter: Quarter number

        Returns:
            Path to saved file
        """
        filename = self.generate_filename(ticker, year, quarter)
        filepath = TRANSCRIPTS_DIR / filename

        # Add metadata
        transcript["ticker"] = ticker
        transcript["year"] = year
        transcript["quarter"] = quarter
        transcript["fetched_at"] = datetime.now().isoformat()
        transcript["filename"] = filename
        transcript["source"] = "api-ninjas"

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(transcript, f, indent=2, ensure_ascii=False)

        print(f"Saved: {filepath}")
        return str(filepath)

    def run(self, tickers: list[str] = None, latest_only: bool = True) -> list[str]:
        """
        Main fetching loop.

        Args:
            tickers: List of tickers to fetch (defaults to SP100_TICKERS)
            latest_only: If True, only fetch the most recent transcript per ticker

        Returns:
            List of saved file paths
        """
        if tickers is None:
            tickers = SP100_TICKERS

        print(f"Starting transcript fetcher at {datetime.now().isoformat()}")
        print(f"Processing {len(tickers)} tickers")
        saved_files = []
        errors = 0

        for i, ticker in enumerate(tickers):
            print(f"\n[{i+1}/{len(tickers)}] Processing {ticker}...")

            if latest_only:
                # Fetch only the latest transcript
                transcript = self.fetch_transcript(ticker)
                if transcript:
                    year = transcript.get("year")
                    quarter = transcript.get("quarter")

                    if year and quarter:
                        if self.transcript_exists(ticker, year, quarter):
                            print(f"  Skipping (already exists): {ticker} {year} Q{quarter}")
                            continue

                        filepath = self.save_transcript(transcript, ticker, year, quarter)
                        saved_files.append(filepath)
                    else:
                        print(f"  Warning: Missing year/quarter in response for {ticker}")
                        errors += 1
                else:
                    errors += 1
            else:
                # Fetch all available transcripts
                available = self.get_available_transcripts(ticker)
                for item in available:
                    year = item.get("year")
                    quarter = item.get("quarter")

                    if not year or not quarter:
                        continue

                    if self.transcript_exists(ticker, year, quarter):
                        print(f"  Skipping (already exists): {ticker} {year} Q{quarter}")
                        continue

                    transcript = self.fetch_transcript(ticker, year, quarter)
                    if transcript:
                        filepath = self.save_transcript(transcript, ticker, year, quarter)
                        saved_files.append(filepath)
                    else:
                        errors += 1

        print(f"\nFetching complete.")
        print(f"  Saved: {len(saved_files)} new transcripts")
        print(f"  Errors: {errors}")
        return saved_files


def main():
    """Entry point for the fetcher."""
    # Get API key from environment
    api_key = os.environ.get("API_NINJAS_KEY")
    if not api_key:
        print("ERROR: API_NINJAS_KEY environment variable not set")
        print("Sign up for a free API key at: https://api-ninjas.com/register")
        exit(1)

    # Get configuration from environment
    latest_only = os.environ.get("LATEST_ONLY", "true").lower() == "true"

    # Optional: limit to specific tickers (comma-separated)
    tickers_env = os.environ.get("TICKERS")
    tickers = tickers_env.split(",") if tickers_env else None

    # Run the fetcher
    fetcher = TranscriptFetcher(api_key)
    saved_files = fetcher.run(tickers=tickers, latest_only=latest_only)

    # Output for GitHub Actions
    if saved_files:
        print(f"\n::notice::Fetched {len(saved_files)} new transcripts")
    else:
        print("\n::notice::No new transcripts found")


if __name__ == "__main__":
    main()
