"""Relabel VizWiz photos from this Mac through the Databricks gateway, in parallel and resumable.

Usage:
  uv run --with databricks-sdk --with requests --with pillow relabel_train.py \
      <split.json> <image dir> <out.jsonl> [--workers 48] [--limit N]

Each line of <out.jsonl> is one photo: id, question, crowd tally and the new label, including
`spoken_answer`, the reply the app should speak (the fine-tuning target). Re-running skips ids
that already have a label, so it is safe to stop and restart.
"""
import argparse, base64, io, json, os, random, sys, threading, time
import concurrent.futures as cf

import requests
from PIL import Image, ImageOps

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx_auth

MODEL = os.environ.get("RELABEL_MODEL", "gpt-6.1-sol")
PRICE_IN, PRICE_OUT = (1.00, 5.00) if "terra" in MODEL else (2.00, 10.00)  # listed price per million tokens

INSTRUCTIONS = """You are helping build training data for a phone app that answers spoken questions from blind people about what their camera sees.

Each item comes from the VizWiz dataset: a photo taken by a blind person, the question they asked aloud (transcribed; sometimes rambling, sometimes not a question at all), and short answers from ten crowd workers. The crowd answers are noisy. Workers often wrote "unanswerable" when the answer was readable with some effort, they disagree on wording, and a few typed nonsense. The answers were also stored lowercased with punctuation and small words removed.

Your job is to look at the photo yourself and decide the correct label. Use the crowd answers as hints about where to look, but only accept what you can verify in the photo. If the crowd says something you cannot see, do not repeat it. If you can read or see the answer and the crowd said "unanswerable", overturn them. Photos are often rotated, blurred or badly framed, so mentally rotate the image before reading text. Do not guess text you cannot actually read.

Fields to return:
- answerable: "yes" if the photo shows enough to answer the question as asked. "partly" if the photo answers only part of what was asked, or only at a coarser level: the brand but not the flavour, a site's name but not its address, "a bottle" but not what is in it, a screen you can describe but whose text you cannot read. "no" if the needed information is not visible at all.
- spoken_answer: the reply the app should speak. It is heard, not read, by someone who cannot skim, so every word costs time. Write it the way a sighted guide talks:
  - Answer first. No lead-in ("There is", "It is", "I can see") and no repeating the question.
  - Noun phrases, not sentences, without articles or "is/are": "Diet Pepsi, 20 ounce bottle." not "It is a bottle of Diet Pepsi."
  - One to eight words, at most ten for a scene. Be as specific as the photo allows: read the brand, flavour, title or number off the label when it is visible, rather than naming the general kind of thing.
  - A yes/no answer starts with "Yes" or "No", then the fact that decides it: "No, mixed recycling."
  - When the question asks what something says, give the text exactly as printed, including small words. This may be longer than eight words; never shorten or reword printed text. The crowd's wording had small words stripped, so do not copy it.
  - People: hair, clothing and what they are doing. Never ethnicity, skin colour, age or build.
  - For "partly": the part that can be answered, then what is missing in a few words: "Campbell's soup, flavour not visible."
  - For "no": a plain statement of the obstacle, with no apology and no advice: "Can't read it, too blurry.", "Not in view.", "Too dark to tell.", "Screen washed out by glare.", "No question about the photo."
- unanswerable_reason: for "no" or "partly", the main obstacle. Use "not_applicable" for "yes".
- answer_type: what kind of answer the question calls for: "text_reading" (read words or numbers off something), "object_identity" (what is this), "color", "yes_no", "count", "description" (describe a scene, screen or person), or "other".
- evidence: one short sentence naming what in the photo supports your label (the text you read, the object you saw, or what blocks the view).
- crowd_verdict: "agrees" if your label matches the crowd majority, "refines" if you agree in substance but your answer is more specific or better worded, "overturns" if you contradict the crowd majority.

Two special cases:
- If the transcript is not a question about the photo (the person is talking to someone else, or reading out a homework question), answerable is "no" with reason "not_a_question", however readable the photo is.
- A frame that is almost uniformly black, white or blurred shows nothing. Do not answer colour or object questions from it; answerable is "no"."""

SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {"type": "string", "enum": ["yes", "partly", "no"]},
        "spoken_answer": {"type": "string"},
        "unanswerable_reason": {"type": "string", "enum": [
            "not_applicable", "too_blurry", "too_dark_or_glare", "not_in_frame",
            "not_a_question", "needs_outside_knowledge", "other"]},
        "answer_type": {"type": "string", "enum": [
            "text_reading", "object_identity", "color", "yes_no", "count", "description", "other"]},
        "evidence": {"type": "string"},
        "crowd_verdict": {"type": "string", "enum": ["agrees", "refines", "overturns"]},
    },
    "required": ["answerable", "spoken_answer", "unanswerable_reason", "answer_type", "evidence", "crowd_verdict"],
    "additionalProperties": False,
}


