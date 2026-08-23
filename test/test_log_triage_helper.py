#!/usr/bin/env python3
#
# ---------------------------------------------------------------------
# Path:         test/test_log_triage_helper.py
# Filename:     test_log_triage_helper.py
# Project:      log_triage_helper
# Description:  Unit tests for the parsing, ordering, and windowing
#               logic. Standard library unittest, no pytest dependency.
# Status:       production
# Revision:     1
# Updated:      2026-08-05
# Requires:     Python 3.9 or newer
# Included by:  .github/workflows/ci.yml
# Provides:     test coverage for log_triage_helper
# ---------------------------------------------------------------------
#
# Run with:  python3 -m unittest discover -s test -v
#
"""Tests for log_triage_helper."""

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import log_triage_helper as helper  # noqa: E402

ANCHOR = datetime(2026, 5, 11, 2, 45, 0, tzinfo=timezone.utc)


class TimestampParsingTests(unittest.TestCase):

    def test_iso_with_zulu_zone_parses_as_utc(self):
        parsed = helper.parse_line_timestamp(
            "2026-05-11T02:44:59Z app: hello", ANCHOR)
        self.assertEqual(parsed, datetime(2026, 5, 11, 2, 44, 59,
                                          tzinfo=timezone.utc))

    def test_fractional_seconds_are_preserved(self):
        """Regression: fractions were captured then discarded, which
        silently reordered events sharing a whole second."""
        parsed = helper.parse_line_timestamp(
            "2026-05-11T02:44:59.100Z app: hello", ANCHOR)
        self.assertEqual(parsed.microsecond, 100000)

    def test_comma_is_accepted_as_a_fraction_separator(self):
        parsed = helper.parse_line_timestamp(
            "2026-05-11 02:44:59,250+0000 app: hello", ANCHOR)
        self.assertEqual(parsed.microsecond, 250000)

    def test_numeric_offset_without_colon_parses(self):
        parsed = helper.parse_line_timestamp(
            "2026-05-11T04:44:59+0200 app: hello", ANCHOR)
        self.assertEqual(parsed, datetime(2026, 5, 11, 2, 44, 59,
                                          tzinfo=timezone.utc))

    def test_naive_iso_is_treated_as_utc(self):
        parsed = helper.parse_line_timestamp(
            "2026-05-11T02:44:59 app: hello", ANCHOR)
        self.assertEqual(parsed.tzinfo, timezone.utc)

    def test_syslog_year_resolves_to_the_nearest_anchor_year(self):
        january_anchor = datetime(2026, 1, 3, 0, 0, 0, tzinfo=timezone.utc)
        parsed = helper.parse_line_timestamp(
            "Dec 31 23:59:01 node kernel: oops", january_anchor)
        self.assertEqual(parsed.year, 2025)

    def test_unparsable_line_returns_none(self):
        self.assertIsNone(
            helper.parse_line_timestamp("  File 'x.py', line 3", ANCHOR))


class ShiftArgumentTests(unittest.TestCase):

    def test_valid_shift_parses_to_integer_seconds(self):
        self.assertEqual(helper.parse_shift_arguments(["node3.log=-90"]),
                         {"node3.log": -90})

    def test_shift_without_equals_is_rejected(self):
        with self.assertRaises(ValueError):
            helper.parse_shift_arguments(["node3.log-90"])

    def test_shift_with_empty_filename_is_rejected(self):
        with self.assertRaises(ValueError):
            helper.parse_shift_arguments(["=-90"])

    def test_shift_with_non_numeric_seconds_is_rejected(self):
        with self.assertRaises(ValueError):
            helper.parse_shift_arguments(["node3.log=ninety"])


class MergeBehaviourTests(unittest.TestCase):

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.root = Path(self.work.name)

    def tearDown(self):
        self.work.cleanup()

    def write_log(self, name, text):
        path = self.root / name
        path.write_text(text)
        return path

    def merge(self, paths, shifts=None, warning_sink=None):
        return helper.build_merged_entries(
            paths, shifts or {}, ANCHOR,
            ANCHOR - timedelta(minutes=60), ANCHOR + timedelta(minutes=10),
            warning_sink)

    def test_entries_sharing_a_second_sort_by_fraction(self):
        path = self.write_log("app.log",
                              "2026-05-11T02:44:59.900Z later\n"
                              "2026-05-11T02:44:59.100Z earlier\n")
        entries = self.merge([path])
        self.assertIn("earlier", entries[0][3][0])
        self.assertIn("later", entries[1][3][0])

    def test_continuation_lines_travel_with_their_parent(self):
        path = self.write_log("app.log",
                              "2026-05-11T02:45:01Z traceback follows\n"
                              "  File 'handler.py', line 12\n"
                              "    raise TimeoutError\n")
        entries = self.merge([path])
        self.assertEqual(len(entries), 1)
        self.assertEqual(len(entries[0][3]), 3)

    def test_shift_moves_a_source_onto_the_true_timeline(self):
        path = self.write_log("node3.log",
                              "2026-05-11T02:44:59Z nfs server not responding\n")
        entries = self.merge([path], {"node3.log": -90})
        self.assertEqual(entries[0][0],
                         datetime(2026, 5, 11, 2, 43, 29, tzinfo=timezone.utc))

    def test_entries_outside_the_window_are_excluded(self):
        path = self.write_log("app.log",
                              "2026-05-11T01:00:00Z far too early\n"
                              "2026-05-11T02:44:59Z inside window\n")
        entries = self.merge([path])
        self.assertEqual(len(entries), 1)
        self.assertIn("inside window", entries[0][3][0])

    def test_orphan_leading_lines_are_reported_not_silently_dropped(self):
        path = self.write_log("header.log",
                              "### rotated log begins\n"
                              "2026-05-11T02:45:00Z daemon: failover\n")
        sink = []
        self.merge([path], warning_sink=sink)
        self.assertEqual(len(sink), 1)
        self.assertIn("header.log", sink[0])

    def test_sources_interleave_in_true_time_order(self):
        first = self.write_log("a.log", "2026-05-11T02:44:58Z alpha\n")
        second = self.write_log("b.log", "2026-05-11T02:44:57Z beta\n")
        entries = self.merge([first, second])
        self.assertIn("beta", entries[0][3][0])
        self.assertIn("alpha", entries[1][3][0])


class ExitCodeTests(unittest.TestCase):

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.root = Path(self.work.name)
        self.good = self.root / "app.log"
        self.good.write_text("2026-05-11T02:44:59Z app: hello\n")

    def tearDown(self):
        self.work.cleanup()

    def test_missing_file_exits_two(self):
        code = helper.main(["--anchor", "2026-05-11T02:45:00",
                            str(self.root / "absent.log")])
        self.assertEqual(code, 2)

    def test_bad_anchor_exits_two(self):
        code = helper.main(["--anchor", "not-a-timestamp", str(self.good)])
        self.assertEqual(code, 2)

    def test_shift_naming_an_unsupplied_file_exits_two(self):
        code = helper.main(["--anchor", "2026-05-11T02:45:00",
                            "--shift", "absent.log=-90", str(self.good)])
        self.assertEqual(code, 2)

    def test_negative_window_exits_two(self):
        code = helper.main(["--anchor", "2026-05-11T02:45:00",
                            "--minutes-before", "-5", str(self.good)])
        self.assertEqual(code, 2)

    def test_successful_run_exits_zero(self):
        code = helper.main(["--anchor", "2026-05-11T02:45:00",
                            str(self.good)])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
