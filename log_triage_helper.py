#!/usr/bin/env python3
#
# ---------------------------------------------------------------------
# Path:         log_triage_helper.py
# Filename:     log_triage_helper.py
# Project:      log_triage_helper
# Description:  Merge log files from multiple sources into one
#               UTC-normalized, time-sorted stream bracketed around an
#               anchor timestamp.
# Status:       production
# Revision:     2
# Updated:      2026-08-05
# Requires:     Python 3.9 or newer, standard library only
# Included by:  standalone command line tool
# Provides:     parse_line_timestamp, read_source_entries,
#               parse_shift_arguments, build_merged_entries, main
# ---------------------------------------------------------------------
#
# Portability
#   Tested on:  CPython 3.9 through 3.12 on Linux.
#   Standard library only. No third party packages, no network access,
#   no writes to disk. Reads named files and writes to stdout.
#
"""Merge log files from multiple sources into one UTC-normalized,
time-sorted stream bracketed around an anchor timestamp.

Usage:
    log_triage_helper.py --anchor "2026-05-11T02:45:00" \
        --minutes-before 60 --minutes-after 10 \
        --shift node3.log=-90 \
        application.log node3.log network.log

Exit codes: 0 output produced, 2 argument or file error.
"""

import argparse
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SYSLOG_PATTERN = re.compile(
    r"^(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"\s+(?P<day>\d{1,2})\s(?P<time>\d{2}:\d{2}:\d{2})"
)
ISO_PATTERN = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})"
    r"(?P<fraction>[.,]\d+)?(?P<zone>Z|[+-]\d{2}:?\d{2})?"
)
MONTH_NUMBERS = {name: number for number, name in enumerate(
    ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]) if number}


def parse_line_timestamp(line_text, anchor_time):
    """Return an aware UTC datetime for the line, or None (continuation).

    Sub-second precision is preserved when the source provides it. A
    timeline tool that discards fractional seconds silently reorders
    events that share a whole second, which is the exact error this
    tool exists to prevent.
    """
    iso_match = ISO_PATTERN.match(line_text)
    if iso_match:
        stamp_text = iso_match.group("stamp").replace(" ", "T")
        fraction_text = iso_match.group("fraction")
        zone_text = iso_match.group("zone")

        # Normalize the fractional part to exactly six digits so
        # fromisoformat accepts it on Python 3.9, which rejects any
        # other length. Comma separators are legal ISO 8601.
        if fraction_text:
            digits = fraction_text[1:][:6].ljust(6, "0")
            stamp_text = f"{stamp_text}.{digits}"

        if zone_text in (None, "", "Z"):
            parsed_time = datetime.fromisoformat(stamp_text)
            parsed_time = parsed_time.replace(tzinfo=timezone.utc)
        else:
            zone_normalized = zone_text if ":" in zone_text \
                else zone_text[:3] + ":" + zone_text[3:]
            parsed_time = datetime.fromisoformat(stamp_text + zone_normalized)
        return parsed_time.astimezone(timezone.utc)

    syslog_match = SYSLOG_PATTERN.match(line_text)
    if syslog_match:
        hour, minute, second = map(int, syslog_match.group("time").split(":"))
        candidate_times = []
        for year_candidate in (anchor_time.year - 1, anchor_time.year,
                               anchor_time.year + 1):
            try:
                candidate_times.append(datetime(
                    year_candidate,
                    MONTH_NUMBERS[syslog_match.group("month")],
                    int(syslog_match.group("day")),
                    hour, minute, second, tzinfo=timezone.utc))
            except ValueError:
                continue
        if not candidate_times:
            return None
        # The missing year resolves to whichever choice lands nearest
        # the anchor, which handles December logs read in January.
        return min(candidate_times,
                   key=lambda candidate: abs(candidate - anchor_time))
    return None


def read_source_entries(file_path, shift_seconds, anchor_time,
                        warning_sink=None):
    """Yield (utc_time, sequence, source_name, [lines]) entries.

    Lines appearing before the first parsable timestamp in a file have
    no entry to attach to. They are dropped, but never silently: the
    count is reported through warning_sink, because an evidence tool
    that discards input without saying so is not evidence.
    """
    source_name = file_path.name
    shift_delta = timedelta(seconds=shift_seconds)
    current_entry = None
    orphan_line_count = 0
    with file_path.open(errors="replace") as file_handle:
        for sequence_number, raw_line in enumerate(file_handle):
            line_text = raw_line.rstrip("\n")
            line_time = parse_line_timestamp(line_text, anchor_time)
            if line_time is None:
                if current_entry is not None:
                    current_entry[3].append(line_text)
                elif line_text.strip() != "":
                    orphan_line_count += 1
                continue
            if current_entry is not None:
                yield tuple(current_entry)
            current_entry = [line_time + shift_delta, sequence_number,
                             source_name, [line_text]]
    if current_entry is not None:
        yield tuple(current_entry)
    if orphan_line_count and warning_sink is not None:
        warning_sink.append(
            f"{source_name}: {orphan_line_count} line(s) before the first "
            f"parsable timestamp were not included")


