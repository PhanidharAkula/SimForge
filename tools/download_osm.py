"""
Download OSM PBF snapshots listed in ``osm_data/manifest.json`` and verify
their SHA256 hashes.

Running this script is a no-op if every file is already present and hashes.
Otherwise it fetches missing / corrupt files from Geofabrik and refuses to
proceed on hash mismatch (never leaves a broken PBF behind).

Usage:
    python tools/download_osm.py            # all files in manifest
    python tools/download_osm.py illinois   # one file
    python tools/download_osm.py --force    # re-download even if present
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
OSM_DIR = REPO_ROOT / "osm_data"
MANIFEST = OSM_DIR / "manifest.json"


def sha256_of(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def download(url: str, dest: Path) -> None:
    """Stream URL → dest with a one-line progress readout every 10 MB."""
    tmp = dest.with_suffix(dest.suffix + ".partial")
    with urlopen(url) as resp, tmp.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        next_report = 10 * 1024 * 1024
        while True:
            buf = resp.read(1024 * 1024)
            if not buf:
                break
            out.write(buf)
            read += len(buf)
            if read >= next_report:
                pct = f"{100 * read / total:.1f}%" if total else ""
                print(f"    ... {human(read)} {pct}")
                next_report += 10 * 1024 * 1024
    tmp.rename(dest)


def resolve_one(key: str, entry: dict, force: bool) -> bool:
    """Ensure one manifest entry is present and hash-correct. Return True on success."""
    dest = OSM_DIR / entry["path"]
    expected_sha = entry["sha256"]

    if dest.exists() and not force:
        print(f"  [{key}] present ({human(dest.stat().st_size)}) — verifying hash ...")
        actual = sha256_of(dest)
        if actual == expected_sha:
            print(f"  [{key}] OK (sha256 matches manifest)")
            return True
        print(f"  [{key}] HASH MISMATCH — re-downloading")
        print(f"    expected: {expected_sha}")
        print(f"    actual:   {actual}")
        dest.unlink()

    url = entry["url"]
    print(f"  [{key}] downloading from {url}")
    print(f"    → {dest}")
    download(url, dest)

    actual = sha256_of(dest)
    if actual != expected_sha:
        dest.unlink(missing_ok=True)
        print(f"  [{key}] FAILED — downloaded file hash does not match manifest")
        print(f"    expected: {expected_sha}")
        print(f"    actual:   {actual}")
        print("    (Geofabrik's '-latest' rotates daily. If the upstream file has")
        print("     changed, regenerate the manifest with the new hash and commit it.)")
        return False

    print(f"  [{key}] OK ({human(dest.stat().st_size)})")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("keys", nargs="*", help="Manifest keys to fetch (default: all)")
    parser.add_argument("--force", action="store_true", help="Re-download even if present")
    args = parser.parse_args()

    if not MANIFEST.exists():
        print(f"ERROR: manifest not found at {MANIFEST}", file=sys.stderr)
        return 1

    manifest = json.loads(MANIFEST.read_text())
    files = manifest["files"]

    selected = args.keys or list(files.keys())
    unknown = [k for k in selected if k not in files]
    if unknown:
        print(f"ERROR: unknown manifest keys: {unknown}", file=sys.stderr)
        print(f"  available: {list(files.keys())}", file=sys.stderr)
        return 1

    OSM_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Resolving {len(selected)} OSM PBF file(s) against {MANIFEST.name}:")
    failures = [k for k in selected if not resolve_one(k, files[k], args.force)]

    if failures:
        print(f"\n{len(failures)} file(s) failed: {failures}", file=sys.stderr)
        return 2

    print(f"\nAll {len(selected)} file(s) present and verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
