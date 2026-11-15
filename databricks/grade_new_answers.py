# Databricks notebook source
# MAGIC %md
# MAGIC # Grade new model answers
# MAGIC Finds every answer in `workspace.eyes.eval_answers` that has no grade from **gpt-6.1-sol** yet, grades it
# MAGIC through Unity Gateway (provider `workspace.default.openai`), and merges the grades into
# MAGIC `workspace.eyes.eval_judgements`. Text only: the judge sees the question, the reference label and the answer.
# MAGIC Safe to re-run; it only grades what is missing.

# COMMAND ----------

import concurrent.futures as cf
import json, random, time
import requests
from databricks.sdk import WorkspaceClient

dbutils.widgets.text("limit", "0", "Grade at most (0 = all)")
dbutils.widgets.text("workers", "16", "Parallel calls")
dbutils.widgets.text("recheck", "0", "Consistency check: re-grade this many graded answers, save nothing")
RECHECK = int(dbutils.widgets.get("recheck") or 0)
LIMIT = int(dbutils.widgets.get("limit") or 0)
WORKERS = int(dbutils.widgets.get("workers") or 16)
S = "workspace.eyes"
JUDGE = "gpt-6.1-sol"   # the strongest model in the provider; the only judge we report
PROVIDER = "workspace.default.openai"
w = WorkspaceClient()
URL = w.config.host.rstrip("/") + "/ai-gateway/openai/v1/responses"

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

# COMMAND ----------

# Normal run: answers with no grade yet. Consistency check: a fixed pseudo-random sample of graded answers.
pick = (f"JOIN (SELECT * FROM {S}.eval_judgements WHERE judge = '{JUDGE}') j" if RECHECK else
        f"LEFT ANTI JOIN (SELECT * FROM {S}.eval_judgements WHERE judge = '{JUDGE}') j")
todo = spark.sql(f"""
SELECT a.test_set, a.id, a.answer_norm, min(a.answer) AS answer, count(*) AS used_by,
       {"any_value(j.grade)" if RECHECK else "CAST(NULL AS STRING)"} AS stored_grade,
       any_value(l.question) AS question, any_value(l.answerable) AS answerable,
       any_value(l.reference_answer) AS reference_answer, any_value(l.acceptable_answers) AS acceptable_answers,
       any_value(l.unanswerable_reason) AS unanswerable_reason
FROM {S}.eval_answers a
JOIN {S}.eval_labels l ON l.test_set = a.test_set AND l.id = a.id
{pick}
  ON j.test_set = a.test_set AND j.id = a.id AND j.answer_norm = a.answer_norm
GROUP BY a.test_set, a.id, a.answer_norm
ORDER BY {"xxhash64(a.id, a.answer_norm)" if RECHECK else "a.test_set, a.id, a.answer_norm"}""").collect()
if RECHECK or LIMIT:
    todo = todo[:RECHECK or LIMIT]
print(len(todo), "distinct answers to", "re-grade as a consistency check" if RECHECK else "grade")

# COMMAND ----------

import threading
_auth = {"at": 0.0, "headers": None, "lock": threading.Lock()}

def headers():
    # The job's own sign-in; never printed. Fetched once and reused for ten minutes: asking for it on
    # every call made the workers queue behind each other (about one call a second).
    with _auth["lock"]:
        if _auth["headers"] is None or time.time() - _auth["at"] > 600:
            h = dict(w.config.authenticate())
            h["Content-Type"] = "application/json"
            h["Databricks-Model-Provider-Service"] = PROVIDER
            _auth["headers"], _auth["at"] = h, time.time()
        return _auth["headers"]

def output_text(data):
    return " ".join(c.get("text", "") for o in data.get("output", []) if o.get("type") == "message"
                    for c in o.get("content", []) if c.get("type") == "output_text").strip()

