"""Pytest plugin: sticky progress bar + per-file rollup or per-test rows.

Replaces pytest's per-test dots / verbose labels with our own output:

  Default (`python -m pytest`)         — one row per file (PASSED/FAILED/SKIPPED)
  Verbose (`python -m pytest -v`)      — one row per test  (✓/✗/⊘ + reason)

Either way the sticky bar at the bottom advances per-test (so the
percentage is honest) — same visual style as run.py / run_benchmark.py /
generate.py.

To get pytest's plain output for one run, opt out:

    python -m pytest -p no:sticky_progress
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

import pytest

# StickyProgress lives at the repo root under pipeline/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.progress import StickyProgress  # noqa: E402


# ANSI colour codes — match StickyProgress's own ✓/✗ counter palette so
# the file-rollup rows agree visually with the bar at the bottom.
_RESET = "\033[0m"
_GREEN = "\033[1;32m"   # bold green   — PASSED
_RED = "\033[1;31m"     # bold red     — FAILED
_YELLOW = "\033[1;33m"  # bold yellow  — SKIPPED


def _colour_status(status: str, *, tty: bool) -> str:
    """Wrap the status word in an ANSI colour iff stdout is a TTY.
    Suppress colour when piped/redirected so log files stay clean."""
    if not tty:
        return status
    if status == "PASSED":
        return f"{_GREEN}PASSED{_RESET}"
    if status == "FAILED":
        return f"{_RED}FAILED{_RESET}"
    if status == "SKIPPED":
        return f"{_YELLOW}SKIPPED{_RESET}"
    return status


def _fmt_dur(seconds: float) -> str:
    if seconds < 60:
        # Sub-minute test runs are common — keep one decimal so 0.7s
        # doesn't render as "0s".
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


def _trim_paren_noise(reason: str, *, max_paren: int = 40) -> str:
    """Drop a long parenthetical tail while keeping short integral ones.

    "SUMO binaries (sumo / netconvert) not on PATH" → unchanged.
    "arm64 netconvert can't process chicago_1k_car (netconvert failed:
    Warning: Ambiguity in turnarounds...)" → trimmed to "arm64
    netconvert can't process chicago_1k_car".
    """
    if " (" not in reason:
        return reason
    main, _, paren_part = reason.partition(" (")
    if len(paren_part) > max_paren:
        return main
    return reason


def _truncate(text: str, limit: int = 110) -> str:
    """Hard-truncate with an ellipsis if longer than ``limit``."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


