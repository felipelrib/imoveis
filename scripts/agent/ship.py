#!/usr/bin/env python3
"""Ship the current branch: validate (tier from the diff) -> squash-merge into main -> push.

    python scripts/agent/ship.py [--tier auto|docs|fast|frontend|backend|full] [--no-merge] [--skip-docs]

What it does, in order:

1. Refuses a dirty tree, a ``bmad-loop/*`` branch (the orchestrator merges those), or ``main`` itself
   when there is nothing to push.
2. Brings the branch up to date with ``origin/main`` (merge; a conflict exits 2 for you to resolve).
3. Feature-doc check: a story-key branch (``v0.14-s1.2-…`` / ``v0.14-fu3-…``) whose diff touches code
   must ship ``docs/features/<key>-*.md`` (``--skip-docs`` to override).
4. Runs ``validate.py`` (auto tier) on the branch; a red gate stops here (exit 1).
5. Squash-merges into ``main`` (one commit, linear history), re-checks the validation stamp for the
   resulting tree, and pushes ``origin main``. The feature branch is deleted after the push.

No Docker teardown, no image pruning, no worktree logic: ``scripts/ops/`` has those as operator tasks.
Alembic migrations in the diff print the reminder to run ``migrate-primary.sh`` when the backfill is idle.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _stream in (sys.stdout, sys.stderr):  # Windows consoles/redirects default to cp1252
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
REPO_ROOT = HERE.parent.parent
PYTHON = sys.executable
STORY_KEY_RE = re.compile(r"^v\d+[.-]\d+-(?:s\d+[.-]\d+|fu\d+)")
CODE_PATH_RE = re.compile(r"^(src|frontend|alembic|configs)/")


def git(*args: str, check: bool = True, capture: bool = True) -> str:
    res = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=capture, text=True, encoding="utf-8")
    if check and res.returncode != 0:
        raise SystemExit(f"[FAIL] git {' '.join(args)}: {(res.stderr or res.stdout).strip()}")
    return (res.stdout or "").strip()


def log(msg: str) -> None:
    print(f"> {msg}", flush=True)


def story_key(branch: str) -> str | None:
    desc = branch.split("/", 1)[-1]
    m = STORY_KEY_RE.match(desc)
    if not m:
        return None
    key = m.group(0)
    key = re.sub(r"^v(\d+)[.-](\d+)", r"v\1.\2", key)
    return re.sub(r"-s(\d+)[.-](\d+)$", r"-s\1.\2", key)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tier", default="auto")
    ap.add_argument("--no-merge", action="store_true", help="validate only; do not merge or push")
    ap.add_argument("--skip-docs", action="store_true", help="skip the feature-doc check")
    args = ap.parse_args(argv)

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch.startswith("bmad-loop/"):
        raise SystemExit("[FAIL] bmad-loop branches are merged by the orchestrator after its review pass — commit, validate, end the session.")
    if git("status", "--porcelain", check=False):
        raise SystemExit("[FAIL] working tree is dirty — commit (or stash) first.")

    git("fetch", "origin", "main", "--quiet", check=False)
    on_main = branch == "main"
    if not on_main:
        log(f"merging origin/main into {branch}")
        res = subprocess.run(["git", "merge", "--no-edit", "origin/main"], cwd=REPO_ROOT)
        if res.returncode != 0:
            subprocess.run(["git", "merge", "--abort"], cwd=REPO_ROOT)
            print("[FAIL] merge conflict with origin/main — resolve on the branch, commit, re-run (exit 2)")
            return 2

    changed = set(git("diff", "--name-only", "origin/main...HEAD", check=False).splitlines())
    if on_main:
        changed = set(git("diff", "--name-only", "origin/main..HEAD", check=False).splitlines())
        if not changed and not git("rev-list", "origin/main..HEAD", check=False):
            print("[OK] main is already pushed — nothing to ship")
            return 0

    key = story_key(branch)
    if key and not args.skip_docs and any(CODE_PATH_RE.match(p) for p in changed):
        if not list((REPO_ROOT / "docs" / "features").glob(f"{key}-*.md")):
            raise SystemExit(f"[FAIL] no feature doc for {key} (docs/features/{key}-*.md). Write it, commit, re-run — or --skip-docs.")

    log(f"validating ({args.tier} tier)")
    res = subprocess.run([PYTHON, str(HERE / "validate.py"), "--tier", args.tier], cwd=REPO_ROOT)
    if res.returncode != 0:
        return 1
    if args.no_merge:
        print("[OK] validated; stopping before merge (--no-merge)")
        return 0

    if not on_main:
        title = git("log", "-1", "--pretty=%s", branch)
        body = git("log", "origin/main..HEAD", "--pretty=- %s", "--no-merges", check=False)
        alembic = any(p.startswith("alembic/versions/") for p in changed)
        git("checkout", "main")
        git("pull", "--ff-only", "origin", "main")
        res = subprocess.run(["git", "merge", "--squash", branch], cwd=REPO_ROOT)
        if res.returncode != 0:
            subprocess.run(["git", "merge", "--abort"], cwd=REPO_ROOT, capture_output=True)
            git("checkout", branch)
            print("[FAIL] squash-merge conflict — merge main into the branch, resolve, re-run (exit 2)")
            return 2
        if not git("diff", "--cached", "--name-only", check=False):
            print("[WARN] nothing to merge — branch adds no changes on top of main")
            git("checkout", branch)
            return 0
        msg = title if not body else f"{title}\n\n{body}"
        subprocess.run(["git", "commit", "-q", "-m", msg], cwd=REPO_ROOT, check=True)
        print(f"[OK] squash-merged into main: {title}")
    else:
        alembic = any(p.startswith("alembic/versions/") for p in changed)

    check = subprocess.run([PYTHON, str(HERE / "validate.py"), "--check-stamp"], cwd=REPO_ROOT)
    if check.returncode != 0:
        print("[FAIL] the merged tree carries no validation stamp (main moved under the branch?) — re-run ship")
        return 1
    log("pushing main to origin")
    subprocess.run(["git", "push", "origin", "main"], cwd=REPO_ROOT, check=True)
    print("[OK] origin/main updated")
    if not on_main:
        subprocess.run(["git", "branch", "-D", branch], cwd=REPO_ROOT, capture_output=True)
        subprocess.run(["git", "push", "origin", "--delete", branch], cwd=REPO_ROOT, capture_output=True)
    if alembic:
        print("[WARN] this merge includes Alembic migrations — run `bash scripts/agent/migrate-primary.sh` when the backfill is idle.")
    print("[OK] shipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
