"""
Lightweight progress bar for terminal output — no external dependencies.

Usage:
    from pipeline.progress import ProgressBar

    pb = ProgressBar(total=1000, desc="Generating trips")
    for i in range(1000):
        do_work(i)
        pb.update()
    pb.finish()

    # Or as a context manager:
    with ProgressBar(total=500, desc="Downloading") as pb:
        for chunk in download():
            pb.update()
"""

import sys
import time


class ProgressBar:
    """Minimal progress bar using only stdlib."""

    def __init__(self, total: int, desc: str = "", width: int = 30):
        self.total = max(total, 1)
        self.desc = desc
        self.width = width
        self.current = 0
        self.start_time = time.time()
        self._last_print = 0.0
        self._print_interval = 0.15  # seconds between redraws

    def update(self, n: int = 1) -> None:
        self.current = min(self.current + n, self.total)
        now = time.time()
        # Rate-limit redraws to avoid terminal flooding
        if now - self._last_print >= self._print_interval or self.current >= self.total:
            self._draw()
            self._last_print = now

    def _draw(self) -> None:
        frac = self.current / self.total
        filled = int(self.width * frac)
        bar = "█" * filled + "░" * (self.width - filled)
        pct = frac * 100

        elapsed = time.time() - self.start_time
        elapsed_str = self._fmt_time(elapsed)

        if self.current > 0 and self.current < self.total:
            eta = elapsed * (self.total - self.current) / self.current
            eta_str = self._fmt_time(eta)
        else:
            eta_str = "--:--"

        desc = f"{self.desc}: " if self.desc else ""
        line = (
            f"\r  {desc}[{bar}] {pct:5.1f}%  "
            f"{self.current:,}/{self.total:,}  "
            f"elapsed {elapsed_str}  eta {eta_str}"
        )
        sys.stderr.write(line)
        sys.stderr.flush()

    def finish(self, message: str = "") -> None:
        self.current = self.total
        self._draw()
        _ = time.time() - self.start_time  # elapsed, reserved for future use
        if message:
            sys.stderr.write(f"  {message}")
        sys.stderr.write("\n")
        sys.stderr.flush()

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            m, s = divmod(int(seconds), 60)
            return f"{m}m{s:02d}s"
        else:
            h, rem = divmod(int(seconds), 3600)
            m = rem // 60
            return f"{h}h{m:02d}m"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.finish()


# ---------------------------------------------------------------------------
# StickyProgress — used by the entry-point CLIs (run.py, generate.py)
# ---------------------------------------------------------------------------
#
# A single-line progress bar that lives at the bottom of the screen while
# log lines accumulate above it. Designed for benchmark / generation flows
# where work happens in discrete steps and a heartbeat spinner gives visible
# motion during long steps that have no internal progress signal.
#
# Differences from the older ProgressBar above:
#   - Tracks DISCRETE steps (advance() bumps by 1) instead of continuous
#     work units (update(n)).
#   - Always-on heartbeat thread that re-renders the spinner every ~200 ms
#     so the operator can see "still alive" during a 60+ s step.
#   - Stays at the bottom of the screen with a blank-line gap above and
#     accepts print_above() calls that emit persistent log lines without
#     clobbering the bar.
#   - Flicker-free: the heartbeat redraw uses `\r + content + \033[K`
#     (clear-to-EOL AFTER writing), so the terminal never sees a cleared
#     frame between renders. Only print_above() does a true erase + reflow.
#   - TTY-only: silently no-ops when stdout is piped (sbatch logs, CI
#     captures) — print_above() then just prints the log line.

import logging as _logging
import threading


_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# Plain (non-bold, non-dim) colours so filled and empty cells render at
# identical glyph weight and height. Earlier we used \033[1;36m (bold
# cyan) for the filled portion and \033[2m (dim) for the empty portion;
# bold subtly thickens characters in most terminal fonts which made the
# cyan cells appear "taller" than the dim ones, and the bold/dim
# transition at the boundary rendered the last cyan cell as half-filled.
_BAR_FILL = "\033[97m"         # bright white (active / in-progress)
_BAR_EMPTY = "\033[90m"        # bright black / gray (no dim attribute)
_SPINNER_COLOR = "\033[1;97m"  # bold bright white for the spinner
_RESET = "\033[0m"


