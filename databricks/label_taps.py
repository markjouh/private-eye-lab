"""Write tap-style training labels: what the Private Eye app should say when the user taps, in the
app's own positional style ("Bed ahead, lamp left, door right."), plus where-is-it examples.

The first fine-tune learned from question/answer pairs only and stopped saying left/right in tap
descriptions. These labels teach the tap prompts the app actually sends.

Usage:
  uv run --with databricks-sdk --with requests --with pillow label_taps.py \
      <train.json> <image dir> <out.jsonl> --count 3000 [--part i/n] [--workers 64]
Model comes from RELABEL_MODEL (default gpt-6.1-sol). Resumable.
"""
import argparse, json, os, random, sys, threading, time
import concurrent.futures as cf

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx_auth
from relabel_train import encode, output_text

MODEL = os.environ.get("RELABEL_MODEL", "gpt-6.1-sol")

INSTRUCTIONS = """You are writing training data for a phone app used by blind people. The user points the phone and taps; the app speaks what is there. You see the photo exactly as the camera took it. Write what the app should say.

How the app talks. Everything is heard, not read, by someone who cannot skim, so every word costs time:
- Noun phrases, not sentences. No lead-in ("There is", "I see"), no articles, no "is/are".
- Say where things are with the bare words left, ahead or right: the left third, middle third and right third of the photo as given. Do not mentally rotate the photo; positions are as the camera sees them. Put the position after what the thing is on or next to: "Kettle on stove, right."
- Never pick a thing out by its colour ("the orange bottle"); say what it is. Never describe people at all: the app announces people itself.
- Do not guess. Only name things you can actually make out.

Fields to return:
- usable: false if the frame is too dark, too blurred or too close to make anything out; true otherwise.
- close_up: true if the photo is a close-up of one object (one thing held up to the camera or filling most of the frame); false if it shows a scene with several things or a place.
- object_reply: only when close_up is true, else empty. What it is, then any label of its own read off it, like "Shampoo bottle, Head and Shoulders, 13 ounces." If it has no readable label, just what it is, as specifically as you can see: "Stainless steel water bottle." At most twelve words.
- scene_reply: only when close_up is false, else empty. The nearest two to four things and where they are, at most ten words, like "Bed ahead, lamp left, door right." or "Stairs ahead, railing left." No people. If usable is false: "Too dark to tell." or "Too blurry to tell."
- locate: up to two examples of a where-is-it question about a thing that is clearly in the photo and the app's answer: the thing and where it is, like {"question": "Where is the lamp?", "answer": "Lamp on desk, left."}. Vary the wording of the questions the way people speak ("Where's my mug?", "Can you find the remote?"). Leave empty when close_up is true or usable is false.
- absent_thing: one everyday thing that is definitely not in the photo but could plausibly be looked for there (for example "keys", "phone charger", "light switch"). Used to teach the answer "Not visible." """

SCHEMA = {
    "type": "object",
    "properties": {
        "usable": {"type": "boolean"},
        "close_up": {"type": "boolean"},
        "object_reply": {"type": "string"},
        "scene_reply": {"type": "string"},
        "locate": {"type": "array", "items": {
            "type": "object",
            "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
            "required": ["question", "answer"], "additionalProperties": False}},
        "absent_thing": {"type": "string"},
    },
    "required": ["usable", "close_up", "object_reply", "scene_reply", "locate", "absent_thing"],
    "additionalProperties": False,
}


def label(name, image_dir):
    row = {"image": name, "labeller": MODEL}
    try:
        b64 = encode(os.path.join(image_dir, name))
    except Exception as e:
        row["error"] = "image: %s" % e
        return row
    payload = {
        "model": MODEL, "max_output_tokens": 2000, "instructions": INSTRUCTIONS,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": "The user tapped. Here is the camera frame."},
            {"type": "input_image", "image_url": "data:image/jpeg;base64," + b64}]}],
        "text": {"format": {"type": "json_schema", "name": "tap_label", "schema": SCHEMA, "strict": True}},
    }
    for attempt in range(7):
        try:
            r = requests.post(dbx_auth.GATEWAY_URL, headers=dbx_auth.headers(), json=payload, timeout=180)
            if r.status_code in (429, 500, 502, 503, 504, 529):
                row["error"] = r.text[:200]
                time.sleep(min(60, 2 ** attempt + random.random() * 2))
                continue
            if r.status_code != 200:
                row["error"] = r.text[:300]
                break
            data = r.json()
            text = output_text(data)
            row.update(json.loads(text[text.find("{"):text.rfind("}") + 1]))
            usage = data.get("usage") or {}
            row["in_tok"], row["out_tok"] = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
            row.pop("error", None)
            break
        except Exception as e:
            row["error"] = "%s: %s" % (type(e).__name__, str(e)[:200])
            time.sleep(2 + random.random() * 2)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split"), ap.add_argument("image_dir"), ap.add_argument("out")
    ap.add_argument("--count", type=int, default=3000), ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--part", default=""), ap.add_argument("--also-done", nargs="*", default=[])
    args = ap.parse_args()
    names = [x["image"] for x in json.load(open(args.split))]
    random.Random(2026).shuffle(names)
    names = names[: args.count]
    done = set()
    for path in [args.out] + args.also_done:
        if os.path.exists(path):
            for line in open(path):
                try:
                    r = json.loads(line)
                    if "close_up" in r:
                        done.add(r["image"])
                except Exception:
                    pass
    todo = [n for n in names if n not in done]
    if args.part:
        i, n = (int(v) for v in args.part.split("/"))
        todo = todo[i::n]
    print("%d chosen, %d done, %d to do with %s" % (len(names), len(done), len(todo), MODEL), flush=True)
    dbx_auth.headers()
    lock, t0, ok = threading.Lock(), time.time(), 0
    with open(args.out, "a") as out, cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for n, fut in enumerate(cf.as_completed([pool.submit(label, x, args.image_dir) for x in todo]), 1):
            row = fut.result()
            with lock:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                ok += "close_up" in row
            if n % 200 == 0 or n == len(todo):
                print("%d/%d | %.1f/s | ok %d" % (n, len(todo), n / (time.time() - t0), ok), flush=True)
    print("DONE in %.0f s" % (time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
