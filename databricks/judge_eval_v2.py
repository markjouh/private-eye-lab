# Databricks notebook source
# Grade LFM3 answers against reference labels, text only (no photos are sent).
# Reads lfm3_answers_v2.json (uploaded: answers per configuration, plus the phone-frame labels) and
# vizwiz_eval_labels.json (written by relabel_eval). Writes lfm3_judgements.json.
# Safe to re-run: judgements already made are reused.

import concurrent.futures as cf
import json, math, os, random, time
from collections import Counter, defaultdict
import requests
from databricks.sdk import WorkspaceClient

HOST = "https://dbc-5bd2d642-3eac.cloud.databricks.com"
URL = HOST + "/ai-gateway/openai/v1/responses"
PROVIDER = "workspace.default.openai"
MODEL = "gpt-6.1-terra"
PRICE_IN, PRICE_OUT = 1.00, 5.00  # listed price per million tokens
WORKERS = 12

def notebook_dir():
    path = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    return "/Workspace" + os.path.dirname(path)

ANSWERS_FILE = "lfm3_answers_v2.json"
BASE = "." if os.path.exists(ANSWERS_FILE) else notebook_dir()
answers = json.load(open(os.path.join(BASE, ANSWERS_FILE)))
labels = {"vizwiz": {r["id"]: r for r in json.load(open(os.path.join(BASE, "vizwiz_eval_labels.json"))) if "answerable" in r},
          "phone": {r["id"]: r for r in answers["phone_labels"]}}
judge_path = os.path.join(BASE, "lfm3_judgements.json")
cache = json.load(open(judge_path)) if os.path.exists(judge_path) else {}
print({s: len(labels[s]) for s in labels}, "labels;", {s: {c: len(a) for c, a in answers[s].items()} for s in ("vizwiz", "phone")})
print(len(cache), "judgements already made")

# COMMAND ----------

INSTRUCTIONS = """You are grading answers from a small vision model that runs on a phone and speaks short answers to blind people. For each item you get the question the person asked aloud, a reference label written by a careful reviewer who saw the photo, and the model's answer. You do not see the photo, so grade against the reference label.

The reference label says whether the photo can answer the question ("yes", "partly" or "no"), gives a reference answer and other acceptable answers, and for photos that cannot answer it, the reason.

Give one grade:
- "right": the answer gives the person the correct information. It means the same as the reference answer or one of the acceptable answers. Wording, word order, capitals, a missing brand that the acceptable answers also leave out, and harmless extra words do not matter. For a yes/no question the yes or no must be correct.
- "partly": the answer is true as far as it goes but is less specific than every acceptable answer (for example "a can" when the least specific acceptable answer is "energy drink can"), or it gets the main thing right and adds a wrong detail, or it names something else that the reference says is in the photo rather than the main thing.
- "wrong": the answer names a different thing, gives text or a number that differs from the reference, gets a yes/no wrong, or does not answer the question.

If the reference says the photo cannot answer the question ("no"): "right" when the answer declines or says it cannot tell, read or see it; "wrong" when it gives a specific answer anyway, because that answer is invented; "partly" when it only describes something vague without claiming the specific thing asked.

If the reference says the photo can answer the question and the model declines or says it cannot tell, the grade is "wrong".

Also return "declined": true when the model's answer declines, says it cannot tell, read or see, or says nothing is visible; false otherwise. And "reason": at most twelve words on why you chose the grade."""

SCHEMA = {
    "type": "object",
    "properties": {
        "grade": {"type": "string", "enum": ["right", "partly", "wrong"]},
        "declined": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["grade", "declined", "reason"],
    "additionalProperties": False,
}

def auth_headers():
    h = dict(WorkspaceClient().config.authenticate())  # the notebook's own sign-in; never printed
    h["Content-Type"] = "application/json"
    h["Databricks-Model-Provider-Service"] = PROVIDER
    return h

def output_text(data):
    return " ".join(c.get("text", "") for o in data.get("output", []) if o.get("type") == "message"
                    for c in o.get("content", []) if c.get("type") == "output_text").strip()

def key_of(source, qid, answer):
    return "%s|%s|%s" % (source, qid, " ".join(answer.lower().split()))

def judge(job):
    key, lab, answer = job
    user_text = ("Question: %s\nCan the photo answer it: %s\nReference answer: %s\nOther acceptable answers: %s\n"
                 "Reason if it cannot: %s\nModel's answer: %s") % (
        lab["question"], lab["answerable"], lab.get("reference_answer") or "(none)",
        "; ".join(lab.get("acceptable_answers") or []) or "(none)",
        lab.get("unanswerable_reason", "not_applicable"), answer if answer.strip() else "(said nothing)")
    payload = {
        "model": MODEL,
        "max_output_tokens": 1000,
        "instructions": INSTRUCTIONS,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": user_text}]}],
        "text": {"format": {"type": "json_schema", "name": "grade", "schema": SCHEMA, "strict": True}},
    }
    out = {}
    for attempt in range(5):
        try:
            r = requests.post(URL, headers=auth_headers(), json=payload, timeout=120)
            if r.status_code in (429, 500, 502, 503, 504):
                out = {"error": "%d %s" % (r.status_code, r.text[:200])}
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code != 200:
                out = {"error": "%d %s" % (r.status_code, r.text[:300])}
                break
            data = r.json()
            text = output_text(data)
            out = json.loads(text[text.find("{"):text.rfind("}") + 1])
            usage = data.get("usage") or {}
            out["in_tok"], out["out_tok"] = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
            break
        except Exception as e:
            out = {"error": "%s: %s" % (type(e).__name__, str(e)[:200])}
            time.sleep(2)
    return key, out

jobs = {}
for source in ("vizwiz", "phone"):
    for config, by_id in answers[source].items():
        for qid, answer in by_id.items():
            if qid not in labels[source]:
                continue
            key = key_of(source, qid, answer)
            if key not in cache or "grade" not in cache[key]:
                jobs[key] = (key, labels[source][qid], answer)
jobs = list(jobs.values())
print(len(jobs), "new judgements to make")
t_start = time.time()
for start in range(0, len(jobs), 400):
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for key, out in pool.map(judge, jobs[start:start + 400]):
            cache[key] = out
    json.dump(cache, open(judge_path, "w"))
    print("judged %d of %d, %.0f s" % (min(start + 400, len(jobs)), len(jobs), time.time() - t_start))
tin, tout = sum(v.get("in_tok", 0) for v in cache.values()), sum(v.get("out_tok", 0) for v in cache.values())
print("JUDGE_COST input_tokens=%d output_tokens=%d est=$%.2f errors=%d" % (
    tin, tout, tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT, sum(1 for v in cache.values() if "grade" not in v)))

# COMMAND ----------

RANK = {"wrong": 0, "partly": 1, "right": 2}
LETTER = {"right": "R", "partly": "P", "wrong": "W", None: "?"}

def graded(source, config):
    rows = []
    for qid, lab in labels[source].items():
        answer = answers[source][config].get(qid)
        if answer is None:
            continue
        j = cache.get(key_of(source, qid, answer), {})
        rows.append((qid, lab, answer, j.get("grade"), j.get("declined")))
    return rows

def sign_test(better, worse):
    n, k = better + worse, min(better, worse)
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)

