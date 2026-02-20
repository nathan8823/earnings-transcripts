#!/usr/bin/env python3
"""
Earnings Call Transcript Scraper

Scrapes earnings call transcripts from The Motley Fool and stores them as JSON files.
Designed to run via GitHub Actions on a schedule.

Uses the Motley Fool sitemap to discover transcript URLs (more reliable than
the listing page which only shows today's transcripts).

Source: https://www.fool.com/earnings-call-transcripts/
"""
from __future__ import annotations

import json
import os
import re
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# Configuration
TRANSCRIPTS_DIR = Path("transcripts")
RATE_LIMIT_SECONDS = 2  # Be respectful to the server
BASE_URL = "https://www.fool.com"
SITEMAP_URL = f"{BASE_URL}/sitemap"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Regex to extract ticker from URL slug like "walmart-wmt-q4-2026-earnings-call-transcript"
# Matches patterns like: company-TICKER-q1-2026 or company-TICKER-earnings
SLUG_TICKER_RE = re.compile(r'-([a-z]{1,5})-(?:q\d|earnings)', re.IGNORECASE)


class MotleyFoolScraper:
    """Scraper for earnings call transcripts from The Motley Fool."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
        TRANSCRIPTS_DIR.mkdir(exist_ok=True)

    def get_transcripts_from_sitemap(self, tickers: list[str] | None = None) -> list[dict]:
        """
        Fetch transcript URLs from the Motley Fool sitemap.

        Checks the current month's sitemap plus the previous month's sitemap
        to catch transcripts published near month boundaries.

        Args:
            tickers: Optional list of tickers to filter

        Returns:
            List of dicts with 'url', 'ticker', 'date' keys
        """
        tickers_upper = set(t.upper() for t in tickers) if tickers else None
        transcripts = []
        seen_urls = set()

        now = datetime.now()
        # Check current month and previous month
        months_to_check = [now]
        if now.day <= 7:
            # Early in the month, also check previous month more thoroughly
            prev = now.replace(day=1) - timedelta(days=1)
            months_to_check.append(prev)
        else:
            prev = now.replace(day=1) - timedelta(days=1)
            months_to_check.append(prev)

        for month_date in months_to_check:
            sitemap_url = f"{SITEMAP_URL}/{month_date.year}/{month_date.month:02d}"
            print(f"Fetching sitemap: {sitemap_url}")

            try:
                time.sleep(1)
                response = self.session.get(sitemap_url)
                response.raise_for_status()

                # Sitemap is XML with <url><loc>...</loc></url> format
                soup = BeautifulSoup(response.text, 'lxml-xml')

                # Find all <loc> tags containing transcript URLs
                for loc in soup.find_all('loc'):
                    href = loc.get_text(strip=True)
                    if '/earnings/call-transcripts/' not in href:
                        continue
                    if href in seen_urls:
                        continue
                    seen_urls.add(href)

                    full_url = href  # Already absolute URLs in sitemap

                    # Extract ticker from URL slug
                    slug = href.rstrip('/').split('/')[-1]
                    ticker = self._extract_ticker_from_slug(slug)

                    # Filter by ticker list if provided
                    if tickers_upper and ticker not in tickers_upper:
                        continue

                    # Extract date from URL
                    date_match = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', href)
                    date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}" if date_match else ""

                    transcripts.append({
                        "url": full_url,
                        "ticker": ticker,
                        "date": date,
                        "title": slug.replace('-', ' ').title(),
                    })

                print(f"  Found {len([t for t in transcripts if t['date'].startswith(f'{month_date.year}-{month_date.month:02d}')])} transcript URLs for {month_date.strftime('%Y-%m')}")

            except requests.RequestException as e:
                print(f"  Error fetching sitemap {sitemap_url}: {e}")

        print(f"Total transcript URLs found: {len(transcripts)}")
        return transcripts

    def _extract_ticker_from_slug(self, slug: str) -> str:
        """
        Extract ticker symbol from a URL slug.

        Examples:
            walmart-wmt-q4-2026-earnings-call-transcript -> WMT
            analog-devices-adi-q1-2026-earnings-transcript -> ADI
            booking-holdings-bkng-earnings-transcript -> BKNG
            berkshire-hathaway-brk-b-q4-2025-earnings -> BRK-B
        """
        # Special case: BRK-B has a hyphen in the ticker
        if 'brk-b-' in slug:
            return "BRK-B"
        match = SLUG_TICKER_RE.search(slug)
        if match:
            return match.group(1).upper()
        return "UNKNOWN"

    def scrape_transcript(self, url: str) -> dict | None:
        """
        Scrape a single transcript from the given URL.

        Args:
            url: URL of the transcript page

        Returns:
            Dict with transcript data or None if scraping fails
        """
        try:
            time.sleep(RATE_LIMIT_SECONDS)

            print(f"  Fetching: {url}")
            response = self.session.get(url)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'lxml')

            # Extract title
            title_elem = soup.find('h1')
            title = title_elem.get_text(strip=True) if title_elem else ""

            # Extract ticker from title
            ticker_match = re.search(r'\(([A-Z]{1,5})\)', title)
            ticker = ticker_match.group(1) if ticker_match else "UNKNOWN"

            # Extract company name (before the ticker)
            company_match = re.search(r'^(.+?)\s*\([A-Z]{1,5}\)', title)
            company = company_match.group(1).strip() if company_match else ""

            # Extract quarter info
            quarter_match = re.search(r'Q(\d)\s+(\d{4})', title)
            quarter = int(quarter_match.group(1)) if quarter_match else None
            year = int(quarter_match.group(2)) if quarter_match else None

            # Find the main content area
            content_area = soup.find('main')
            if not content_area:
                content_area = soup.find('article')
            if not content_area:
                content_area = soup.find('div', class_='tailwind-article-body')

            if not content_area:
                print(f"  Warning: Could not find content area for {url}")
                return None

            # Extract all paragraphs
            paragraphs = content_area.find_all(['p', 'h2', 'h3'])

            # Build transcript text
            transcript_parts = []
            current_section = "intro"
            prepared_remarks = []
            qa_section = []

            for p in paragraphs:
                text = p.get_text(strip=True)
                if not text:
                    continue

                # Detect section transitions
                text_lower = text.lower()
                if 'q&a' in text_lower or 'question-and-answer' in text_lower or 'questions and answers' in text_lower:
                    current_section = "qa"
                elif 'prepared remarks' in text_lower or 'opening remarks' in text_lower:
                    current_section = "prepared"

                transcript_parts.append(text)

                if current_section == "qa":
                    qa_section.append(text)
                else:
                    prepared_remarks.append(text)

            full_transcript = "\n\n".join(transcript_parts)

            if not full_transcript or len(full_transcript) < 500:
                print(f"  Warning: Transcript too short for {url}")
                return None

            return {
                "ticker": ticker,
                "company": company,
                "title": title,
                "year": year,
                "quarter": quarter,
                "url": url,
                "transcript": full_transcript,
                "prepared_remarks": "\n\n".join(prepared_remarks),
                "qa_section": "\n\n".join(qa_section),
                "source": "motley-fool",
                "word_count": len(full_transcript.split())
            }

        except requests.RequestException as e:
            print(f"  Error fetching {url}: {e}")
            return None
        except Exception as e:
            print(f"  Error parsing {url}: {e}")
            return None

    def generate_filename(self, transcript: dict) -> str:
        """Generate a unique filename for the transcript."""
        ticker = transcript.get("ticker", "UNKNOWN")
        year = transcript.get("year", datetime.now().year)
        quarter = transcript.get("quarter", 0)
        # Add URL hash for uniqueness
        url_hash = hashlib.md5(transcript.get("url", "").encode()).hexdigest()[:6]
        return f"{ticker}_{year}_Q{quarter}_{url_hash}.json"

    def transcript_exists(self, url: str) -> bool:
        """Check if transcript has already been scraped (by URL hash)."""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:6]
        for filepath in TRANSCRIPTS_DIR.glob("*.json"):
            if url_hash in filepath.name:
                return True
        return False

    def save_transcript(self, transcript: dict) -> str:
        """Save transcript to JSON file."""
        filename = self.generate_filename(transcript)
        filepath = TRANSCRIPTS_DIR / filename

        transcript["scraped_at"] = datetime.now().isoformat()
        transcript["filename"] = filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(transcript, f, indent=2, ensure_ascii=False)

        print(f"  Saved: {filepath}")
        return str(filepath)

    def run(self, limit: int = 10, tickers: list[str] = None) -> list[str]:
        """
        Main scraping loop.

        Args:
            limit: Maximum number of transcripts to scrape
            tickers: Optional list of tickers to filter (e.g., ['AAPL', 'MSFT'])

        Returns:
            List of saved file paths
        """
        print(f"Starting Motley Fool scraper at {datetime.now().isoformat()}")
        saved_files = []

        # Get transcript URLs from sitemap (filtered by tickers if provided)
        transcript_list = self.get_transcripts_from_sitemap(tickers=tickers)

        # Sort by date descending (newest first)
        transcript_list.sort(key=lambda t: t.get("date", ""), reverse=True)

        if tickers:
            print(f"Found {len(transcript_list)} transcripts matching {len(tickers)} target tickers")

        scraped = 0
        for i, item in enumerate(transcript_list):
            if scraped >= limit:
                break

            url = item.get("url")
            if not url:
                continue

            # Skip if already scraped
            if self.transcript_exists(url):
                continue

            print(f"\n[{scraped+1}/{limit}] {item.get('ticker', '???')} - {item.get('date', '???')}")

            # Scrape and save
            transcript = self.scrape_transcript(url)
            if transcript:
                filepath = self.save_transcript(transcript)
                saved_files.append(filepath)
            scraped += 1

        print(f"\nScraping complete. Saved {len(saved_files)} new transcripts.")
        return saved_files


def main():
    """Entry point for the scraper."""
    # Get configuration from environment
    limit = int(os.environ.get("TRANSCRIPT_LIMIT", 10))

    # Optional: filter to specific tickers (comma-separated)
    tickers_env = os.environ.get("TICKERS")
    tickers = [t.strip() for t in tickers_env.split(",")] if tickers_env else None

    # Run the scraper
    scraper = MotleyFoolScraper()
    saved_files = scraper.run(limit=limit, tickers=tickers)

    # Output for GitHub Actions
    if saved_files:
        print(f"\n::notice::Scraped {len(saved_files)} new transcripts")
    else:
        print("\n::notice::No new transcripts found")


if __name__ == "__main__":
    main()
