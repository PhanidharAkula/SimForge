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
        elapsed = time.time() - self.start_time
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
