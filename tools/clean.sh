#!/usr/bin/env bash
# Wipe regenerable caches.
#
# Default: Python bytecode only (safe, regenerates instantly on next import).
# --all:   also drops the OSM Overpass cache (next benchmark re-fetches; slow).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WIPE_OSM=0
for arg in "$@"; do
  case "$arg" in
    --all) WIPE_OSM=1 ;;
    -h|--help)
      echo "Usage: tools/clean.sh [--all]"
      echo "  (no args)  wipe Python bytecode (__pycache__, *.pyc, .pytest_cache)"
      echo "  --all      additionally wipe cache/ (OSM Overpass HTTP cache)"
      exit 0
      ;;
    *)
      echo "Unknown arg: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

echo "Cleaning Python bytecode under $REPO_ROOT ..."
PYC_DIRS=$(find . -type d -name __pycache__ -not -path "./.venv/*" 2>/dev/null | wc -l | tr -d ' ')
PYC_FILES=$(find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -not -path "./.venv/*" 2>/dev/null | wc -l | tr -d ' ')
find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -not -path "./.venv/*" -delete 2>/dev/null || true
echo "  removed $PYC_DIRS __pycache__/ dir(s) and $PYC_FILES *.pyc/*.pyo file(s)"

if [ -d ".pytest_cache" ]; then
  rm -rf .pytest_cache
  echo "  removed .pytest_cache/"
fi

if [ "$WIPE_OSM" -eq 1 ]; then
  if [ -d "cache" ]; then
    OSM_FILES=$(find cache -type f 2>/dev/null | wc -l | tr -d ' ')
    rm -rf cache
    echo "Removed cache/ (${OSM_FILES} OSM response file(s)) — next fetch will hit Overpass"
  else
    echo "cache/ already absent"
  fi
fi

echo "Done."
