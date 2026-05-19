#!/bin/bash
# ============================================================================
# SimForge — animated_flow renders for the large tier (200K + 500K scenarios).
#
# Renders the per-vehicle particle animation for both chicago_200k_car and
# nyc_500k_car. Single-threaded Python + ffmpeg pipe per scenario; runs
# sequentially to avoid memory contention on the events-file decode.
#
# Why Cardinal vs Mac:
#   The Mac render hit ~1 h wall before being cancelled because the user
#   needed to take the Mac out (battery + lid-closed). Cardinal can run
#   for hours uninterrupted. The animated_flow renderer is not parallel
#   (single-threaded matplotlib + single ffmpeg pipe), so Cardinal's
#   Sapphire Rapids gives only ~1.2-1.5× single-thread speedup vs Mac
#   arm64. The real Cardinal advantage is the wall-time stability.
#
# Wall-time projection:
#   chicago_200k animated_flow: events file ~315 MB compressed.
#     Decode + frame gen on Mac was ~60 min before cancel; full render
#     estimated ~90-120 min on Mac. Cardinal: ~60-90 min.
#   nyc_500k animated_flow: events file ~522 MB compressed.
#     Estimated ~120-180 min on Cardinal.
#   Sequential total: ~3-5 h. --time=6:00:00 provides margin.
#
# Resources:
#   --partition=cpu        : Single-threaded; CPU node is the right choice.
#   --cpus-per-task=8      : 1 thread for Python + 1 for ffmpeg + headroom.
#                            Animated_flow doesn't benefit from >8 cores.
#   --mem=64G              : Events file decode + frame buffer. nyc_500k
#                            with 522 MB compressed events + 2716×2200×4
#                            rgba frames in flight needs ~30-40 G; 64 G
#                            is conservative.
#   --time=6:00:00         : 6 h. ~1.2-2× margin over the 3-5 h sequential
#                            estimate. Single sbatch covers both scenarios.
#
# ffmpeg dependency:
#   The renderer uses matplotlib's FFMpegWriter which needs `ffmpeg` on
#   PATH. The script tries `module load ffmpeg` first (works on most OSC
#   systems) and falls back to imageio-ffmpeg's bundled binary if the
#   module isn't available. If both fail, the renderer logs a clear error
#   and skips animated_flow (other map types still work).
# ============================================================================

#SBATCH --account=PMIU0110
#SBATCH --job-name=simforge_animated_flow_large
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=6:00:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err
##SBATCH --mail-type=END,FAIL
##SBATCH --mail-user=your-email@example.com

set -euo pipefail
shopt -s nullglob

mkdir -p logs
cd ~/SimForge
source .venv/bin/activate

# ---------------------------------------------------------------------------
# Try to make ffmpeg available. Three fallback levels:
#   1. Cardinal `module load ffmpeg` (likely available)
#   2. imageio-ffmpeg bundled binary (pip install if missing)
#   3. Bail with clear message
# ---------------------------------------------------------------------------
echo "=== Locating ffmpeg ==="
if module load ffmpeg 2>/dev/null && command -v ffmpeg >/dev/null 2>&1; then
    echo "  ffmpeg from module:  $(which ffmpeg)"
    echo "  version:             $(ffmpeg -version 2>&1 | head -1)"
elif python -c "import imageio_ffmpeg" 2>/dev/null; then
    FFBIN=$(python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())")
    export PATH="$(dirname $FFBIN):$PATH"
    echo "  ffmpeg from imageio-ffmpeg: $FFBIN"
else
    echo "  ffmpeg not on PATH and imageio-ffmpeg not installed."
    echo "  Installing imageio-ffmpeg via uv..."
    uv pip install imageio-ffmpeg
    FFBIN=$(python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())")
    export PATH="$(dirname $FFBIN):$PATH"
    echo "  ffmpeg installed at: $FFBIN"
fi
echo

echo "=== Job starting on $(hostname) at $(date) ==="
echo "Python:  $(which python)"
echo "Free mem: $(free -h | awk 'NR==2{print $4}')"
echo

# ---------------------------------------------------------------------------
# Render animated_flow for both scenarios sequentially.
# Sequential (not parallel) to avoid memory contention — the events-file
# decode + rgba frame buffer can spike to 30-40 G each.
# ---------------------------------------------------------------------------
for scenario in chicago_200k_car nyc_500k_car; do
    echo "================================================================"
    echo "=== Rendering animated_flow for $scenario ==="
    echo "================================================================"

    if [ ! -d "runs/benchmark_large/$scenario" ]; then
        echo "  SKIP: runs/benchmark_large/$scenario not present — rsync the run dir from your dev box first."
        continue
    fi

    START=$(date +%s)
    python -u -m visualization.generate_maps \
        --scenario "$scenario" \
        --run-dir "runs/benchmark_large/$scenario" \
        --maps animated_flow
    END=$(date +%s)
    ELAPSED=$((END - START))
    echo "  $scenario animated_flow finished in $((ELAPSED / 60)) min $((ELAPSED % 60)) s"
    echo
done

echo "=== Job complete at $(date) ==="
echo
echo "Output files (rsync these back to your dev box):"
for scenario in chicago_200k_car nyc_500k_car; do
    for f in visualization/output/$scenario/animated_flow*.mp4; do
        [ -f "$f" ] && echo "  $(du -h $f | cut -f1)  $f"
    done
done
echo
echo "Pull-back rsync (run on your dev box):"
echo "  rsync -avzP phanidharakula@cardinal.osc.edu:/users/PMIU0110/phanidharakula/SimForge/visualization/output/ visualization/output/"
