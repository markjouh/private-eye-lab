# /// script
# dependencies = ["numpy", "scipy"]
# ///
"""Line up each outside-camera clip with its screen recording by matching their audio.

    uv run scripts/sync.py            # every tN-outside / tN-screen pair in public/raw
    uv run scripts/sync.py t3         # one take

Writes src/sync.json: for each take, `offset` = where the outside clip is (seconds)
at the moment the screen recording starts. Negative means the camera started later.
`score` is how far the best match stands above the runner-up; under ~2 is doubtful.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "public" / "raw"
SR = 16000


def audio(path: Path) -> np.ndarray:
    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR),
         "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(pcm, dtype=np.float32)


def whiten(x: np.ndarray, n: int) -> np.ndarray:
    """Flatten the spectrum (PHAT weighting) so the match is sharp and room tone matters less."""
    spec = np.fft.rfft(x, n)
    spec /= np.abs(spec) + 1e-9
    # keep the speech band, where both microphones hear the same thing
    freqs = np.fft.rfftfreq(n, 1 / SR)
    spec[(freqs < 200) | (freqs > 4000)] = 0
    return np.fft.irfft(spec, n)


def offset(outside: np.ndarray, screen: np.ndarray) -> tuple[float, float]:
    n = len(outside) + len(screen)
    a, b = whiten(outside, n)[: len(outside)], whiten(screen, n)[: len(screen)]
    corr = fftconvolve(a, b[::-1], mode="full")
    lags = np.arange(-(len(b) - 1), len(a))
    mag = np.abs(corr)
    best = int(np.argmax(mag))
    # runner-up: best peak at least half a second away from the winner
    away = mag.copy()
    away[max(0, best - SR // 2): best + SR // 2] = 0
    return lags[best] / SR, float(mag[best] / (away.max() + 1e-12))


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    j = json.loads(out)
    st = j["streams"][0]
    return {"w": st["width"], "h": st["height"], "dur": round(float(j["format"]["duration"]), 3)}


def main() -> None:
    takes = sys.argv[1:] or sorted(
        p.name.removesuffix("-screen.mp4") for p in RAW.glob("*-screen.mp4")
    )
    out_path = ROOT / "src" / "sync.json"
    result = json.loads(out_path.read_text()) if out_path.exists() else {}
    for take in takes:
        o, s = RAW / f"{take}-outside.mp4", RAW / f"{take}-screen.mp4"
        if not o.exists():
            # screen recording with no camera clip (e.g. the intro)
            result[take] = {"offset": 0, "score": 0, "outside": None, "screen": probe(s)}
            print(f"{take}: screen recording only")
            continue
        off, score = offset(audio(o), audio(s))
        result[take] = {
            "offset": round(off, 3),
            "score": round(score, 2),
            "outside": probe(o),
            "screen": probe(s),
        }
        print(f"{take}: outside is at {off:+.3f} s when the screen recording starts (score {score:.1f})")
    out_path.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
