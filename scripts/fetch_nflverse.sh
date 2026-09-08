#!/usr/bin/env bash
# Prefetch nflverse schedules + PBP parquets into .cache/nflverse (gitignored).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="${NFLVERSE_CACHE:-$ROOT/.cache/nflverse}"
START="${NFLVERSE_START_SEASON:-1999}"
END="${NFLVERSE_END_SEASON:-2025}"
UA="nfl-ats/0.1 (+https://github.com/WyattCurtis327/nfl-ats)"
mkdir -p "$CACHE"
ok=0
fail=0
skip=0

fetch() {
  local url="$1" dest="$2"
  local tmp="${dest}.tmp"
  if [[ -f "$dest" && "${FORCE:-0}" != "1" ]]; then
    echo "skip exists $(basename "$dest")"
    skip=$((skip+1))
    return 0
  fi
  if curl -fL --retry 3 --retry-delay 2 -A "$UA" -o "$tmp" "$url"; then
    mv "$tmp" "$dest"
    echo "ok $(basename "$dest") ($(du -h "$dest" | cut -f1))"
    ok=$((ok+1))
  else
    rm -f "$tmp"
    echo "fail $(basename "$dest")"
    fail=$((fail+1))
    return 1
  fi
}

echo "cache=$CACHE seasons=${START}-${END}"
fetch "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet" "$CACHE/games.parquet" || true
for y in $(seq "$START" "$END"); do
  fetch "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_${y}.parquet" \
    "$CACHE/play_by_play_${y}.parquet" || true
done
echo "summary ok=$ok skip=$skip fail=$fail"
ls -lh "$CACHE" | head -60
du -sh "$CACHE"