def _fmt_dur(seconds: float) -> str:
    """Format a duration as Xs / Xm YYs / Xh YYm YYs for human consumption."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m"


class _ProgressBarLogHandler(_logging.Handler):
    """Routes log records through StickyProgress.print_above() so they
    land above the sticky bar without colliding with the bar's own
    no-newline writes. Used by capture_logs=True to keep --verbose
    output readable."""

    def __init__(self, progress: "StickyProgress"):
        super().__init__()
        self.progress = progress

    def emit(self, record: _logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.progress.print_above(msg)
        except Exception:  # noqa: BLE001 — logging mustn't crash callers
            self.handleError(record)


class StickyProgress:
    """Sticky single-line progress bar with spinner heartbeat. See module
    docstring above for the design rationale and usage patterns."""

    BAR_WIDTH = 32

    def __init__(self, total: int, *, unit: str = "step",
                 ok_count: int = 0, fail_count: int = 0,
                 enabled: bool = True,
                 capture_logs: bool = False,
                 capture_log_level: int = _logging.INFO,
                 capture_log_names: tuple = ("",)):
        """Initialise the bar.

        Pass ``enabled=False`` to suppress all rendering (useful when
        stdout is not a TTY and the bar would just print escape-code
        junk in the captured log). When disabled, every method becomes
        a silent no-op except ``print_above`` which still emits the
        line so per-step ✓ rows appear in the output.

        Pass ``capture_logs=True`` to install a logging handler that
        routes every log record through ``print_above()`` so log lines
        land cleanly above the sticky bar instead of colliding with the
        bar's own no-newline writes. Critical for --verbose mode where
        adapter INFO chatter and the sticky bar would otherwise mush
        together on the same stdout. Existing StreamHandlers writing to
        stdout are removed to avoid duplication. Restore the previous
        handlers by calling ``stop()`` (which is also a no-op-safe).
        """
        self.total = max(total, 1)
        self.completed = 0
        self.current_label = ""
        self.unit = unit
        self.ok = ok_count
        self.fail = fail_count
        self.t0 = time.time()
        self.is_tty = sys.stdout.isatty() and enabled
        self._drawn = False
        self._stop = threading.Event()
        self._thread = None
        self._tick = 0
        self._lock = threading.Lock()
        self._captured_loggers: list[tuple] = []  # (logger, removed_handlers)
        self._capture_handler: _ProgressBarLogHandler | None = None
        if capture_logs and self.is_tty:
            self._install_log_capture(capture_log_level, capture_log_names)

    # ---- public API --------------------------------------------------

    def start(self) -> None:
        """Spawn the heartbeat thread (no-op on non-TTY)."""
        if not self.is_tty or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._thread.start()

    def set_label(self, label: str) -> None:
        """Update the in-progress step label without bumping the count."""
        with self._lock:
            self.current_label = label
            self._render_locked()

    def advance(self, label=None, *, ok: bool = True) -> None:
        """Mark the current unit done and bump the percentage. Pass
        ok=False to count as a failure (red ✗N in the bar tail)."""
        with self._lock:
            self.completed = min(self.completed + 1, self.total)
            if label is not None:
                self.current_label = label
            if ok:
                self.ok += 1
            else:
                self.fail += 1
            self._render_locked()

    def print_above(self, line: str = "") -> None:
        """Emit a persistent log line above the sticky bar. Erases the
        bar first so the line lands cleanly, then re-renders the bar at
        the new bottom."""
        with self._lock:
            self._erase_locked()
            print(line)
            self._render_locked()

    def stop(self) -> None:
        """Halt the heartbeat thread, erase the bar, and uninstall any
        log-capture handler so subsequent log calls work normally."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        with self._lock:
            self._erase_locked()
        self._uninstall_log_capture()

    # ---- log capture (used by --verbose entry-points) ---------------

    def _install_log_capture(self, level: int,
                             logger_names: tuple) -> None:
        """Replace stdout-bound StreamHandlers on the named loggers with
        a handler that routes through print_above(). Cached so stop()
        can restore the previous handlers."""
        handler = _ProgressBarLogHandler(self)
        handler.setLevel(level)
        handler.setFormatter(_logging.Formatter("%(levelname)s  %(message)s"))
        self._capture_handler = handler
        for name in logger_names:
            logger = _logging.getLogger(name)
            removed = []
            for h in list(logger.handlers):
                # Only displace handlers that would write to stdout (the
                # bar's stream). Leave file handlers, syslog handlers,
                # etc. in place so other audit trails keep working.
                if (isinstance(h, _logging.StreamHandler)
                        and getattr(h, "stream", None) is sys.stdout):
                    logger.removeHandler(h)
                    removed.append(h)
            logger.addHandler(handler)
            if level < logger.level or logger.level == _logging.NOTSET:
                logger.setLevel(level)
            self._captured_loggers.append((logger, removed))

    def _uninstall_log_capture(self) -> None:
        if self._capture_handler is None:
            return
        for logger, removed in self._captured_loggers:
            try:
                logger.removeHandler(self._capture_handler)
            except ValueError:
                pass
            for h in removed:
                logger.addHandler(h)
        self._captured_loggers.clear()
        self._capture_handler = None

    # ---- rendering ---------------------------------------------------

    def _heartbeat(self) -> None:
        # ~5 frames per second so the spinner motion is obvious without
        # flooding the terminal.
        while not self._stop.is_set():
            with self._lock:
                if self._drawn:
                    # Tick only when the bar is currently on screen
                    # (skip ticks during print_above transitions).
                    self._tick += 1
                    self._render_locked(_in_place=True)
            self._stop.wait(0.2)

    def _render_locked(self, *, _in_place: bool = False) -> None:
        """Redraw the bar.

        When _in_place=True (heartbeat path), only the bar line is
        rewritten in place via `\\r + content + \\033[K`. The blank line
        above stays untouched, so there is no perceptible flicker.

        When _in_place=False (advance, set_label, post-print_above
        re-render), the full blank+bar pair is drawn from scratch so
        the bar appears below the most recently printed log line.
        """
        if not self.is_tty:
            return
        elapsed = time.time() - self.t0
        progress = self.completed
        # Honest fill: bar width tracks the actual completed fraction,
        # nothing more. The spinner already provides the "still alive"
        # visual cue (cyan + animated), so we don't fake a 1-cell tip
        # at 0% — that lied about progress (bar showed something filled
        # while the % label said 0.0%, which was confusing). Empty bar
        # at start, spinner spinning, percentage honest.
        if progress >= self.total:
            filled = self.BAR_WIDTH
        else:
            filled = int(self.BAR_WIDTH * progress / self.total)
        # Use full-block █ for filled cells and light-shade ░ for empty
        # cells. Both glyphs fill the entire character cell vertically
        # (so no height mismatch / boundary artefact between the two
        # halves), but the fill DENSITY differs — solid block vs sparse
        # texture — so the empty portion is visually obviously "not
        # filled" even when its colour is gray. Using █ for both cells
        # made the bar look uniformly solid at a glance because gray █
        # on a dark terminal still reads as a full block.
        bar = (_BAR_FILL + ("█" * filled) + _RESET
               + _BAR_EMPTY + ("░" * (self.BAR_WIDTH - filled)) + _RESET)
        pct = 100.0 * progress / self.total
        if 0 < progress < self.total:
            eta = (elapsed / progress) * (self.total - progress)
            eta_s = _fmt_dur(eta)
        elif progress >= self.total:
            eta_s = "0s"
        else:
            eta_s = "--"
        if progress >= self.total:
            spinner = _SPINNER_COLOR + "✓" + _RESET
        else:
            spinner = (_SPINNER_COLOR
                       + _SPINNER_FRAMES[self._tick % len(_SPINNER_FRAMES)]
                       + _RESET)
        # Optional ✓N ✗N counters in the tail (used by run.py; for
        # generate.py these stay at 0 and we suppress them).
        counters = ""
        if self.ok or self.fail:
            counters = (f"  \033[32m✓{self.ok}\033[0m "
                        f"\033[31m✗{self.fail}\033[0m")
        label = self.current_label or "..."
        bar_line = (f"  {bar}  {spinner}  {pct:>3.0f}%  "
                    f"{self.unit} {min(progress + 1, self.total)}/{self.total}: "
                    f"{label}{counters}  "
                    f"elapsed {_fmt_dur(elapsed)}  ETA {eta_s}")
        if _in_place and self._drawn:
            # Flicker-free in-place rewrite: cursor still on the bar
            # line from the previous render. \r jumps to column 0,
            # write new bar text, \033[K trims any leftover characters
            # from a longer previous frame. Single-pass, single flush.
            sys.stdout.write("\r" + bar_line + "\033[K")
        else:
            # Fresh draw (or post-print_above re-render): print blank
            # line + bar text. clear-to-EOL on the bar line so any
            # leftover characters on those screen rows are wiped.
            if self._drawn:
                sys.stdout.write("\r\033[K\033[1A\r\033[K")
            sys.stdout.write("\n" + bar_line + "\033[K")
        sys.stdout.flush()
        self._drawn = True

    def _erase_locked(self) -> None:
        if not self.is_tty or not self._drawn:
            return
        # Clear bar line + blank line above. Cursor lands at the start
        # of where the blank used to be, ready for caller's print().
        sys.stdout.write("\r\033[K\033[1A\r\033[K")
        sys.stdout.flush()
        self._drawn = False

    # ---- context-manager sugar ---------------------------------------

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_exc):
        self.stop()
