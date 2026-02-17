#!/usr/bin/env python3
"""
S&P 500 Earnings Calendar Updater

Fetches upcoming earnings dates for S&P 500 companies via yfinance
and generates a JSON calendar + human-readable Markdown file.

Sources:
- S&P 500 list: Wikipedia
- Earnings dates: Yahoo Finance via yfinance
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
import yfinance as yf
from bs4 import BeautifulSoup

CALENDAR_DIR = Path("calendar")
SP500_FILE = CALENDAR_DIR / "sp500_tickers.json"
CALENDAR_JSON = CALENDAR_DIR / "earnings_calendar.json"
CALENDAR_MD = CALENDAR_DIR / "EARNINGS_CALENDAR.md"
RATE_LIMIT_SECONDS = 0.5
WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class EarningsCalendarUpdater:
    """Fetches and publishes an S&P 500 earnings calendar."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        CALENDAR_DIR.mkdir(exist_ok=True)

    # ---- S&P 500 list ----

    def fetch_sp500_list(self) -> list[dict]:
        """Scrape the S&P 500 constituent list from Wikipedia."""
        print(f"Fetching S&P 500 list from Wikipedia...")
        resp = self.session.get(WIKIPEDIA_URL)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", {"id": "constituents"})
        if not table:
            raise RuntimeError("Could not find S&P 500 table on Wikipedia")

        rows = table.find_all("tr")[1:]  # skip header
        companies = []
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            ticker = cols[0].get_text(strip=True).replace(".", "-")  # BRK.B → BRK-B
            company = cols[1].get_text(strip=True)
            sector = cols[2].get_text(strip=True) if len(cols) > 2 else ""
            companies.append({
                "ticker": ticker,
                "company": company,
                "sector": sector,
            })

        print(f"  Found {len(companies)} S&P 500 companies")

        with open(SP500_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"updated_at": datetime.utcnow().isoformat() + "Z", "companies": companies},
                f, indent=2, ensure_ascii=False,
            )
        print(f"  Saved {SP500_FILE}")
        return companies

    def load_sp500_list(self) -> list[dict]:
        """Load S&P 500 list from cache, or fetch if missing."""
        if SP500_FILE.exists():
            with open(SP500_FILE, encoding="utf-8") as f:
                data = json.load(f)
            print(f"Loaded {len(data['companies'])} tickers from {SP500_FILE}")
            return data["companies"]
        return self.fetch_sp500_list()

    # ---- Earnings dates ----

    def fetch_earnings_dates(self, companies: list[dict]) -> list[dict]:
        """Query yfinance for each ticker's next earnings date."""
        earnings = []
        total = len(companies)

        for i, co in enumerate(companies):
            ticker = co["ticker"]
            print(f"  [{i+1}/{total}] {ticker}...", end=" ", flush=True)

            try:
                tk = yf.Ticker(ticker)
                cal = tk.calendar
                if cal is None or (isinstance(cal, dict) and not cal):
                    print("no data")
                    time.sleep(RATE_LIMIT_SECONDS)
                    continue

                # yfinance .calendar returns a dict with keys like
                # 'Earnings Date', 'EPS Estimate', 'Revenue Estimate', etc.
                earnings_date = None
                eps_estimate = None
                revenue_estimate = None

                if isinstance(cal, dict):
                    # Earnings Date can be a list of dates or a single date
                    ed = cal.get("Earnings Date")
                    if isinstance(ed, list) and ed:
                        earnings_date = ed[0]
                    elif ed is not None:
                        earnings_date = ed
                    eps_estimate = cal.get("Earnings Average") or cal.get("EPS Estimate")
                    revenue_estimate = cal.get("Revenue Average") or cal.get("Revenue Estimate")

                if earnings_date is None:
                    print("no earnings date")
                    time.sleep(RATE_LIMIT_SECONDS)
                    continue

                # Normalize date to string
                if hasattr(earnings_date, "strftime"):
                    date_str = earnings_date.strftime("%Y-%m-%d")
                else:
                    date_str = str(earnings_date)[:10]

                # Determine BMO/AMC from earnings_dates if available
                report_time = "TBD"
                try:
                    edates = tk.earnings_dates
                    if edates is not None and not edates.empty:
                        # Find the row matching our date
                        for idx in edates.index:
                            idx_date = idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx)[:10]
                            if idx_date == date_str:
                                hour = idx.hour if hasattr(idx, "hour") else 12
                                report_time = "BMO" if hour < 12 else "AMC"
                                break
                except Exception:
                    pass

                entry = {
                    "ticker": ticker,
                    "company": co["company"],
                    "sector": co.get("sector", ""),
                    "date": date_str,
                    "time": report_time,
                }
                if eps_estimate is not None:
                    entry["eps_estimate"] = round(float(eps_estimate), 2)
                if revenue_estimate is not None:
                    entry["revenue_estimate"] = int(revenue_estimate)

                earnings.append(entry)
                print(f"{date_str} ({report_time})")

            except Exception as e:
                print(f"error: {e}")

            time.sleep(RATE_LIMIT_SECONDS)

        # Sort by date, then ticker
        earnings.sort(key=lambda x: (x["date"], x["ticker"]))
        return earnings

    # ---- JSON output ----

    def generate_json(self, earnings: list[dict]) -> None:
        """Write earnings_calendar.json with weekly buckets."""
        today = datetime.utcnow().date()
        week_start = today - timedelta(days=today.weekday())  # Monday
        week_end = week_start + timedelta(days=6)
        next_week_start = week_start + timedelta(days=7)
        next_week_end = next_week_start + timedelta(days=6)

        this_week = [e for e in earnings if week_start.isoformat() <= e["date"] <= week_end.isoformat()]
        next_week = [e for e in earnings if next_week_start.isoformat() <= e["date"] <= next_week_end.isoformat()]

        data = {
            "updated_at": datetime.utcnow().isoformat() + "Z",
            "source": "Yahoo Finance via yfinance",
            "total_companies": len(earnings),
            "earnings": earnings,
            "this_week": this_week,
            "next_week": next_week,
        }

        with open(CALENDAR_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"\nSaved {CALENDAR_JSON} ({len(earnings)} entries)")

    # ---- Markdown output ----

    def generate_markdown(self, earnings: list[dict]) -> None:
        """Write EARNINGS_CALENDAR.md with week-by-week tables."""
        today = datetime.utcnow().date()
        now_str = today.strftime("%b %d, %Y")

        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        next_week_start = week_start + timedelta(days=7)
        next_week_end = next_week_start + timedelta(days=6)

        this_week = [e for e in earnings if week_start.isoformat() <= e["date"] <= week_end.isoformat()]
        next_week = [e for e in earnings if next_week_start.isoformat() <= e["date"] <= next_week_end.isoformat()]
        later = [e for e in earnings if e["date"] > next_week_end.isoformat()]

        lines = [
            "# S&P 500 Earnings Calendar",
            f"> Last updated: {now_str} &middot; Source: Yahoo Finance &middot; Auto-updated daily",
            "",
        ]

        def _fmt_date_range(start, end):
            return f"{start.strftime('%b %d')}\\u2013{end.strftime('%b %d')}"

        def _write_table(entries, heading):
            lines.append(f"## {heading}")
            if not entries:
                lines.append("_No earnings scheduled._")
                lines.append("")
                return
            lines.append("| Date | Time | Ticker | Company | Est. EPS |")
            lines.append("|------|------|--------|---------|----------|")
            for e in entries:
                d = datetime.strptime(e["date"], "%Y-%m-%d").strftime("%b %d")
                eps = f"${e['eps_estimate']:.2f}" if "eps_estimate" in e else "—"
                lines.append(f"| {d} | {e['time']} | {e['ticker']} | {e['company']} | {eps} |")
            lines.append("")

        _write_table(this_week, f"This Week ({week_start.strftime('%b %d')}–{week_end.strftime('%b %d')})")
        _write_table(next_week, f"Next Week ({next_week_start.strftime('%b %d')}–{next_week_end.strftime('%b %d')})")
        _write_table(later, f"Later ({(next_week_end + timedelta(days=1)).strftime('%b %d')}+)")

        with open(CALENDAR_MD, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"Saved {CALENDAR_MD}")

    # ---- Orchestration ----

    def run(self, update_tickers: bool = False, limit: int | None = None, dry_run: bool = False) -> None:
        """Main entry point."""
        print(f"Starting earnings calendar update at {datetime.utcnow().isoformat()}Z")

        # Step 1: Get S&P 500 list
        if update_tickers or not SP500_FILE.exists():
            companies = self.fetch_sp500_list()
        else:
            companies = self.load_sp500_list()

        if limit:
            companies = companies[:limit]
            print(f"Limited to {limit} tickers")

        # Step 2: Fetch earnings dates
        print(f"\nFetching earnings dates for {len(companies)} companies...")
        earnings = self.fetch_earnings_dates(companies)
        print(f"\nFound earnings dates for {len(earnings)} companies")

        if dry_run:
            print("\n[DRY RUN] Skipping file writes")
            for e in earnings[:10]:
                print(f"  {e['date']} {e['time']:>3} {e['ticker']:<6} {e['company']}")
            if len(earnings) > 10:
                print(f"  ... and {len(earnings) - 10} more")
            return

        # Step 3: Generate outputs
        self.generate_json(earnings)
        self.generate_markdown(earnings)

        print("\nDone!")


def main():
    parser = argparse.ArgumentParser(description="Update S&P 500 earnings calendar")
    parser.add_argument("--update-tickers", action="store_true", help="Refresh S&P 500 list from Wikipedia")
    parser.add_argument("--limit", type=int, default=None, help="Process only N tickers (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write output files")
    args = parser.parse_args()

    updater = EarningsCalendarUpdater()
    updater.run(update_tickers=args.update_tickers, limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
