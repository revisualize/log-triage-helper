# log-triage-helper

[![ci](https://github.com/revisualize/log-triage-helper/actions/workflows/ci.yml/badge.svg)](https://github.com/revisualize/log-triage-helper/actions/workflows/ci.yml)
[![test](https://github.com/revisualize/log-triage-helper/actions/workflows/test.yml/badge.svg)](https://github.com/revisualize/log-triage-helper/actions/workflows/test.yml)
[![shellcheck](https://github.com/revisualize/log-triage-helper/actions/workflows/shellcheck.yml/badge.svg)](https://github.com/revisualize/log-triage-helper/actions/workflows/shellcheck.yml)
[![python-compat](https://github.com/revisualize/log-triage-helper/actions/workflows/python-compat.yml/badge.svg)](https://github.com/revisualize/log-triage-helper/actions/workflows/python-compat.yml)
[![python-lint](https://github.com/revisualize/log-triage-helper/actions/workflows/python-lint.yml/badge.svg)](https://github.com/revisualize/log-triage-helper/actions/workflows/python-lint.yml)
[![codeql](https://github.com/revisualize/log-triage-helper/actions/workflows/codeql.yml/badge.svg)](https://github.com/revisualize/log-triage-helper/actions/workflows/codeql.yml)
[![markdown-lint](https://github.com/revisualize/log-triage-helper/actions/workflows/markdown-lint.yml/badge.svg)](https://github.com/revisualize/log-triage-helper/actions/workflows/markdown-lint.yml)
[![links](https://github.com/revisualize/log-triage-helper/actions/workflows/links.yml/badge.svg)](https://github.com/revisualize/log-triage-helper/actions/workflows/links.yml)
[![content-policy](https://github.com/revisualize/log-triage-helper/actions/workflows/content-policy.yml/badge.svg)](https://github.com/revisualize/log-triage-helper/actions/workflows/content-policy.yml)
[![license: all rights reserved](https://img.shields.io/badge/license-all%20rights%20reserved-lightgrey)](LICENSE)

The mechanical first hour of incident log review, automated. It takes log files from several systems, normalizes their timestamps to UTC, applies known per-source clock drift, brackets a window around an anchor time, and emits one merged, time-sorted stream so a human can start reading instead of collating.

It makes no judgments about what matters. The judgment is the human job. The collating never should have been.

## Usage

```sh
log_triage_helper.py --anchor "2026-05-11T02:45:00" \
    --minutes-before 60 --minutes-after 10 \
    --shift node3.log=-90 \
    application.log node3.log network.log
```

`--shift NAME=SECONDS` corrects a source whose clock is known to be wrong, or whose timestamps are local time written without a zone. The applied shift is printed in the output header, so the correction is part of the record rather than a silent adjustment someone has to rediscover later.

## What it parses

Formats are attempted in a fixed order and the first match wins:

1. ISO 8601, with or without fractional seconds, with or without a zone. A naive timestamp is treated as UTC.
2. Classic RFC 3164 syslog, which carries no year. The year is resolved to whichever candidate lands nearest the anchor, so December logs read in January land in the right place.
3. Anything else is a continuation line and travels with the entry above it.

Guessing beyond a known list produces confident wrong parses, which in a timeline tool is worse than refusing.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Output produced |
| 2 | Argument or file error |

## Design notes

**Sub-second precision is preserved.** Two events in the same second must not be reordered by the tool that exists to order events correctly. Fractional seconds, comma or period separated, are carried into the sort key.

**Lines before the first timestamp are reported, not silently dropped.** They have no entry to attach to, so they cannot be placed on the timeline, but the count appears in the output header. An evidence tool that discards input without saying so is not evidence.

**A `--shift` naming a file that was not supplied is refused.** It is almost always a typo, and a silently ignored drift correction produces a confidently wrong timeline.

**Read-only, stdout, no state.** The tool never modifies its inputs and writes nothing anywhere. A triage tool that could conceivably alter evidence has disqualified itself.

## Known limitations

- Only the three timestamp families above are recognized. A fourth format present in a source becomes continuation lines attached to whatever preceded it.
- Measuring clock drift is out of scope. The number you pass to `--shift` comes from your time infrastructure.
- `--shift` is keyed by file basename, so two files with the same name in different directories share one shift value.

## Requirements

Python 3.9 or newer. Standard library only, no third-party packages.

## Tests

```sh
python3 -m unittest discover -s test -v
```

## Continuous integration

Each badge above is its own GitHub Actions workflow in `.github/workflows/`. Every workflow runs on each push and pull request, can be re-run by hand from the Actions tab, and links to its run history.

| Workflow | A green badge means |
|---|---|
| [`ci`](https://github.com/revisualize/log-triage-helper/actions/workflows/ci.yml) | `bash test/run_all_tests.sh` passed on Python 3.9 and 3.12 and reported a non-zero count of executed tests, and shellcheck found nothing at style severity. |
| [`test`](https://github.com/revisualize/log-triage-helper/actions/workflows/test.yml) | `bash test/run_all_tests.sh` passed on Python 3.9 and 3.12. The run fails if any suite fails or if zero tests executed, and the job summary lists each suite with its test count. |
| [`shellcheck`](https://github.com/revisualize/log-triage-helper/actions/workflows/shellcheck.yml) | Every shell script outside `test/fixtures/` parses with `bash -n` and has no shellcheck findings at style severity. |
| [`python-compat`](https://github.com/revisualize/log-triage-helper/actions/workflows/python-compat.yml) | The test suite passed under every Python release from 3.9 through 3.14. |
| [`python-lint`](https://github.com/revisualize/log-triage-helper/actions/workflows/python-lint.yml) | ruff found no defects (unused imports, undefined names, and similar) in any Python module. |
| [`codeql`](https://github.com/revisualize/log-triage-helper/actions/workflows/codeql.yml) | GitHub CodeQL security analysis of the Python code reported no results. |
| [`markdown-lint`](https://github.com/revisualize/log-triage-helper/actions/workflows/markdown-lint.yml) | Every Markdown file passes markdownlint. |
| [`links`](https://github.com/revisualize/log-triage-helper/actions/workflows/links.yml) | Every link in every Markdown file resolved on the latest run. It also runs weekly, because a link can break with no commit here. |
| [`content-policy`](https://github.com/revisualize/log-triage-helper/actions/workflows/content-policy.yml) | Every tracked file meets the publishing rules: UTF-8, LF line endings, no em dashes, scripts documented as `bash name.sh`, and vendor-neutral wording. |

A badge reports the latest run of those checks. What the tool needs on your own host is listed under Requirements.

## License

See [LICENSE](LICENSE). This code is published for viewing as a sample of the author's work. All rights reserved.
