# log-triage-helper

![ci](https://github.com/revisualize/log-triage-helper/actions/workflows/ci.yml/badge.svg)

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

## License

See [LICENSE](LICENSE). This code is published for viewing as a sample of the author's work. All rights reserved.
