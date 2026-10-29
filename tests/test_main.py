"""Run with: python -m unittest discover -s tests -v"""
import argparse
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class TestCPDExtractor(unittest.TestCase):
    def test_urls_follow_frontend_code(self):
        root = "https://bigdata_api.cpd.go.th/apitest/"
        self.assertEqual(main.build_url(root, "cooperatives", 2568, "2"), root + "api/CoopProfile/GetCoopOracleCountNEW")
        self.assertEqual(main.build_url(root, "members", 2568, "1"), root + "api/Member/GetCoopSumMemberNew?year=2568&sector=1")
        self.assertIn("sector=%E0%B8%AA", main.build_url(root, "officers", 2568, "1"))
        self.assertTrue(main.build_url(root, "officers", 2568, "0").endswith("?year=2568&sector=null"))

    def test_summary_from_api_rows(self):
        data = {
            "cooperatives": [{"coopCount": 7563, "active": 6316, "nonActive": 1247}],
            "members": [{"dataM": 2, "dataFm": 3, "sum": 5}],
            "committees": [{"dataM": "10", "dataFm": "20", "sum": "30"}],
            "officers": [{"dataM": 11154, "dataFm": 21040, "sum": 32194}],
        }
        result = main.build_summary(data, 2568, "0", "2026-10-29T15:00:00+07:00", main.API_BASE)
        self.assertEqual(result["officer_total"], 32194)
        self.assertEqual(result["officer_female"], 21040)
        self.assertEqual(result["coop_total"], 7563)
        self.assertEqual(result["coop_year_sector_filtered"], "no")
        self.assertEqual(result["member_total"], 5)

    def test_invalid_counts_never_become_zero(self):
        for value in (None, "", "unknown", 2.5, -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                main.parse_count(value, "test")

    def test_details(self):
        headers, rows = main.detail_rows("provinces", [{"provinceName": "เชียงใหม่", "sum": 3, "active": 2, "nonActive": 1}], 2568, "0", "now")
        self.assertEqual(rows[0]["coop_total"], 3)
        self.assertEqual(rows[0]["year_sector_filter_applied"], "no")
        self.assertIn("province_name", headers)
        headers, rows = main.detail_rows("strength", [{"type": "1", "level": "2", "count": 12}], 2568, "1", "now")
        self.assertEqual(rows[0]["coop_type_name"], "สหกรณ์การเกษตร")

    @patch("main.post_json")
    def test_single_command_writes_csv_and_raw(self, fake_post):
        mock_responses = {
            "GetCoopOracleCountNEW": [{"coopCount": 3, "active": 2, "nonActive": 1}],
            "GetCoopSumMemberNew": [{"sum": 5, "dataM": 2, "dataFm": 3}],
            "GetCoopSumCommitteeNew": [{"sum": 4, "dataM": 1, "dataFm": 3}],
            "GetCoopSumOfficer": [{"sum": 2, "dataM": 1, "dataFm": 1}],
            "GetCoopOracleTypesNEW": [{"coopType": "1", "active": 2, "nonActive": 1}],
            "GetCoopTypeLevelCount": [{"type": "1", "level": "1", "count": 2}],
            "GetOracleSumProvinceYearSearch": [{"provinceName": "กรุงเทพมหานคร", "sum": 3, "active": 2, "nonActive": 1}],
        }
        fake_post.side_effect = lambda url, body, timeout, retries: next(v for k, v in mock_responses.items() if k in url)
        with tempfile.TemporaryDirectory() as folder:
            args = argparse.Namespace(year=2568, sector="0", out=folder, base_url=main.API_BASE, timeout=3, retries=0, delay=0, summary_only=False, dry_run=False)
            self.assertEqual(main.run(args), 0)
            with (Path(folder) / "cpd_summary.csv").open(encoding="utf-8-sig", newline="") as f:
                self.assertEqual(next(csv.DictReader(f))["officer_total"], "2")
            self.assertTrue((Path(folder) / "cpd_province.csv").exists())
            self.assertTrue((Path(folder) / "cpd_type.csv").exists())
            self.assertTrue((Path(folder) / "cpd_strength.csv").exists())
            self.assertEqual(len(list((Path(folder) / "raw").glob("*/officers.json"))), 1)

    @patch("main.post_json", side_effect=RuntimeError("offline"))
    def test_failure_is_nonzero_and_logged(self, fake_post):
        with tempfile.TemporaryDirectory() as folder:
            args = argparse.Namespace(year=2568, sector="0", out=folder, base_url=main.API_BASE, timeout=3, retries=0, delay=0, summary_only=True, dry_run=False)
            self.assertEqual(main.run(args), 1)
            self.assertTrue((Path(folder) / "cpd_request_log.csv").exists())
            self.assertFalse((Path(folder) / "cpd_summary.csv").exists())


if __name__ == "__main__":
    unittest.main()
