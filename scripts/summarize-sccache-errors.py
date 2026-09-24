#!/usr/bin/env python3
"""Show bounded, redacted sccache diagnostic messages from a benchmark job."""

import collections
import pathlib
import re
import sys


def redact(line: str) -> str:
    line = re.sub(r"https?://\S+", "[url]", line)
    line = re.sub(r"/home/runner/\S+", "[path]", line)
    line = re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "[id]", line)
    line = re.sub(
        r"(?i)\b(authorization|bearer|token|secret|password)\s*[:=]?\s*\S+",
        r"\1 [redacted]",
        line,
    )
    return line[:300]


def main() -> None:
    path = pathlib.Path(sys.argv[1])
    if not path.exists():
        print("sccache did not write a diagnostic log")
        return

    messages = collections.Counter()
    with path.open(errors="replace") as log:
        for line in log:
            if re.search(r"\b(?:error|warn|fail)\b", line, re.IGNORECASE):
                messages[redact(line.strip())] += 1
    print(f"sccache diagnostic log: {path.stat().st_size} bytes")
    print(f"matching messages: {sum(messages.values())}")
    for message, count in messages.most_common(30):
        print(f"{count} × {message}")


if __name__ == "__main__":
    main()