def parse_shift_arguments(shift_arguments):
    shift_by_filename = {}
    for shift_argument in shift_arguments:
        if "=" not in shift_argument:
            raise ValueError(
                f"bad --shift (want name=seconds): {shift_argument}")
        file_name, _, seconds_text = shift_argument.partition("=")
        if file_name.strip() == "":
            raise ValueError(
                f"bad --shift (empty filename): {shift_argument}")
        shift_by_filename[file_name] = int(seconds_text)
    return shift_by_filename


def build_merged_entries(log_files, shift_by_filename, anchor_time,
                         window_start, window_end, warning_sink=None):
    """Collect, window-filter, and sort entries from every source."""
    all_entries = []
    for file_path in log_files:
        shift_seconds = shift_by_filename.get(file_path.name, 0)
        for entry in read_source_entries(file_path, shift_seconds,
                                         anchor_time, warning_sink):
            if window_start <= entry[0] <= window_end:
                all_entries.append(entry)
    all_entries.sort(key=lambda entry: (entry[0], entry[2], entry[1]))
    return all_entries


def format_entry_lines(entries):
    """Render sorted entries. Continuation lines print under their parent."""
    rendered = []
    for entry_time, _, source_name, entry_lines in entries:
        stamp = entry_time.isoformat()
        rendered.append(f"{stamp} [{source_name}] {entry_lines[0]}")
        indent = " " * len(stamp)
        for continuation_line in entry_lines[1:]:
            rendered.append(f"{indent} [{source_name}] .  {continuation_line}")
    return rendered


def main(argument_values=None):
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument(
        "--anchor", required=True,
        help="Anchor timestamp, ISO 8601, treated as UTC if no zone given")
    argument_parser.add_argument("--minutes-before", type=int, default=60)
    argument_parser.add_argument("--minutes-after", type=int, default=10)
    argument_parser.add_argument(
        "--shift", action="append", default=[], metavar="FILENAME=SECONDS",
        help="Seconds to add to a source's timestamps to correct to true UTC")
    argument_parser.add_argument("log_files", nargs="+", type=Path)
    arguments = argument_parser.parse_args(argument_values)

    try:
        anchor_time = datetime.fromisoformat(arguments.anchor)
        if anchor_time.tzinfo is None:
            anchor_time = anchor_time.replace(tzinfo=timezone.utc)
        anchor_time = anchor_time.astimezone(timezone.utc)
        shift_by_filename = parse_shift_arguments(arguments.shift)
    except ValueError as argument_error:
        print(f"argument error: {argument_error}", file=sys.stderr)
        return 2

    if arguments.minutes_before < 0 or arguments.minutes_after < 0:
        print("argument error: window minutes must not be negative",
              file=sys.stderr)
        return 2

    for file_path in arguments.log_files:
        if not file_path.is_file():
            print(f"file error: {file_path} is not a readable file",
                  file=sys.stderr)
            return 2

    # A --shift naming a file that was not supplied is almost always a
    # typo, and a silently ignored drift correction produces a confidently
    # wrong timeline. Refuse instead.
    supplied_names = {file_path.name for file_path in arguments.log_files}
    for shift_name in shift_by_filename:
        if shift_name not in supplied_names:
            print(f"argument error: --shift names {shift_name}, which is not "
                  f"among the supplied log files", file=sys.stderr)
            return 2

    window_start = anchor_time - timedelta(minutes=arguments.minutes_before)
    window_end = anchor_time + timedelta(minutes=arguments.minutes_after)

    warning_sink = []
    all_entries = build_merged_entries(
        arguments.log_files, shift_by_filename, anchor_time,
        window_start, window_end, warning_sink)

    print(f"# window {window_start.isoformat()} .. {window_end.isoformat()}"
          f"  anchor {anchor_time.isoformat()}")
    for file_path in arguments.log_files:
        applied_shift = shift_by_filename.get(file_path.name, 0)
        print(f"# source {file_path.name} shift {applied_shift:+d}s")
    for warning_text in warning_sink:
        print(f"# warning {warning_text}")
    for rendered_line in format_entry_lines(all_entries):
        print(rendered_line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