for source in ("vizwiz", "phone"):
    configs = list(answers[source].keys())
    if not configs:
        continue
    base = {qid: g for qid, _, _, g, _ in graded(source, configs[0])}
    print("\n===== %s (%d items) =====" % (source, len(labels[source])))
    for config in configs:
        rows = [r for r in graded(source, config) if r[3]]
        n = len(rows)
        c = Counter(r[3] for r in rows)
        can = [r for r in rows if r[1]["answerable"] != "no"]
        cannot = [r for r in rows if r[1]["answerable"] == "no"]
        words = sum(len(r[2].split()) for r in rows) / max(1, n)
        better = sum(1 for r in rows if r[0] in base and base[r[0]] and RANK[r[3]] > RANK[base[r[0]]])
        worse = sum(1 for r in rows if r[0] in base and base[r[0]] and RANK[r[3]] < RANK[base[r[0]]])
        print("CONFIG %-14s n=%d right=%d partly=%d wrong=%d | right%%=%.1f score%%=%.1f | answerable: right %d/%d (%.1f%%), declined %d | not answerable: declined-right %d/%d (%.1f%%), invented %d | words %.1f | vs %s: better %d, worse %d, p=%.3f" % (
            config, n, c["right"], c["partly"], c["wrong"], 100 * c["right"] / max(1, n),
            100 * (c["right"] + 0.5 * c["partly"]) / max(1, n),
            sum(1 for r in can if r[3] == "right"), len(can), 100 * sum(1 for r in can if r[3] == "right") / max(1, len(can)),
            sum(1 for r in can if r[4]),
            sum(1 for r in cannot if r[3] == "right"), len(cannot), 100 * sum(1 for r in cannot if r[3] == "right") / max(1, len(cannot)),
            sum(1 for r in cannot if r[3] == "wrong"), words, configs[0], better, worse, sign_test(better, worse)))
    print("--- right%% by answer type (answerable photos only): type n " + " ".join(configs))
    types = Counter(lab.get("answer_type", "other") for lab in labels[source].values() if lab["answerable"] != "no")
    for t, tn in types.most_common():
        cells = []
        for config in configs:
            rows = [r for r in graded(source, config) if r[3] and r[1]["answerable"] != "no" and r[1].get("answer_type", "other") == t]
            cells.append("%.0f" % (100 * sum(1 for r in rows if r[3] == "right") / max(1, len(rows))))
        print("TYPE %-16s %3d  %s" % (t, tn, "  ".join(cells)))
    for config in configs:
        order = sorted(labels[source])
        got = {qid: g for qid, _, _, g, _ in graded(source, config)}
        print("GRADES %s %s" % (config, "".join(LETTER[got.get(q)] for q in order)))

# COMMAND ----------

random.seed(7)
first = list(answers["vizwiz"].keys())[0]
rows = [r for r in graded("vizwiz", first) if r[3]]
print("SAMPLE of judgements for", first)
for qid, lab, answer, g, d in random.sample(rows, min(30, len(rows))):
    j = cache[key_of("vizwiz", qid, answer)]
    print("S %s | Q: %s | ref(%s): %s | LFM3: %s | %s%s | %s" % (
        qid, lab["question"][:60], lab["answerable"], (lab.get("reference_answer") or "-")[:60], answer[:60],
        g, " declined" if d else "", j.get("reason", "")))
print("\nPHONE, every item, first config and every other config's answer")
pconfigs = list(answers["phone"].keys())
for qid in sorted(labels["phone"]):
    lab = labels["phone"][qid]
    cells = []
    for config in pconfigs:
        a = answers["phone"][config].get(qid, "")
        cells.append("%s=%s[%s]" % (config[:1], a[:40], LETTER[cache.get(key_of("phone", qid, a), {}).get("grade")]))
    print("P %s | %s | ref: %s | %s" % (qid, lab["question"][:40], (lab.get("reference_answer") or "(no answer)")[:40], " | ".join(cells)))
