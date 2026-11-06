#!/usr/bin/env bash
# CI (Ubuntu): install FFmpeg + DejaVu fonts without hanging on a stuck apt mirror.
# Each apt attempt has its own time limit; after 3 tries it falls back to a static
# FFmpeg build from GitHub (BtbN, GPL), which is put on the PATH for later steps.
set -u
APT_OPTS=(-o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o DPkg::Lock::Timeout=60)

for try in 1 2 3; do
  echo "apt attempt $try"
  if timeout 180 sudo apt-get "${APT_OPTS[@]}" update -q \
     && timeout 240 sudo apt-get "${APT_OPTS[@]}" install -y -q --no-install-recommends ffmpeg fonts-dejavu-core; then
    ffmpeg -hide_banner -version | head -1
    exit 0
  fi
  sleep $((try * 10))
done

echo "::warning::apt kept failing; using a static FFmpeg build instead"
url="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
dir="$HOME/ffmpeg-static"
mkdir -p "$dir"
for try in 1 2 3; do
  if curl -fsSL --retry 3 --max-time 300 "$url" | tar -xJ -C "$dir" --strip-components=1; then
    echo "$dir/bin" >> "$GITHUB_PATH"
    "$dir/bin/ffmpeg" -hide_banner -version | head -1
    # the captions/titles need DejaVu; most runners have it already
    fc-list | grep -qi dejavu || echo "::warning::DejaVu fonts missing; caption tests may differ"
    exit 0
  fi
  sleep 10
done
echo "::error::could not install FFmpeg"
exit 1
