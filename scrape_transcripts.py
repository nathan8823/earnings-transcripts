#!/usr/bin/env python3
"""
Earnings Call Transcript Scraper

Scrapes earnings call transcripts from The Motley Fool and stores them as JSON files.
Designed to run via GitHub Actions on a schedule.

Source: https://www.fool.com/earnings-call-transcripts/
"""
from __future__ import annotations

import json
import os
import re
import time
import hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# Configuration
TRANSCRIPTS_DIR = Path("transcripts")
RATE_LIMIT_SECONDS = 2  # Be respectful to the server
BASE_URL = "https://www.fool.com"
TRANSCRIPTS_URL = f"{BASE_URL}/earnings-call-transcripts/"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


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

    def get_recent_transcripts(self, limit: int = 10) -> list[dict]:
        """
        Fetch list of recent transcript URLs from the main page.

        Args:
            limit: Maximum number of transcripts to fetch

        Returns:
            List of dicts with 'url', 'title', 'ticker', 'date' keys
        """
        transcripts = []

        try:
            print(f"Fetching transcript list from {TRANSCRIPTS_URL}")
            response = self.session.get(TRANSCRIPTS_URL)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'lxml')

            # Find transcript links - they're in article cards
            # The structure is typically: <a href="/earnings/call-transcripts/...">
            all_links = soup.find_all('a', href=True)
            links = [l for l in all_links if '/earnings/call-transcript' in l.get('href', '')]

            # Group links by URL and prefer ones with titles
            url_to_link = {}
            for link in links:
                href = link.get('href', '')
                if not href:
                    continue
                title = link.get_text(strip=True)
                # Prefer links with titles
                if href not in url_to_link or (title and not url_to_link[href].get_text(strip=True)):
                    url_to_link[href] = link

            for href, link in url_to_link.items():
                if len(transcripts) >= limit:
                    break

                full_url = urljoin(BASE_URL, href)
                title = link.get_text(strip=True)

                # If no title, extract from URL
                if not title:
                    # URL like: unifirst-unf-q1-2026-earnings-call-transcript
                    slug = href.rstrip('/').split('/')[-1]
                    title = slug.replace('-', ' ').title()

                # Try to extract ticker from title like "Apple (AAPL) Q4 2024..."
                ticker_match = re.search(r'\(([A-Z]{1,5})\)', title)
                ticker = ticker_match.group(1) if ticker_match else "UNKNOWN"

                # Extract date from URL like /2024/10/31/
                date_match = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', href)
                if date_match:
                    date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
                else:
                    date = datetime.now().strftime("%Y-%m-%d")

                transcripts.append({
                    "url": full_url,
                    "title": title,
                    "ticker": ticker,
                    "date": date
                })

            print(f"Found {len(transcripts)} transcript URLs")
            return transcripts

        except requests.RequestException as e:
            print(f"Error fetching transcript list: {e}")
            return []

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
            # Motley Fool uses <main> element containing the transcript
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

        # Get list of recent transcripts
        transcript_list = self.get_recent_transcripts(limit=limit * 2)  # Get extra in case we filter

        if tickers:
            tickers_upper = [t.upper() for t in tickers]
            transcript_list = [t for t in transcript_list if t.get("ticker") in tickers_upper]
            print(f"Filtered to {len(transcript_list)} transcripts for tickers: {tickers_upper}")

        for i, item in enumerate(transcript_list[:limit]):
            url = item.get("url")
            if not url:
                continue

            print(f"\n[{i+1}/{min(len(transcript_list), limit)}] {item.get('title', url)[:60]}...")

            # Skip if already scraped
            if self.transcript_exists(url):
                print(f"  Skipping (already exists)")
                continue

            # Scrape and save
            transcript = self.scrape_transcript(url)
            if transcript:
                filepath = self.save_transcript(transcript)
                saved_files.append(filepath)

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
