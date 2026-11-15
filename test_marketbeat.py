#!/usr/bin/env python3
"""Unit tests for the MarketBeat fallback + canonical dedup / quality gates.

Run: python3 -m pytest test_marketbeat.py -q   (or: python3 test_marketbeat.py)
No network required — parser tests use injected HTML.
"""
import json
import tempfile
import unittest
from pathlib import Path

import marketbeat
import scrape_transcripts as st
from marketbeat import MarketBeatScraper


SAMPLE_HTML = """
<html><head><title> MU Q3 2026 Earnings Report on 6/24/2026 </title></head>
<body>
<div class="transcript-discussion">
  <div class="transcript-line-speaker">Operator 00:00:00</div>
  <div class="transcript-arrow">Operator 00:00:00 Welcome to Micron's fiscal third quarter 2026 call. After today's prepared remarks, we will host a question-and-answer session. {body}</div>
  <div class="transcript-line-speaker">Sanjay Mehrotra 00:05:00</div>
  <div class="transcript-arrow">Sanjay Mehrotra 00:05:00 We delivered record revenue this quarter. {body}</div>
  <div class="transcript-line-speaker">Operator 00:30:00</div>
  <div class="transcript-arrow">Operator 00:30:00 We will now begin the question and answer session. Our first question comes from an analyst. {body}</div>
  <div class="transcript-arrow">Analyst 00:31:00 My question is on margins. {body}</div>
  <div class="transcript-arrow">Operator 00:58:00 This concludes today's call. You may now disconnect.</div>
</div>
</body></html>
""".replace("{body}", "word " * 400)  # pad each turn so the doc clears the word floor


