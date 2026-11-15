# /// script
# dependencies = ["mlx-whisper"]
# ///
"""Transcribe each screen recording's audio locally (Whisper large-v3-turbo on the Mac's GPU),
with word timings, for choosing cuts and for captions later.

    uv run scripts/transcribe.py          # every tN-screen.mp4
    uv run scripts/transcribe.py t3

Writes transcripts/<take>.json (segments + words) and transcripts/<take>.txt (readable).
"""
import json
import sys
from pathlib import Path

import mlx_whisper

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "public" / "raw"
OUT = ROOT / "transcripts"
OUT.mkdir(exist_ok=True)

takes = sys.argv[1:] or sorted(p.name.removesuffix("-screen.mp4") for p in RAW.glob("*-screen.mp4"))
for take in takes:
    r = mlx_whisper.transcribe(
        str(RAW / f"{take}-screen.mp4"),
        path_or_hf_repo="mlx-community/whisper-large-v3-turbo",
        word_timestamps=True,
        language="en",
        condition_on_previous_text=False,
    )
    segs = [
        {
            "start": round(s["start"], 2),
            "end": round(s["end"], 2),
            "text": s["text"].strip(),
            "words": [
                {"w": w["word"].strip(), "start": round(w["start"], 2), "end": round(w["end"], 2)}
                for w in s.get("words", [])
            ],
        }
        for s in r["segments"]
    ]
    (OUT / f"{take}.json").write_text(json.dumps(segs, indent=1) + "\n")
    lines = [f"[{s['start']:6.2f} - {s['end']:6.2f}] {s['text']}" for s in segs]
    (OUT / f"{take}.txt").write_text("\n".join(lines) + "\n")
    print(f"== {take}")
    print("\n".join(lines))
