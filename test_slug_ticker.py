#!/usr/bin/env python3
"""Unit tests for MotleyFoolScraper._extract_ticker_from_slug.

Run: python3 -m pytest test_slug_ticker.py -q   (or: python3 test_slug_ticker.py)
No network required — __init__ only sets up a session and mkdir's the output dir.

Regression guard for the GOOGL->GOOG alias: Alphabet's Motley Fool transcript
slug is "alphabet-googl-q3-2026-..." (GOOGL), but the TICKERS allowlist and the
earnings-podcasts pipeline key Alphabet as GOOG. Before the alias, GOOGL was
filtered out at the allowlist step and no Alphabet episode ever generated.
"""
import unittest

from scrape_transcripts import MotleyFoolScraper, SLUG_TICKER_ALIASES


class SlugTickerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = MotleyFoolScraper()

    def test_alphabet_googl_aliases_to_goog(self):
        self.assertEqual(
            self.s._extract_ticker_from_slug(
                "alphabet-googl-q3-2026-earnings-call-transcript"
            ),
            "GOOG",
        )

    def test_plain_ticker(self):
        self.assertEqual(
            self.s._extract_ticker_from_slug(
                "walmart-wmt-q4-2026-earnings-call-transcript"
            ),
            "WMT",
        )

    def test_brk_b_special_case_preserved(self):
        self.assertEqual(
            self.s._extract_ticker_from_slug(
                "berkshire-hathaway-brk-b-q4-2025-earnings"
            ),
            "BRK-B",
        )

    def test_pnc_extracts_cleanly(self):
        # PNC (added to the allowlist) must extract from its own slug.
        self.assertEqual(
            self.s._extract_ticker_from_slug(
                "pnc-financial-services-pnc-q1-2027-earnings-call-transcript"
            ),
            "PNC",
        )

    def test_non_aliased_ticker_unchanged(self):
        # A ticker not in the alias map passes through untouched.
        self.assertEqual(
            self.s._extract_ticker_from_slug(
                "apple-aapl-q4-2026-earnings-call-transcript"
            ),
            "AAPL",
        )

    def test_alias_map_has_googl(self):
        self.assertEqual(SLUG_TICKER_ALIASES.get("GOOGL"), "GOOG")


if __name__ == "__main__":
    unittest.main(verbosity=2)
