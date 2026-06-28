#!/usr/bin/env python3
"""
MarketBeat earnings-call-transcript fallback source.

A free, co-equal second source alongside The Motley Fool. Motley Fool sometimes
lags days behind a call (e.g. MU fiscal Q3 2026: reported 2026-06-24, still
unpublished on Fool 3+ days later while MarketBeat had it same-day). This module
discovers and scrapes transcripts from MarketBeat so whichever source produces a
valid transcript for a (ticker, year, quarter) FIRST wins; canonical dedup in
scrape_transcripts.py suppresses the slower source for that quarter.

Output schema is identical to the Motley Fool path (see scrape_transcripts.py
save_transcript/generate_filename), with source="marketbeat".

Key DOM facts (verified against live pages 2026-06):
- Report URL:   https://www.marketbeat.com/earnings/reports/{YYYY}-{M}-{D}-{slug}-stock/
                (month/day are NOT zero-padded)
- Listing page: https://www.marketbeat.com/earnings/transcripts/ indexes recent
                report URLs (<a href="/earnings/reports/...#transcript">).
- <title> is authoritative: "MU Q3 2026 Earnings Report on 6/24/2026"
                -> ticker, fiscal quarter, fiscal year (no heuristic needed).
- Transcript body: div.transcript-discussion > div.transcript-arrow bubbles,
                each already prefixed with "Speaker HH:MM:SS text".
"""
from __future__ import annotations

import re
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.marketbeat.com"
LISTING_URL = f"{BASE_URL}/earnings/transcripts/"
RATE_LIMIT_SECONDS = 2
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# "MU Q3 2026 Earnings Report ..." -> ticker, quarter, year (authoritative)
TITLE_RE = re.compile(r"^\s*([A-Z][A-Z.\-]{0,5})\s+Q([1-4])\s+(20\d{2})\b")
# Listing table: ticker from the /stocks/EXCH/TICKER/ link, period from "Q3 2026"
STOCK_TICKER_RE = re.compile(r"/stocks/[A-Z]+/([A-Z][A-Z.\-]{0,5})/")
PERIOD_RE = re.compile(r"\bQ([1-4])\s+(20\d{2})\b")
# Q&A section boundary markers (same spirit as the Fool path)
QA_MARKERS = ("q&a", "question-and-answer", "questions and answers",
              "question and answer")