class StickyProgressPlugin:
    """Hooks into pytest's per-test reporting and drives a sticky bar +
    per-file aggregate rows (or per-test rows with --verbose)."""

    def __init__(self, verbose: bool = False) -> None:
        # Per-test rows when True, per-file rollup when False.
        self.verbose = verbose
        # Bar + counters
        self.progress: StickyProgress | None = None
        self.total = 0
        self.test_passed = 0
        self.test_failed = 0
        self.test_skipped = 0
        self.start_time = 0.0
        self._seen: set[str] = set()

        # Per-file aggregator
        self.current_file: str | None = None
        self.file_has_fail = False
        self.file_has_pass = False
        self.file_has_skip = False

        # File-name column width (computed from collected items)
        self.name_w = 30

        # TTY detection — colours only when we're on an interactive
        # terminal (matches StickyProgress's own gating).
        self.tty = sys.stdout.isatty()

        # Per-file roll-up of skip reasons + warning collection so we
        # can emit a single clean Summary block at the end.
        self.skip_reasons_by_file: dict[str, Counter] = {}
        self.failed_nodeids: list[tuple[str, str]] = []  # (nodeid, first-error-line)
        self.warning_messages: list[tuple[str, str]] = []  # (nodeid, message)

    # ---- lifecycle --------------------------------------------------------

    def pytest_collection_finish(self, session) -> None:
        self.total = len(session.items)
        self.start_time = time.time()
        if self.total == 0:
            return
        # Width fits the longest collected test file path.
        files = {item.nodeid.split("::", 1)[0] for item in session.items}
        if files:
            self.name_w = max(len(f) for f in files)

        # SimForge-style header — same look as run.py / run_benchmark.py.
        # `-q` in addopts hides pytest's own "collected N items" line, so we
        # re-emit a richer one here.
        print("\n" + "=" * 60)
        print("  SimForge Test Suite")
        print("=" * 60)
        verbose_tag = "  (verbose)" if self.verbose else ""
        print(f"\n  Collected:  {self.total} tests across {len(files)} files{verbose_tag}")
        print("\n" + "=" * 60)
        print("  Running Tests")
        print("=" * 60)

        self.progress = StickyProgress(self.total, unit="test")
        self.progress.start()

    def pytest_sessionfinish(self, session, exitstatus) -> None:
        if self.progress is None:
            return
        # Flush the last file's row before stopping the bar.
        self._flush_file()
        self.progress.stop()
        self.progress = None

    # ---- warning capture (replaces pytest's "warnings summary" block) ----

    def pytest_warning_recorded(self, warning_message, when, nodeid, location):
        msg = str(warning_message.message)
        # Drop the conftest path / lineno noise — we just want the warning text.
        self.warning_messages.append((nodeid or "<session>", msg))

    # ---- suppress pytest's per-test character / label output --------------

    def pytest_report_teststatus(self, report, config):
        """Return empty short/verbose strings so pytest doesn't print
        its `.`/`s`/`F` characters or per-test PASSED labels. The
        category (passed/failed/skipped/error) still flows so pytest's
        bookkeeping (final summary, FAILURES section) is untouched."""
        if report.when == "setup" and report.skipped:
            return ("skipped", "", "")
        if report.when == "setup" and report.failed:
            return ("error", "", "")
        if report.when == "call":
            if report.passed:
                return ("passed", "", "")
            if report.failed:
                return ("failed", "", "")
            if report.skipped:
                return ("skipped", "", "")
        return None

    # ---- drive the bar + rollup ------------------------------------------

    def pytest_runtest_logreport(self, report) -> None:
        if self.progress is None:
            return

        nid = report.nodeid
        outcome = self._outcome(report)
        if outcome is None or nid in self._seen:
            return
        self._seen.add(nid)

        # Detect file change → flush previous file's rollup row.
        file_path = nid.split("::", 1)[0]
        if self.current_file is None:
            self.current_file = file_path
        elif file_path != self.current_file:
            self._flush_file()
            self.current_file = file_path
            self.file_has_fail = False
            self.file_has_pass = False
            self.file_has_skip = False

        # Update per-test counters + advance the bar.
        if outcome == "passed":
            self.test_passed += 1
            self.file_has_pass = True
            if self.verbose:
                self._emit_test_row(nid, "passed")
            self.progress.advance(ok=True)
        elif outcome == "failed":
            self.test_failed += 1
            self.file_has_fail = True
            err = self._first_error_line(report)
            self.failed_nodeids.append((nid, err))
            if self.verbose:
                self._emit_test_row(nid, "failed", err)
            self.progress.advance(ok=False)
        elif outcome == "skipped":
            self.test_skipped += 1
            self.file_has_skip = True
            reason = self._skip_reason(report)
            self.skip_reasons_by_file.setdefault(file_path, Counter())[reason] += 1
            if self.verbose:
                self._emit_test_row(nid, "skipped", reason)
            # Skips count toward total but aren't failures — advance with
            # ok=True so the bar's ✗N stays accurate to actual failures.
            self.progress.advance(ok=True)

    def _emit_test_row(self, nid: str, outcome: str, detail: str = "") -> None:
        """One ✓/✗/⊘ row per test (verbose mode).

        Pass rows show the full nodeid. Skip/fail rows truncate the
        nodeid and the parenthetical detail so the combined line stays
        under ~120 cols.
        """
        if self.progress is None:
            return
        if outcome == "passed":
            mark = f"{_GREEN}✓{_RESET}" if self.tty else "✓"
        elif outcome == "failed":
            mark = f"{_RED}✗{_RESET}" if self.tty else "✗"
        else:  # skipped
            mark = f"{_YELLOW}⊘{_RESET}" if self.tty else "⊘"
        if detail:
            line = (
                f"  {mark} {_truncate(nid, limit=85)}"
                f"  ({_truncate(detail, limit=30)})"
            )
        else:
            line = f"  {mark} {nid}"
        self.progress.print_above(line)

    def _flush_file(self) -> None:
        """Print the accumulated rollup row for self.current_file."""
        if self.progress is None or self.current_file is None:
            return
        # In verbose mode we already printed a row per test — skip the
        # per-file rollup so the screen doesn't double-list everything.
        if self.verbose:
            return
        if self.file_has_fail:
            status = "FAILED"
        elif self.file_has_pass:
            status = "PASSED"
        elif self.file_has_skip:
            status = "SKIPPED"
        else:
            return  # No reportable tests — don't emit a row.
        # Pad the file-name column based on plain text width, then
        # colour the status only — padding stays correct because the
        # ANSI codes don't change the visible-glyph count.
        self.progress.print_above(
            f"  {self.current_file:<{self.name_w}}  "
            f"{_colour_status(status, tty=self.tty)}"
        )

    @staticmethod
    def _outcome(report):
        if report.when == "setup":
            if report.skipped:
                return "skipped"
            if report.failed:
                return "failed"
        elif report.when == "call":
            if report.passed:
                return "passed"
            if report.failed:
                return "failed"
            if report.skipped:
                return "skipped"
        return None

    @staticmethod
    def _skip_reason(report) -> str:
        if not report.longrepr:
            return ""
        if isinstance(report.longrepr, tuple) and len(report.longrepr) >= 3:
            reason = str(report.longrepr[2])
        else:
            reason = str(report.longrepr).splitlines()[0]
        if reason.startswith("Skipped: "):
            reason = reason[len("Skipped: "):]
        return _truncate(_trim_paren_noise(reason))

    @staticmethod
    def _first_error_line(report) -> str:
        if not report.longrepr:
            return ""
        text = str(report.longrepr)
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith(("E ", "_", "=", ">", ":", "tests/")):
                return line[:80]
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line:
                return line[:80]
        return ""

    # ---- unified final summary block ------------------------------------
    #
    # Runs with tryfirst=True so we render before _pytest.terminal and
    # _pytest.warnings get their turn. We also flip terminalreporter's
    # internal "no_summary" / "no_header" knobs to suppress their output —
    # cleaner than a wholesale reporter swap and keeps pytest's exit code
    # logic intact.

    @pytest.hookimpl(tryfirst=True)
    def pytest_terminal_summary(self, terminalreporter, exitstatus, config):
        tr = terminalreporter
        elapsed = time.time() - self.start_time

        print("\n" + "=" * 60)
        print("  Summary")
        print("=" * 60)
        total = max(self.total, 1)
        print(f"\n  Wall time:   {_fmt_dur(elapsed)}")
        passed_str = f"{self.test_passed}/{self.total}"
        skipped_str = f"{self.test_skipped}/{self.total}"
        failed_str = f"{self.test_failed}/{self.total}"
        if self.tty:
            passed_str = f"{_GREEN}{passed_str}{_RESET}"
            skipped_str = f"{_YELLOW}{skipped_str}{_RESET}" if self.test_skipped else skipped_str
            failed_str = f"{_RED}{failed_str}{_RESET}" if self.test_failed else failed_str
        print(f"  ✓ Passed:    {passed_str} ({100.0 * self.test_passed / total:.1f}%)")
        print(f"  ⊘ Skipped:   {skipped_str}")
        print(f"  ✗ Failed:    {failed_str}")

        if self.failed_nodeids:
            print(f"\n  Failed tests ({len(self.failed_nodeids)}):")
            for nid, msg in self.failed_nodeids:
                line = f"    ✗ {nid}"
                if msg:
                    line += f"\n        {msg}"
                print(line)

        if self.skip_reasons_by_file:
            total_skipped = sum(
                sum(c.values()) for c in self.skip_reasons_by_file.values()
            )
            print(f"\n  Skipped tests ({total_skipped}):")
            file_w = max(len(f) for f in self.skip_reasons_by_file)
            for file_path in sorted(self.skip_reasons_by_file):
                reasons = self.skip_reasons_by_file[file_path]
                count = sum(reasons.values())
                # Most-common skip reason first; collapse identical
                # reasons across multiple tests in the same file.
                top_reason, _ = reasons.most_common(1)[0]
                rest = len(reasons) - 1
                trailer = f"  ({rest} other reason{'s' if rest != 1 else ''})" if rest else ""
                print(f"    {file_path:<{file_w}}  {count} — {top_reason}{trailer}")

        if self.warning_messages:
            # Collapse identical messages across reports.
            counts: Counter = Counter(msg for _, msg in self.warning_messages)
            print(f"\n  Warnings ({len(self.warning_messages)}):")
            for msg, n in counts.most_common():
                multiplier = f" (x{n})" if n > 1 else ""
                print(f"    ⚠ {_truncate(msg)}{multiplier}")

        print("\n" + "=" * 60 + "\n")

        # Mute pytest's own three-block tail. tr.stats and the underlying
        # writer are still intact so internal exit-code logic works.
        # Drop the categories that drive the noise rows of "short test
        # summary info". Failures stay in tr.stats["failed"] so
        # summary_failures() still renders the FAILURES section (with
        # tracebacks) — that's debugging gold.
        for key in ("skipped", "xfailed", "xpassed", "deselected", "rerun"):
            tr.stats.pop(key, None)
        # Both `summary_warnings` and `short_test_summary` print blocks
        # we already render in our Summary block above (Warnings + Skipped
        # tests rollup). They have separate code paths from tr.stats — the
        # only reliable way to suppress them is to no-op the methods on
        # this TerminalReporter instance.
        tr.summary_warnings = lambda: None
        tr.short_test_summary = lambda: None
        # `summary_stats` prints the final "N passed, M skipped in T s"
        # one-liner — also redundant with our Wall time + counts block.
        tr.summary_stats = lambda: None


def pytest_configure(config) -> None:
    """Register under a stable name so users can disable with
    ``-p no:sticky_progress`` (matches the docstring promise).

    Reads pytest's `-v` / `--verbose` flag and threads it into the plugin
    so verbose mode switches from per-file rollup to per-test rows. Then
    pins ``config.option.verbose`` back to ``-1`` so pytest's own
    TerminalReporter stays in quiet mode for the rest of the run — its
    file headers, ``[ N%]`` tails, and ``test session starts`` banner all
    branch on that value, and we'd otherwise be fighting them for screen
    real estate.

    Threshold is ``>= 0`` because ``addopts`` carries ``-q`` (baseline
    verbose = -1); a single ``-v`` brings it back to 0, and that's what
    we treat as "user wants verbose". ``-vv`` (verbose >= 1) also
    activates it.
    """
    user_wants_verbose = config.option.verbose >= 0
    # Pin BEFORE pytest_sessionstart fires (which prints the "test
    # session starts" banner at verbosity >= 0).
    config.option.verbose = -1
    config.pluginmanager.register(
        StickyProgressPlugin(verbose=user_wants_verbose), "sticky_progress"
    )
