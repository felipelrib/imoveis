"""Retro-item keys survive a sprint-status regeneration (_bmad/custom/restore_retro_items.py)."""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "_bmad" / "custom" / "restore_retro_items.py"

_spec = importlib.util.spec_from_file_location("restore_retro_items", SCRIPT)
restore_retro_items = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(restore_retro_items)

BEFORE = """\
# header
generated: 10-07-2026 18:35
development_status:
  epic-1: in-progress
  1-1-first-story: done
  epic-1-retrospective: done
  # A1 - re-check the blocker
  # before the loop advances
  epic-1-retro-item-1-escalation-reverification: open
  epic-1-retro-item-2-ledger-budget: done

  epic-2: backlog
  2-1-other-story: backlog
  epic-2-retrospective: optional

followups: {}
"""

# What the generator writes: same plan, retro items gone.
REGENERATED = """\
# header
generated: 10-07-2026 18:35
development_status:
  epic-1: in-progress
  1-1-first-story: done
  epic-1-retrospective: done

  epic-2: backlog
  2-1-other-story: backlog
  epic-2-retrospective: optional

followups: {}
"""


def test_dropped_items_return_after_their_retrospective_with_comments():
    new_text, report = restore_retro_items.restore(BEFORE, REGENERATED)

    assert new_text == BEFORE
    assert report["restored"] == [
        "epic-1-retro-item-1-escalation-reverification",
        "epic-1-retro-item-2-ledger-budget",
    ]
    assert report["unplaced"] == []


def test_second_run_changes_nothing():
    once, _ = restore_retro_items.restore(BEFORE, REGENERATED)
    twice, report = restore_retro_items.restore(BEFORE, once)

    assert twice == once
    assert report["restored"] == []
    assert len(report["already_present"]) == 2


def test_item_of_an_epic_missing_from_the_new_plan_is_reported_not_written():
    without_epic_1 = """\
development_status:
  epic-2: backlog
  2-1-other-story: backlog
  epic-2-retrospective: optional
"""
    new_text, report = restore_retro_items.restore(BEFORE, without_epic_1)

    assert new_text == without_epic_1
    assert report["restored"] == []
    assert report["unplaced"] == [
        "epic-1-retro-item-1-escalation-reverification",
        "epic-1-retro-item-2-ledger-budget",
    ]


def test_crlf_file_keeps_its_line_endings():
    new_text, _ = restore_retro_items.restore(BEFORE, REGENERATED.replace("\n", "\r\n"))

    assert new_text == BEFORE.replace("\n", "\r\n")


def test_cli_reads_the_previous_file_and_rewrites_in_place(tmp_path, capsys):
    before = tmp_path / "before.yaml"
    status = tmp_path / "sprint-status.yaml"
    before.write_text(BEFORE, encoding="utf-8", newline="")
    status.write_text(REGENERATED, encoding="utf-8", newline="")

    rc = restore_retro_items.main(["--status-file", str(status), "--before", str(before)])

    assert rc == 0
    assert status.read_bytes().decode("utf-8") == BEFORE
    assert '"restored"' in capsys.readouterr().out
