# Databricks notebook source
# VizWiz test set: relabel 500 validation photos through the Unity Gateway provider workspace.default.openai.
# Reads vizwiz_eval_chunk_*.json from this folder, writes vizwiz_eval_labels.json (no pixels) next to it.
# Safe to re-run: photos that already have a label are skipped.

import concurrent.futures as cf
import glob, json, os, time
import requests
from databricks.sdk import WorkspaceClient

HOST = "https://dbc-5bd2d642-3eac.cloud.databricks.com"
URL = HOST + "/ai-gateway/openai/v1/responses"
PROVIDER = "workspace.default.openai"
MODEL = "gpt-6.1-sol"
PRICE_IN, PRICE_OUT = 2.00, 10.00  # listed price per million tokens
LABEL_FILE = "vizwiz_eval_labels.json"
WORKERS = 8

def notebook_dir():
    path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    return "/Workspace" + os.path.dirname(path)

BASE = "." if glob.glob("vizwiz_eval_chunk_*.json") else notebook_dir()
items = []
for path in sorted(glob.glob(os.path.join(BASE, "vizwiz_eval_chunk_*.json"))):
    part = json.load(open(path))
    items.extend(part)
    print(os.path.basename(path), len(part))
label_path = os.path.join(BASE, LABEL_FILE)
labels = {r["id"]: r for r in json.load(open(label_path))} if os.path.exists(label_path) else {}
print(len(items), "photos loaded;", len(labels), "already labelled")

# COMMAND ----------

INSTRUCTIONS = """You are helping build a trustworthy test set for a phone app that answers spoken questions from blind people about what their camera sees.

Each item comes from the VizWiz dataset: a photo taken by a blind person, the question they asked aloud (transcribed; sometimes rambling, sometimes not a question at all), and short answers from ten crowd workers. The crowd answers are noisy. Workers often wrote "unanswerable" when the answer was readable with some effort, they disagree on wording, and a few typed nonsense. The answers were also stored lowercased with punctuation and small words removed.

Your job is to look at the photo yourself and decide the correct reference label. Use the crowd answers as hints about where to look, but only accept what you can verify in the photo. If the crowd says something you cannot see, do not repeat it. If you can read or see the answer and the crowd said "unanswerable", overturn them. Photos are often rotated, blurred or badly framed, so mentally rotate the image before reading text. Do not guess text you cannot actually read.

Fields to return:
- answerable: "yes" if the photo shows enough to answer the question as asked. "partly" if the photo answers only part of what was asked, or only at a coarser level: the brand but not the flavour, a site's name but not its address, "a bottle" but not what is in it, a screen you can describe but whose text you cannot read. "no" if the needed information is not visible at all.
- reference_answer: the answer a careful sighted friend would give, in natural words, at most 12 words. For "partly", give the part that can be answered. For "no", leave it empty. When the answer is text in the photo, give it as printed there, including small words; the crowd's wording had small words stripped, so do not copy it.
- acceptable_answers: up to five other answers that should also count as correct, such as shorter, more general or differently worded versions of the reference answer. Do not list an answer so general that it would not help the person. Empty for "no".
- unanswerable_reason: for "no" or "partly", the main obstacle. Use "not_applicable" for "yes".
- answer_type: what kind of answer the question calls for: "text_reading" (read words or numbers off something), "object_identity" (what is this), "color", "yes_no", "count", "description" (describe a scene, screen or person), or "other".
- evidence: one short sentence naming what in the photo supports your label (the text you read, the object you saw, or what blocks the view), so a human reviewer can check you quickly.
- crowd_verdict: "agrees" if your label matches the crowd majority, "refines" if you agree in substance but your answer is more specific or better worded, "overturns" if you contradict the crowd majority.

Two special cases:
- If the transcript is not a question about the photo (the person is talking to someone else, or reading out a homework question), answerable is "no" with reason "not_a_question", however readable the photo is.
- A frame that is almost uniformly black, white or blurred shows nothing. Do not answer colour or object questions from it; answerable is "no"."""

SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {"type": "string", "enum": ["yes", "partly", "no"]},
        "reference_answer": {"type": "string"},
        "acceptable_answers": {"type": "array", "items": {"type": "string"}},
        "unanswerable_reason": {"type": "string", "enum": [
            "not_applicable", "too_blurry", "too_dark_or_glare", "not_in_frame",
            "not_a_question", "needs_outside_knowledge", "other"]},
        "answer_type": {"type": "string", "enum": [
            "text_reading", "object_identity", "color", "yes_no", "count", "description", "other"]},
        "evidence": {"type": "string"},
        "crowd_verdict": {"type": "string", "enum": ["agrees", "refines", "overturns"]},
    },
    "required": ["answerable", "reference_answer", "acceptable_answers", "unanswerable_reason",
                 "answer_type", "evidence", "crowd_verdict"],
    "additionalProperties": False,
}

def tally(answers):
    counts = {}
    for a in answers:
        counts[a] = counts.get(a, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: -kv[1])
    return "; ".join(a + (" x%d" % n if n > 1 else "") for a, n in ordered)

def auth_headers():
    h = dict(WorkspaceClient().config.authenticate())  # the notebook's own sign-in; never printed
    h["Content-Type"] = "application/json"
    h["Databricks-Model-Provider-Service"] = PROVIDER
    return h

def output_text(data):
    return " ".join(c.get("text", "") for o in data.get("output", []) if o.get("type") == "message"
                    for c in o.get("content", []) if c.get("type") == "output_text").strip()

def relabel(item):
    user_text = "Question as transcribed: %s\nCrowd answers from ten workers: %s" % (
        item["question"], tally(item["crowd_answers"]))
    payload = {
        "model": MODEL,
        "max_output_tokens": 2000,
        "instructions": INSTRUCTIONS,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": user_text},
            {"type": "input_image", "image_url": "data:image/jpeg;base64," + item["image_b64"]}]}],
        "text": {"format": {"type": "json_schema", "name": "vizwiz_relabel", "schema": SCHEMA, "strict": True}},
    }
    row = {"id": item["id"], "image": item["image"], "question": item["question"],
           "crowd": tally(item["crowd_answers"]), "dataset_answerable": item["dataset_answerable"]}
    t0 = time.time()
    for attempt in range(5):
        try:
            r = requests.post(URL, headers=auth_headers(), json=payload, timeout=180)
            row["http"] = r.status_code
            if r.status_code in (429, 500, 502, 503, 504):
                row["error"] = r.text[:300]
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code != 200:
                row["error"] = r.text[:400]
                break
            data = r.json()
            text = output_text(data)
            row.update(json.loads(text[text.find("{"):text.rfind("}") + 1]))
            usage = data.get("usage") or {}
            row["in_tok"], row["out_tok"] = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
            row.pop("error", None)
            break
        except Exception as e:
            row["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
            time.sleep(2)
    row["seconds"] = round(time.time() - t0, 1)
    return row

todo = [it for it in items if it["id"] not in labels or "answerable" not in labels[it["id"]]]
print(len(todo), "to label")
t_start = time.time()
for start in range(0, len(todo), 100):
    batch = todo[start:start + 100]
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for row in pool.map(relabel, batch):
            labels[row["id"]] = row
    json.dump([labels[it["id"]] for it in items if it["id"] in labels], open(label_path, "w"), indent=1)
    print("labelled %d of %d, %.0f s" % (min(start + 100, len(todo)), len(todo), time.time() - t_start))

# COMMAND ----------

from collections import Counter
rows = [labels[it["id"]] for it in items if it["id"] in labels]
ok = [r for r in rows if "answerable" in r]
tin, tout = sum(r.get("in_tok", 0) for r in rows), sum(r.get("out_tok", 0) for r in rows)
print("SUMMARY ok=%d of %d | input_tokens=%d output_tokens=%d | est_cost=$%.2f" % (
    len(ok), len(items), tin, tout, tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT))
print("ERRORS", Counter(str(r.get("http")) + " " + r.get("error", "")[:80] for r in rows if "answerable" not in r).most_common(5))
print("BY_DATASET_FLAG", {flag: dict(Counter(r["answerable"] for r in ok if r["dataset_answerable"] == flag)) for flag in (1, 0)})
print("CROWD_VERDICT", dict(Counter(r["crowd_verdict"] for r in ok)))
print("ANSWER_TYPE", dict(Counter(r["answer_type"] for r in ok)))
print("REASON", dict(Counter(r["unanswerable_reason"] for r in ok if r["answerable"] != "yes")))
for r in ok[:12]:
    print("ROW " + json.dumps({k: r.get(k) for k in ("id", "question", "crowd", "dataset_answerable", "answerable",
                                                    "reference_answer", "answer_type", "crowd_verdict")}))
