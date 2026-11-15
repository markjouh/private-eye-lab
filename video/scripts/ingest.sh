#!/bin/bash
# Copy a recording into public/raw as a constant-30fps H.264 file Remotion can seek reliably.
# Phone and screen recordings are variable frame rate, which drifts out of sync otherwise.
#
#   npm run ingest -- ~/Movies/IMG_1234.MOV outside
#   npm run ingest -- ~/Movies/ScreenRecording.mp4 screen
set -euo pipefail

src="${1:?usage: ingest.sh <input file> <outside|screen|other name>}"
name="${2:?usage: ingest.sh <input file> <outside|screen|other name>}"
dir="$(cd "$(dirname "$0")/.." && pwd)/public/raw"
mkdir -p "$dir"
out="$dir/$name.mp4"

# HDR (HLG from Samsung / iPhone cameras) looks washed out unless it is converted to SDR.
transfer="$(ffprobe -v error -select_streams v:0 -show_entries stream=color_transfer -of csv=p=0 "$src" | head -1 | tr -d ', \n' || true)"
vf="fps=30"
if [[ "$transfer" == "arib-std-b67" || "$transfer" == "smpte2084" ]]; then
  # This ffmpeg build has no zscale, so read HLG as SDR BT.2020 (it is designed to be
  # watchable that way) and convert the colours to BT.709. Checked against Apple's
  # avconvert tone-mapping: near identical for these clips.
  vf="colorspace=all=bt709:iall=bt2020:itrc=bt2020-10:fast=0,format=yuv420p,fps=30"
  echo "HDR source ($transfer): converting to SDR"
fi

ffmpeg -hide_banner -loglevel warning -stats -y -i "$src" \
  -vf "$vf" -fps_mode cfr \
  -c:v libx264 -preset veryfast -crf 16 -g 30 -pix_fmt yuv420p \
  -c:a aac -b:a 256k -ar 48000 \
  -movflags +faststart "$out"

# A still from the middle of the clip, used as the blurred backdrop behind portrait footage.
mid="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$out" | awk '{print $1/2}')"
ffmpeg -hide_banner -loglevel error -y -ss "$mid" -i "$out" -frames:v 1 -vf "scale=640:-2" -q:v 4 "$dir/$name-poster.jpg"

echo "wrote $out"
ffprobe -v error -show_entries format=duration:stream=codec_type,width,height,r_frame_rate -of compact "$out"
