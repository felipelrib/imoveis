"""Put retrospective action-item keys back after a sprint-status regeneration.

This project tracks retrospective action items as
``epic-N-retro-item-M-<slug>`` keys inside ``development_status`` because that is
the only shape bmad-loop parses (see bmad-retrospective.toml). The upstream
generator (bmad-sprint-planning ``sprint_plan.py generate``) rebuilds
``development_status`` from epics.md alone, so it drops those keys as orphans on
every refresh. This script re-inserts them, with their status and the comment
block above them, right after ``epic-N-retrospective``.

The previous content comes from ``--before`` or, by default, from the committed
version of the status file (``git show HEAD:<path>``). A key whose epic has no
``epic-N-retrospective`` line in the regenerated file is reported as
``unplaced`` and not written: the plan no longer has that epic, so where the
item goes is a judgment call.

Stdlib only; prints one JSON object; idempotent.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ITEM_RE = re.compile(r"^(\s+)(epic-(\d+)-retro-item-\d+-[^:\s]+):\s*(\S.*?)\s*$")
COMMENT_RE = re.compile(r"^\s+#")
BLOCK_START_RE = re.compile(r"^development_status:\s*$")


def _block_bounds(lines):
    """Return (start, end) line indexes of the development_status body, or None."""
    for i, line in enumerate(lines):
        if BLOCK_START_RE.match(line):
            end = len(lines)
            for j in range(i + 1, len(lines)):
                if lines[j].strip() and not lines[j][0].isspace():
                    end = j
                    break
            return i + 1, end
    return None


def extract_items(text):
    """Return [(key, epic_num, block_lines)] for every retro-item key, in file order."""
    lines = text.splitlines()
    bounds = _block_bounds(lines)
    if bounds is None:
        return []
    start, end = bounds
    items = []
    for i in range(start, end):
        m = ITEM_RE.match(lines[i])
        if not m:
            continue
        first = i
        while first - 1 >= start and COMMENT_RE.match(lines[first - 1]):
            first -= 1
        items.append((m.group(2), int(m.group(3)), lines[first : i + 1]))
    return items


def restore(before_text, current_text):
    """Return (new_text, report) with missing retro-item keys re-inserted."""
    report = {"restored": [], "already_present": [], "unplaced": []}
    newline = "\r\n" if "\r\n" in current_text else "\n"
    lines = current_text.splitlines()
    bounds = _block_bounds(lines)
    if bounds is None:
        report["error"] = "no development_status block in the status file"
        return current_text, report
    present = {key for key, _, _ in extract_items(current_text)}
    for key, epic_num, block in extract_items(before_text):
        if key in present:
            report["already_present"].append(key)
            continue
        start, end = _block_bounds(lines)
        anchor_re = re.compile(rf"^\s+epic-{epic_num}-retrospective:")
        anchor = next((i for i in range(start, end) if anchor_re.match(lines[i])), None)
        if anchor is None:
            report["unplaced"].append(key)
            continue
        # Keep file order: skip past items of this epic that are already there.
        insert_at = anchor + 1
        own_re = re.compile(rf"^\s+epic-{epic_num}-retro-item-\d+-")
        for i in range(anchor + 1, end):
            if own_re.match(lines[i]):
                insert_at = i + 1
            elif lines[i].strip() and not COMMENT_RE.match(lines[i]):
                break
        lines[insert_at:insert_at] = block
        present.add(key)
        report["restored"].append(key)
    if not report["restored"]:
        return current_text, report
    new_text = newline.join(lines)
    if current_text.endswith(("\n", "\r\n")):
        new_text += newline
    return new_text, report


def _committed_text(path):
    rel = subprocess.run(
        ["git", "ls-files", "--full-name", "--", str(path)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    ).stdout.strip()
    if not rel:
        return ""
    shown = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    return shown.stdout if shown.returncode == 0 else ""


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--before", help="previous status file; default: the committed version")
    args = parser.parse_args(argv)

    path = Path(args.status_file)
    current = path.read_bytes().decode("utf-8")
    before = Path(args.before).read_bytes().decode("utf-8") if args.before else _committed_text(path)
    new_text, report = restore(before, current)
    if new_text != current:
        path.write_bytes(new_text.encode("utf-8"))
    print(json.dumps({"ok": "error" not in report, "status_file": str(path), **report}))
    return 0 if "error" not in report else 1


if __name__ == "__main__":
    sys.exit(main())
