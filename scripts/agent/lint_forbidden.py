#!/usr/bin/env python3
"""Forbidden-pattern lint behind the local pre-commit hooks.

    python scripts/agent/lint_forbidden.py <check> [--root DIR]

Replaces the ``bash -c '! grep -rnP …'`` hook entries. Those depended on which
``bash`` came first on PATH (the WSL launcher on Windows) and on the locale:
Git for Windows' grep refuses ``-P`` outside a UTF-8 locale, exits 2, and the
``!`` / pipeline shape turned that error into a pass with nothing checked.
Stdlib only, so it runs under any Python 3 without the project venv.

Exit 0 = clean, 1 = matches (printed as ``path:line:text``), 2 = could not run.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

FSTRING_SQL_PATTERN = r"(\btext\(\s*f['\"]|\bf['\"][^'\"]*\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM|ORDER BY)\b)"


@dataclass(frozen=True)
class Check:
    roots: tuple[str, ...]
    pattern: str
    suffixes: tuple[str, ...] | None = None  # None = every file
    # A match is dropped when its ``path:line:text`` output contains any of these
    # (the semantics of the ``| grep -v`` filters the hooks used to carry).
    drop_if_contains: tuple[str, ...] = ()


CHECKS = {
    "secrets": Check(
        roots=("src", "frontend/src"),
        pattern=r"(imoveis_secret|dev-secret-key)",
        suffixes=(".py", ".js", ".jsx", ".ts", ".tsx"),
    ),
    "only": Check(roots=("src/tests",), pattern=r"\.only\("),
    "print": Check(
        roots=("src",),
        pattern=r"^[^#]*\bprint\s*\(",
        suffixes=(".py",),
        drop_if_contains=("__init__.py", "test_"),
    ),
    "fstring-sql": Check(
        roots=("src",),
        pattern=FSTRING_SQL_PATTERN,
        suffixes=(".py",),
        drop_if_contains=("/tests/",),
    ),
}


def find_matches(check: Check, root: Path) -> list[str]:
    """Return ``path:line:text`` for every match; raise FileNotFoundError on a missing root."""
    regex = re.compile(check.pattern)
    matches: list[str] = []
    for rel_root in check.roots:
        base = root / rel_root
        if not base.is_dir():
            raise FileNotFoundError(f"search root not found: {rel_root}")
        for path in sorted(base.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if check.suffixes is not None and path.suffix not in check.suffixes:
                continue
            rel = path.relative_to(root).as_posix()
            text = path.read_bytes().decode("utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                if not regex.search(line):
                    continue
                hit = f"{rel}:{lineno}:{line}"
                if not any(marker in hit for marker in check.drop_if_contains):
                    matches.append(hit)
    return matches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Forbidden-pattern lint (pre-commit local hooks).")
    parser.add_argument("check", choices=sorted(CHECKS))
    parser.add_argument("--root", default=".", help="repository root to scan (default: cwd)")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        matches = find_matches(CHECKS[args.check], Path(args.root))
    except OSError as exc:
        sys.stderr.write(f"lint_forbidden {args.check}: {exc}\n")
        return 2
    if matches:
        sys.stdout.write("\n".join(matches) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