def grade(r):
    answer = r["answer"] or ""
    user_text = ("Question: %s\nCan the photo answer it: %s\nReference answer: %s\nOther acceptable answers: %s\n"
                 "Reason if it cannot: %s\nModel's answer: %s") % (
        r["question"], r["answerable"], r["reference_answer"] or "(none)",
        "; ".join(r["acceptable_answers"] or []) or "(none)",
        r["unanswerable_reason"] or "not_applicable", answer if answer.strip() else "(said nothing)")
    payload = {"model": JUDGE, "max_output_tokens": 1000, "instructions": INSTRUCTIONS,
               "input": [{"role": "user", "content": [{"type": "input_text", "text": user_text}]}],
               "text": {"format": {"type": "json_schema", "name": "grade", "schema": SCHEMA, "strict": True}}}
    out, usage = {}, (0, 0)
    for attempt in range(8):
        try:
            resp = requests.post(URL, headers=headers(), json=payload, timeout=120)
            if resp.status_code in (401, 403):
                _auth["headers"] = None  # sign-in expired: fetch a new one and try again
                out = {"error": "%d %s" % (resp.status_code, resp.text[:200])}
                continue
            if resp.status_code in (429, 500, 502, 503, 504, 529):
                out = {"error": "%d %s" % (resp.status_code, resp.text[:200])}
                time.sleep(min(40, 2 ** attempt + random.random() * 2))
                continue
            if resp.status_code != 200:
                out = {"error": "%d %s" % (resp.status_code, resp.text[:300])}
                break
            data = resp.json()
            text = output_text(data)
            out = json.loads(text[text.find("{"):text.rfind("}") + 1])
            u = data.get("usage") or {}
            usage = (u.get("input_tokens", 0), u.get("output_tokens", 0))
            break
        except Exception as e:
            out = {"error": "%s: %s" % (type(e).__name__, str(e)[:200])}
            time.sleep(2)
    return r, out, usage

t0 = time.time()
graded, failed, tok_in, tok_out, same = [], [], 0, 0, 0
with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
    for n, (r, out, usage) in enumerate(pool.map(grade, todo), 1):
        tok_in += usage[0]; tok_out += usage[1]
        if out.get("grade") in ("right", "partly", "wrong"):
            graded.append((r["test_set"], r["id"], r["answer_norm"], out["grade"], bool(out.get("declined")), out.get("reason"), JUDGE))
            same += out["grade"] == r["stored_grade"]
        else:
            failed.append((r["test_set"], r["id"], str(out.get("error"))[:200]))
        if n % 250 == 0:
            print(n, "graded in %.0f s" % (time.time() - t0))
print(len(graded), "graded,", len(failed), "failed, %.0f s" % (time.time() - t0), failed[:3])

# COMMAND ----------

if RECHECK:
    dbutils.notebook.exit(json.dumps({"rechecked": len(graded), "same_grade": same, "failed": len(failed), "seconds": round(time.time() - t0),
                                      "calls_per_second": round(len(graded) / max(1, time.time() - t0), 1), "judge": JUDGE, "saved": False}))
if graded:
    df = spark.createDataFrame(graded, "test_set string, id string, answer_norm string, grade string, declined boolean, reason string, judge string")
    df.createOrReplaceTempView("new_grades")
    spark.sql(f"""MERGE INTO {S}.eval_judgements t USING new_grades s
ON t.test_set = s.test_set AND t.id = s.id AND t.answer_norm = s.answer_norm
WHEN MATCHED THEN UPDATE SET t.grade = s.grade, t.declined = s.declined, t.reason = s.reason, t.judge = s.judge
WHEN NOT MATCHED THEN INSERT (test_set, id, answer_norm, grade, declined, reason, judge)
  VALUES (s.test_set, s.id, s.answer_norm, s.grade, s.declined, s.reason, s.judge)""")

summary = spark.sql(f"SELECT label, right_answers, partly, wrong, invented_answers, ungraded FROM {S}.eval_summary WHERE test_set = 'vizwiz500' ORDER BY sort_order")
display(summary)
dbutils.notebook.exit(json.dumps({"graded": len(graded), "failed": len(failed), "seconds": round(time.time() - t0),
                                  "input_tokens": tok_in, "output_tokens": tok_out, "judge": JUDGE}))