class MarketBeatScraper:
    """Discover + scrape earnings transcripts from MarketBeat."""

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    # --- discovery -------------------------------------------------------

    def fetch_listing(self) -> list[dict]:
        """
        Parse the recent-transcripts listing TABLE. Each row authoritatively
        gives ticker, fiscal quarter/year, and the report URL — so we know the
        canonical (ticker, year, quarter) key BEFORE fetching any report page.

        Returns list of {"ticker","year","quarter","url","company"} (deduped).
        Network/parse errors return [] (caller treats as "nothing to fall back to").
        """
        try:
            time.sleep(1)
            resp = self.session.get(LISTING_URL, timeout=(5, 30))
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"  MarketBeat listing error: {type(e).__name__}")
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        out, seen = [], set()
        for tr in soup.find_all("tr"):
            a_report = tr.find("a", href=lambda h: h and "/earnings/reports/" in h)
            if not a_report:
                continue
            url = BASE_URL + a_report["href"].split("#")[0]
            if url in seen:
                continue

            cells = tr.find_all(["td", "th"])
            row_text = " ".join(c.get_text(" ", strip=True) for c in cells)

            # Ticker: prefer the /stocks/EXCH/TICKER/ link; fall back to first token
            ticker = None
            a_stock = tr.find("a", href=STOCK_TICKER_RE.search)
            if a_stock:
                m = STOCK_TICKER_RE.search(a_stock["href"])
                ticker = m.group(1).upper() if m else None
            if not ticker and cells:
                first = cells[0].get_text(" ", strip=True).split()
                if first and re.fullmatch(r"[A-Z][A-Z.\-]{0,5}", first[0]):
                    ticker = first[0]
            if not ticker:
                continue

            mp = PERIOD_RE.search(row_text)
            if not mp:
                continue
            quarter, year = int(mp.group(1)), int(mp.group(2))

            company = ""
            if cells:
                c0 = cells[0].get_text(" ", strip=True)
                company = c0[len(ticker):].strip() if c0.startswith(ticker) else c0

            seen.add(url)
            out.append({"ticker": ticker, "year": year, "quarter": quarter,
                        "url": url, "company": company})
        return out

    def discover(self, tickers: list[str] | None = None) -> list[dict]:
        """Listing rows filtered to covered tickers (or all if None)."""
        covered = {t.upper() for t in tickers} if tickers else None
        rows = self.fetch_listing()
        if covered is None:
            return rows
        return [r for r in rows if r["ticker"] in covered]

    # --- scraping --------------------------------------------------------

    @staticmethod
    def _parse_title(title: str) -> tuple[str, int, int] | None:
        """'MU Q3 2026 Earnings Report ...' -> ('MU', 3, 2026); None if no match."""
        m = TITLE_RE.match(title or "")
        if not m:
            return None
        return m.group(1).upper(), int(m.group(2)), int(m.group(3))

    @staticmethod
    def _split_sections(turns: list[str]) -> tuple[str, str]:
        """Split ordered speaker turns into (prepared_remarks, qa_section)."""
        prepared, qa, in_qa = [], [], False
        for t in turns:
            low = t.lower()
            if not in_qa and any(m in low for m in QA_MARKERS):
                in_qa = True
            (qa if in_qa else prepared).append(t)
        return "\n\n".join(prepared), "\n\n".join(qa)

    def scrape_report(self, url: str, company: str = "") -> dict | None:
        """
        Scrape one MarketBeat report page into the canonical transcript schema.
        Returns the dict, or None if the page can't be parsed into a usable
        transcript (caller still applies the shared quality gate).
        """
        # Reuse HTML if find_report_url just fetched this exact URL.
        html = None
        if getattr(self, "_last_url", None) == url and getattr(self, "_last_html", None):
            html = self._last_html
        if html is None:
            try:
                time.sleep(RATE_LIMIT_SECONDS)
                resp = self.session.get(url, timeout=(5, 30))
                resp.raise_for_status()
                html = resp.text
            except requests.RequestException as e:
                print(f"  MarketBeat fetch error for {url}: {type(e).__name__}")
                return None

        soup = BeautifulSoup(html, "lxml")
        title = soup.title.get_text(strip=True) if soup.title else ""
        parsed = self._parse_title(title)
        if not parsed:
            print(f"  MarketBeat: unparseable title for {url}: {title!r}")
            return None
        ticker, quarter, year = parsed

        disc = soup.find(class_="transcript-discussion")
        if not disc:
            print(f"  MarketBeat: no transcript body for {url}")
            return None

        turns = [b.get_text(" ", strip=True)
                 for b in disc.find_all(class_="transcript-arrow")]
        turns = [t for t in turns if t]
        full = "\n\n".join(turns)
        if len(full) < 500:
            print(f"  MarketBeat: transcript too short for {url}")
            return None

        prepared, qa = self._split_sections(turns)
        if not company:
            # derive a readable name from the slug: ".../micron-technology-inc-stock/"
            slug = url.rstrip("/").split("/")[-1]
            slug = re.sub(r"-stock$", "", slug)
            slug = re.sub(r"^\d{4}-\d{1,2}-\d{1,2}-", "", slug)
            company = slug.replace("-", " ").title()

        return {
            "ticker": ticker,
            "company": company,
            "title": title,
            "year": year,
            "quarter": quarter,
            "url": url,
            "transcript": full,
            "prepared_remarks": prepared,
            "qa_section": qa,
            "source": "marketbeat",
            "word_count": len(full.split()),
        }
