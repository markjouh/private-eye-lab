# Databricks notebook source
# VizWiz relabel pilot: 20 photos through the Unity Gateway provider workspace.default.openai.
# For each photo the model sees the image, the question and the ten crowd answers, and returns
# a reference label. Results are printed, shown as a table and saved next to this notebook.

import concurrent.futures as cf
import json, os, time
import requests
from databricks.sdk import WorkspaceClient

HOST = "https://dbc-5bd2d642-3eac.cloud.databricks.com"
URL = HOST + "/ai-gateway/openai/v1/responses"
PROVIDER = "workspace.default.openai"
MODEL = "gpt-6.1-sol"
PRICE_IN, PRICE_OUT = 2.00, 10.00  # listed price per million tokens
DATA_FILE = "vizwiz_pilot_data.json"
RESULT_FILE = "relabel_pilot_results.json"

def notebook_dir():
    path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    return "/Workspace" + os.path.dirname(path)

data_path = DATA_FILE if os.path.exists(DATA_FILE) else os.path.join(notebook_dir(), DATA_FILE)
items = json.load(open(data_path))
print(len(items), "items loaded from", data_path)

# COMMAND ----------

INSTRUCTIONS = """You are helping build a trustworthy test set for a phone app that answers spoken questions from blind people about what their camera sees.

Each item comes from the VizWiz dataset: a photo taken by a blind person, the question they asked aloud (transcribed; sometimes rambling, sometimes not a question at all), and short answers from ten crowd workers. The crowd answers are noisy. Workers often wrote "unanswerable" when the answer was readable with some effort, they disagree on wording, and a few typed nonsense. The answers were also stored lowercased with punctuation and small words removed.

Your job is to look at the photo yourself and decide the correct reference label. Use the crowd answers as hints about where to look, but only accept what you can verify in the photo. If the crowd says something you cannot see, do not repeat it. If you can read or see the answer and the crowd said "unanswerable", overturn them. Photos are often rotated, blurred or badly framed, so mentally rotate the image before reading text. Do not guess text you cannot actually read.

Fields to return:
- answerable: "yes" if the photo shows enough to answer the question as asked. "partly" if it supports a useful partial answer but not the full one (for example the brand is readable but not the flavour that was asked about). "no" if the needed information is not visible, or the transcript is not a question about the photo.
- reference_answer: the answer a careful sighted friend would give, in natural words, at most 12 words. For "partly", give the part that can be answered. For "no", leave it empty.
- acceptable_answers: up to five other answers that should also count as correct, such as shorter, more general or differently worded versions of the reference answer. Empty for "no".
- unanswerable_reason: for "no" or "partly", the main obstacle. Use "not_applicable" for "yes".
- evidence: one short sentence naming what in the photo supports your label (the text you read, the object you saw, or what blocks the view), so a human reviewer can check you quickly.
- crowd_verdict: "agrees" if your label matches the crowd majority, "refines" if you agree in substance but your answer is more specific or better worded, "overturns" if you contradict the crowd majority."""

SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {"type": "string", "enum": ["yes", "partly", "no"]},
        "reference_answer": {"type": "string"},
        "acceptable_answers": {"type": "array", "items": {"type": "string"}},
        "unanswerable_reason": {"type": "string", "enum": [
            "not_applicable", "too_blurry", "too_dark_or_glare", "not_in_frame",
            "not_a_question", "needs_outside_knowledge", "other"]},
        "evidence": {"type": "string"},
        "crowd_verdict": {"type": "string", "enum": ["agrees", "refines", "overturns"]},
    },
    "required": ["answerable", "reference_answer", "acceptable_answers",
                 "unanswerable_reason", "evidence", "crowd_verdict"],
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
    image = {"type": "input_image", "image_url": "data:image/jpeg;base64," + item["image_b64"]}
    payload = {
        "model": MODEL,
        "max_output_tokens": 2000,
        "instructions": INSTRUCTIONS,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": user_text}, image]}],
        "text": {"format": {"type": "json_schema", "name": "vizwiz_relabel", "schema": SCHEMA, "strict": True}},
    }
    row = {"id": item["id"], "question": item["question"], "crowd": tally(item["crowd_answers"]),
           "dataset_answerable": item["dataset_answerable"], "structured": True}
    t0 = time.time()
    try:
        r = requests.post(URL, headers=auth_headers(), json=payload, timeout=180)
        if r.status_code == 400:  # retry once without the structured-output setting
            row["structured"] = False
            row["first_error"] = r.text[:300]
            payload.pop("text")
            payload["instructions"] = INSTRUCTIONS + "\n\nReturn only a JSON object with exactly those six fields."
            r = requests.post(URL, headers=auth_headers(), json=payload, timeout=180)
        row["http"] = r.status_code
        if r.status_code != 200:
            row["error"] = r.text[:500]
            return row
        data = r.json()
        text = output_text(data)
        start, end = text.find("{"), text.rfind("}")
        row.update(json.loads(text[start:end + 1]))
        usage = data.get("usage") or {}
        row["in_tok"], row["out_tok"] = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    except Exception as e:
        row["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
    row["seconds"] = round(time.time() - t0, 1)
    return row

t_start = time.time()
with cf.ThreadPoolExecutor(max_workers=4) as pool:
    rows = list(pool.map(relabel, items))
wall = time.time() - t_start

# COMMAND ----------

ok = [r for r in rows if "answerable" in r]
tin, tout = sum(r.get("in_tok", 0) for r in rows), sum(r.get("out_tok", 0) for r in rows)
print("SUMMARY ok=%d of %d | wall=%.0fs | input_tokens=%d output_tokens=%d | est_cost=$%.3f | structured=%d" % (
    len(ok), len(rows), wall, tin, tout, tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT,
    sum(1 for r in rows if r.get("structured"))))
for r in rows:
    print("ROW " + json.dumps({k: r.get(k) for k in (
        "id", "dataset_answerable", "answerable", "reference_answer", "acceptable_answers",
        "unanswerable_reason", "crowd_verdict", "evidence", "in_tok", "out_tok", "seconds", "http", "error")}))

try:
    out_path = os.path.join(os.path.dirname(data_path) or ".", RESULT_FILE)
    json.dump(rows, open(out_path, "w"), indent=1)
    print("saved", out_path)
except Exception as e:
    print("could not save results file:", type(e).__name__, e)

# COMMAND ----------

import pandas as pd
display(pd.DataFrame(rows)[[c for c in ("id", "question", "crowd", "dataset_answerable", "answerable",
                                         "reference_answer", "unanswerable_reason", "crowd_verdict", "evidence")
                             if c in pd.DataFrame(rows).columns]])