class TestTitleParse(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(MarketBeatScraper._parse_title(
            "MU Q3 2026 Earnings Report on 6/24/2026"), ("MU", 3, 2026))
        self.assertEqual(MarketBeatScraper._parse_title(
            "BRK-B Q4 2025 Earnings Report"), ("BRK-B", 4, 2025))

    def test_invalid(self):
        self.assertIsNone(MarketBeatScraper._parse_title("Some random headline"))
        self.assertIsNone(MarketBeatScraper._parse_title(""))
        self.assertIsNone(MarketBeatScraper._parse_title("MU Q5 2026"))  # bad quarter


class TestSectionSplit(unittest.TestCase):
    def test_split_on_real_boundary(self):
        turns = ["intro prepared remark", "more prepared remarks",
                 "We will now begin the question and answer session. Our first question comes from an analyst.",
                 "analyst question about margins"]
        prep, qa = MarketBeatScraper._split_sections(turns)
        self.assertIn("prepared", prep)
        self.assertIn("analyst question", qa)
        self.assertNotIn("analyst question", prep)

    def test_opening_agenda_mention_does_not_split(self):
        # The opening turn often previews the agenda ("...we will host a
        # question-and-answer session"); that must NOT flip the section.
        turns = ["Operator: welcome. After prepared remarks we will host a "
                 "question-and-answer session.",
                 "CEO prepared remarks about revenue"]
        prep, qa = MarketBeatScraper._split_sections(turns)
        self.assertEqual(qa, "")
        self.assertIn("revenue", prep)


class TestParserInjected(unittest.TestCase):
    def test_scrape_report_from_injected_html(self):
        mb = MarketBeatScraper()
        url = "https://www.marketbeat.com/earnings/reports/2026-6-24-micron-technology-inc-stock/"
        mb._last_url = url           # injection point: reuse instead of fetching
        mb._last_html = SAMPLE_HTML
        t = mb.scrape_report(url)
        self.assertIsNotNone(t)
        self.assertEqual(t["ticker"], "MU")
        self.assertEqual((t["year"], t["quarter"]), (2026, 3))
        self.assertEqual(t["source"], "marketbeat")
        self.assertGreater(t["word_count"], 800)
        # Split correctness: prepared remarks present, Q&A separated, and the
        # opening agenda mention did NOT dump everything into qa_section.
        self.assertIn("record revenue", t["prepared_remarks"])
        self.assertNotIn("margins", t["prepared_remarks"])
        self.assertIn("margins", t["qa_section"])
        self.assertTrue(t["transcript"].strip().endswith("disconnect."))


class TestQualityGate(unittest.TestCase):
    def setUp(self):
        self.s = st.MotleyFoolScraper()

    def test_floor_rejects_stub(self):
        ok, reason = self.s.passes_quality(
            {"transcript": "short.", "word_count": 5})
        self.assertFalse(ok)
        self.assertIn("word floor", reason)

    def test_truncation_rejected(self):
        body = "word " * 1000 + "and then suddenly cut off mid"
        ok, reason = self.s.passes_quality({"transcript": body, "word_count": 1004})
        self.assertFalse(ok)
        self.assertIn("truncated", reason)

    def test_clean_call_accepted(self):
        body = "word " * 1000 + "This concludes today's call. You may now disconnect."
        ok, _ = self.s.passes_quality({"transcript": body, "word_count": 1010})
        self.assertTrue(ok)


class TestLabelAndDedup(unittest.TestCase):
    def test_valid_label(self):
        self.assertTrue(st.MotleyFoolScraper._valid_label(2026, 3))
        self.assertFalse(st.MotleyFoolScraper._valid_label(None, None))
        self.assertFalse(st.MotleyFoolScraper._valid_label(2026, 5))
        self.assertFalse(st.MotleyFoolScraper._valid_label(2026, 0))

    def test_canonical_dedup_and_accept(self):
        with tempfile.TemporaryDirectory() as d:
            tdir = Path(d)
            orig = st.TRANSCRIPTS_DIR
            st.TRANSCRIPTS_DIR = tdir
            marketbeat_dir = tdir
            try:
                s = st.MotleyFoolScraper()
                good = {"ticker": "MU", "company": "Micron", "title": "t",
                        "year": 2026, "quarter": 3, "url": "u1",
                        "transcript": "word " * 1000 + "thank you. disconnect.",
                        "prepared_remarks": "", "qa_section": "",
                        "source": "marketbeat",
                        "word_count": 1003}
                # First write accepted
                p1 = s.accept_and_save(dict(good))
                self.assertIsNotNone(p1)
                self.assertTrue(s.quarter_exists("MU", 2026, 3))
                # Second source, same quarter, different url -> suppressed
                dup = dict(good, url="u2", source="motley-fool")
                p2 = s.accept_and_save(dup)
                self.assertIsNone(p2)
                # Only one file on disk for the quarter
                self.assertEqual(len(list(tdir.glob("MU_2026_Q3_*.json"))), 1)
                # None label rejected
                bad = dict(good, year=None, quarter=None, url="u3")
                self.assertIsNone(s.accept_and_save(bad))
            finally:
                st.TRANSCRIPTS_DIR = orig


LISTING_HTML = """
<html><body><table>
<tr><th>Company</th><th>Date</th><th>Earnings Period</th><th>Details</th></tr>
<tr>
  <td><a href="/stocks/NASDAQ/MU/earnings/">MU Micron Technology</a></td>
  <td>06/24/26 4:30 PM ET</td><td>Q3 2026</td>
  <td><a href="/earnings/reports/2026-6-24-micron-technology-inc-stock/#transcript">View</a></td>
</tr>
<tr>
  <td><a href="/stocks/NYSE/FDX/earnings/">FDX FedEx</a></td>
  <td>06/23/26 4:00 PM ET</td><td>Q4 2026</td>
  <td><a href="/earnings/reports/2026-6-23-fedex-corp-stock/#transcript">View</a></td>
</tr>
</table></body></html>
"""


class TestListingParse(unittest.TestCase):
    def test_fetch_listing_table(self):
        mb = MarketBeatScraper()
        mb.session = _FakeSession(LISTING_HTML)  # inject listing HTML, no network
        rows = mb.fetch_listing()
        by = {r["ticker"]: r for r in rows}
        self.assertIn("MU", by)
        self.assertEqual((by["MU"]["year"], by["MU"]["quarter"]), (2026, 3))
        self.assertTrue(by["MU"]["url"].endswith(
            "/earnings/reports/2026-6-24-micron-technology-inc-stock/"))
        self.assertEqual((by["FDX"]["year"], by["FDX"]["quarter"]), (2026, 4))

    def test_discover_filters_to_covered(self):
        mb = MarketBeatScraper()
        mb.session = _FakeSession(LISTING_HTML)
        rows = mb.discover(["MU"])
        self.assertEqual({r["ticker"] for r in rows}, {"MU"})


class TestSlugQuarter(unittest.TestCase):
    def test_extracts_quarter_year(self):
        self.assertEqual(
            st.MotleyFoolScraper._quarter_from_slug(
                "intel-intc-q3-2026-earnings-call-transcript"), (2026, 3))
        self.assertEqual(
            st.MotleyFoolScraper._quarter_from_slug(
                "walmart-wmt-q4-2026-earnings-call-transcript"), (2026, 4))

    def test_absent_quarter_returns_none(self):
        self.assertEqual(
            st.MotleyFoolScraper._quarter_from_slug(
                "booking-holdings-bkng-earnings-transcript"), (None, None))


class TestRunFoolNoStarvation(unittest.TestCase):
    """A cluster of newer permanently-rejected URLs must not starve an older,
    still-missing covered quarter sitting past `limit` in the newest-first list
    (board #288 — the INTC Q3 2026 regression)."""

    CLEAN = "word " * 1000 + "This concludes today's call. You may now disconnect."
    TRUNC = "word " * 1000 + "but then it was abruptly cut off mid"

    def _item(self, ticker, date, q, y):
        slug = f"{ticker.lower()}-{ticker.lower()}-q{q}-{y}-earnings-call-transcript"
        return {"url": f"https://www.fool.com/earnings/call-transcripts/"
                       f"{y}/{date[5:7]}/{date[8:10]}/{slug}/",
                "ticker": ticker, "date": date}

    def _transcript(self, item, body):
        y, q = st.MotleyFoolScraper._quarter_from_slug(item["url"])
        return {"ticker": item["ticker"], "company": item["ticker"], "title": "t",
                "year": y, "quarter": q, "url": item["url"], "transcript": body,
                "prepared_remarks": "", "qa_section": "", "source": "motley-fool",
                "word_count": len(body.split())}

    def test_older_missing_quarter_saved_despite_newer_rejects(self):
        with tempfile.TemporaryDirectory() as d:
            orig = st.TRANSCRIPTS_DIR
            st.TRANSCRIPTS_DIR = Path(d)
            try:
                s = st.MotleyFoolScraper()
                # 8 newer URLs that always fail the quality gate (truncated),
                # then the older target that scrapes clean.
                rejects = [self._item("AAA", f"2026-11-{str(10-i).zfill(2)}", 3, 2026)
                           for i in range(8)]
                target = self._item("INTC", "2026-10-30", 3, 2026)
                items = rejects + [target]

                s.get_transcripts_from_sitemap = lambda tickers=None: list(items)
                bodies = {it["url"]: self.TRUNC for it in rejects}
                bodies[target["url"]] = self.CLEAN
                s.scrape_transcript = lambda url: self._transcript(
                    next(it for it in items if it["url"] == url), bodies[url])

                # limit=2 (well below the 8 rejects). Old code would burn the
                # budget on the first 2 rejects and never reach INTC.
                saved = s._run_fool(limit=2, tickers=["INTC", "AAA"])

                self.assertEqual(len(list(Path(d).glob("INTC_2026_Q3_*.json"))), 1,
                                 "older missing INTC quarter must be saved")
                self.assertEqual(saved, [str(p) for p in Path(d).glob("INTC_2026_Q3_*.json")])
                self.assertEqual(list(Path(d).glob("AAA_*.json")), [],
                                 "truncated rejects must not be saved")
            finally:
                st.TRANSCRIPTS_DIR = orig

    def test_prefetch_skips_already_captured_quarter(self):
        with tempfile.TemporaryDirectory() as d:
            orig = st.TRANSCRIPTS_DIR
            st.TRANSCRIPTS_DIR = Path(d)
            try:
                s = st.MotleyFoolScraper()
                # Seed MSFT 2026 Q1 on disk under a DIFFERENT url, so the run
                # item is a fresh url (transcript_exists=False) but the quarter
                # is already captured -> must be skipped by the pre-fetch check,
                # not by the url-hash skip.
                seed = self._item("MSFT", "2026-10-29", 1, 2026)
                seed_t = self._transcript(seed, self.CLEAN)
                seed_t["url"] = "https://www.fool.com/other-source-msft-q1-2026/"
                s.save_transcript(seed_t)
                run_item = self._item("MSFT", "2026-10-30", 1, 2026)  # fresh url
                fetched = []
                s.get_transcripts_from_sitemap = lambda tickers=None: [run_item]
                def _spy(url):
                    fetched.append(url)
                    return self._transcript(run_item, self.CLEAN)
                s.scrape_transcript = _spy
                s._run_fool(limit=5, tickers=["MSFT"])
                self.assertEqual(fetched, [],
                                 "already-captured quarter must be skipped pre-fetch")
            finally:
                st.TRANSCRIPTS_DIR = orig


class _FakeResp:
    def __init__(self, text): self.text = text
    def raise_for_status(self): pass


class _FakeSession:
    def __init__(self, text): self._text = text
    def get(self, *a, **k): return _FakeResp(self._text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