def tally(answers):
    counts = {}
    for a in answers:
        counts[a] = counts.get(a, 0) + 1
    return "; ".join(a + (" x%d" % n if n > 1 else "") for a, n in sorted(counts.items(), key=lambda kv: -kv[1]))


def encode(path, side=1024):
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((side, side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=60)
    return base64.b64encode(buf.getvalue()).decode()


def output_text(data):
    return " ".join(c.get("text", "") for o in data.get("output", []) if o.get("type") == "message"
                    for c in o.get("content", []) if c.get("type") == "output_text").strip()


def relabel(item, image_dir):
    question = " ".join(item["question"].split())
    crowd = tally([a["answer"] for a in item["answers"]])
    row = {"id": item["image"].split("_")[-1].split(".")[0], "image": item["image"], "question": question, "labeller": MODEL,
           "crowd": crowd, "dataset_answerable": item.get("answerable")}
    t0 = time.time()
    try:
        b64 = encode(os.path.join(image_dir, item["image"]))
    except Exception as e:
        row["error"] = "image: %s" % e
        return row
    payload = {
        "model": MODEL,
        "max_output_tokens": 2000,
        "instructions": INSTRUCTIONS,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": "Question as transcribed: %s\nCrowd answers from ten workers: %s" % (question, crowd)},
            {"type": "input_image", "image_url": "data:image/jpeg;base64," + b64}]}],
        "text": {"format": {"type": "json_schema", "name": "vizwiz_relabel", "schema": SCHEMA, "strict": True}},
    }
    for attempt in range(7):
        try:
            r = requests.post(dbx_auth.GATEWAY_URL, headers=dbx_auth.headers(), json=payload, timeout=180)
            row["http"] = r.status_code
            if r.status_code in (429, 500, 502, 503, 504, 529):
                row["error"] = r.text[:200]
                row["retries"] = attempt + 1
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
    row["seconds"] = round(time.time() - t0, 1)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split"), ap.add_argument("image_dir"), ap.add_argument("out")
    ap.add_argument("--workers", type=int, default=48)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--part", default="", help="i/n: take every n-th remaining photo starting at i")
    ap.add_argument("--reverse", action="store_true", help="work from the end of the list")
    ap.add_argument("--also-done", nargs="*", default=[], help="other label files whose photos to skip")
    args = ap.parse_args()

    items = json.load(open(args.split))
    done = set()
    for path in [args.out] + args.also_done:
        if not os.path.exists(path):
            continue
        for line in open(path):
            try:
                r = json.loads(line)
                if "answerable" in r:
                    done.add(r["image"])
            except Exception:
                pass
    todo = [x for x in items if x["image"] not in done]
    if args.reverse:
        todo = todo[::-1]
    if args.part:
        i, n = (int(v) for v in args.part.split("/"))
        todo = todo[i::n]
    if args.limit:
        todo = todo[:args.limit]
    print("%d photos, %d already labelled, %d to do, %d workers" % (len(items), len(done), len(todo), args.workers), flush=True)
    dbx_auth.headers()  # sign in once before the threads start

    lock = threading.Lock()
    stats = {"ok": 0, "err": 0, "retries": 0, "tin": 0, "tout": 0}
    t_start = time.time()
    with open(args.out, "a") as out, cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(relabel, x, args.image_dir) for x in todo]
        for n, fut in enumerate(cf.as_completed(futures), 1):
            row = fut.result()
            with lock:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                stats["ok" if "answerable" in row else "err"] += 1
                stats["retries"] += row.get("retries", 0)
                stats["tin"] += row.get("in_tok", 0)
                stats["tout"] += row.get("out_tok", 0)
            if n % 200 == 0 or n == len(futures):
                el = time.time() - t_start
                cost = stats["tin"] / 1e6 * PRICE_IN + stats["tout"] / 1e6 * PRICE_OUT
                print("%d/%d | %.1f/s | ok %d err %d retries %d | $%.2f | eta %.0f min" % (
                    n, len(futures), n / el, stats["ok"], stats["err"], stats["retries"], cost,
                    (len(futures) - n) / max(0.01, n / el) / 60), flush=True)
    print("DONE in %.0f s" % (time.time() - t_start), flush=True)


if __name__ == "__main__":
    main()
