#!/usr/bin/env bash
set -euo pipefail
cache_dir="${RUNNER_TEMP:?This script is for GitHub Actions}/factory-render-apt"
packages=()
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  packages+=(ffmpeg)
fi
if [[ ! -f /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf && ! -f /usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf ]]; then
  packages+=(fonts-dejavu-core)
fi
if ((${#packages[@]})); then
  mkdir -p "$cache_dir"
  echo "Installing missing rendering packages: ${packages[*]} (using cached downloads where available)."
  sudo apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 update -qq
  sudo apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=20 -o Acquire::https::Timeout=20 \
    -o "Dir::Cache::archives=$cache_dir" -o APT::Keep-Downloaded-Packages=true \
    install -y --no-install-recommends "${packages[@]}"
  # Let the cache action archive and restore all package files as the runner user.
  sudo chown -R "$(id -u):$(id -g)" "$cache_dir"
else
  echo 'Rendering tools and a supported font are already available; skipping apt.'
fi
# Exercise the actual encoders, not merely the executable names.
workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
ffmpeg -hide_banner -loglevel error -y -f lavfi -i color=c=black:s=64x64:r=10 \
  -f lavfi -i anullsrc=r=24000:cl=mono -t 0.2 -c:v libx264 -pix_fmt yuv420p -c:a aac "$workdir/check.mp4"
ffprobe -v error -show_entries stream=codec_name -of csv=p=0 "$workdir/check.mp4"
echo 'FFmpeg H.264/AAC encoding and ffprobe checks passed.'
