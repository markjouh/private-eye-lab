"""The grading job on Databricks: grade every model answer that has no gpt-6.1-sol grade yet.

  uv run --with databricks-sdk dbx_job.py deploy     # upload the notebook, create or update the job
  uv run --with databricks-sdk dbx_job.py run        # run it, wait, then copy the new grades into the local cache
  uv run --with databricks-sdk dbx_job.py recheck 200  # re-grade 200 graded answers, save nothing, report how many grades repeat

Flow for a new model: run it over the test sets (eyes-cli or run_other_model.py), add it to CONFIGS in
dbx_lakehouse.py, `dbx_lakehouse.py eval` to load its answers, then `dbx_job.py run`. The job reads
workspace.eyes.eval_answers, calls gpt-6.1-sol through Unity Gateway for answers without a grade, and
merges the grades into workspace.eyes.eval_judgements; the dashboard reads the same tables.
"""
import json, os, sys, time

import dbx_auth

HERE = os.path.dirname(os.path.abspath(__file__))
JOB_FILE = os.path.join(HERE, "job_id.txt")
JOB_NAME = "private-eye-grade-new-answers"
CACHE = os.path.join(HERE, "eval", "lfm3_judgements_gpt-6_1-sol.json")

# The grading instructions and schema are the ones every grade so far was made with.
_src = open(os.path.join(HERE, "judge_eval_v2.py")).read()
RUBRIC = _src[_src.index('INSTRUCTIONS = """'):_src.index("def auth_headers")]

NOTEBOOK = '''# Databricks notebook source
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

__RUBRIC__

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
    user_text = ("Question: %s\\nCan the photo answer it: %s\\nReference answer: %s\\nOther acceptable answers: %s\\n"
                 "Reason if it cannot: %s\\nModel's answer: %s") % (
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
'''.replace("__RUBRIC__", RUBRIC.rstrip())


def deploy(w):
    from databricks.sdk.service.jobs import JobSettings, NotebookTask, Source, Task
    from databricks.sdk.service.workspace import ImportFormat, Language
    me = w.current_user.me().user_name
    folder = "/Workspace/Users/%s/private-eye" % me
    w.workspace.mkdirs(folder)
    path = folder + "/grade_new_answers"
    w.workspace.upload(path, NOTEBOOK.encode("utf-8"), format=ImportFormat.SOURCE, language=Language.PYTHON, overwrite=True)
    open(os.path.join(HERE, "grade_new_answers.py"), "w").write(NOTEBOOK)  # local copy of what is deployed
    tasks = [Task(task_key="grade_new_answers", description="Grade ungraded answers with gpt-6.1-sol through Unity Gateway",
                  notebook_task=NotebookTask(notebook_path=path, source=Source.WORKSPACE, base_parameters={"limit": "0", "workers": "16", "recheck": "0"}))]
    desc = "Private Eye: grades new on-device model answers against the reference labels (gpt-6.1-sol via Unity Gateway) and merges them into workspace.eyes.eval_judgements."
    if os.path.exists(JOB_FILE):
        job_id = int(open(JOB_FILE).read().strip())
        w.jobs.reset(job_id, JobSettings(name=JOB_NAME, description=desc, tasks=tasks, max_concurrent_runs=1))
    else:
        job_id = w.jobs.create(name=JOB_NAME, description=desc, tasks=tasks, max_concurrent_runs=1).job_id
        open(JOB_FILE, "w").write(str(job_id))
    print("job:", "%s/jobs/%s" % (dbx_auth.HOST, job_id), "| notebook:", path)
    return job_id


def pull_grades(w):
    """Copy grades made on Databricks into the local cache, so local summaries and a table rebuild agree."""
    sys.path.insert(0, HERE)
    import dbx_lakehouse as L
    import judge_local
    rows = L.sql("SELECT test_set, id, answer_norm, grade, declined, reason FROM workspace.eyes.eval_judgements WHERE judge = 'gpt-6.1-sol'", quiet=True)
    have = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    new = {}
    for test_set, qid, ans, grade, declined, reason in rows:
        key = "%s|%s|%s" % ("vizwiz" if test_set == "vizwiz500" else "phone", qid, ans or "")
        if key not in have:
            new[key] = {"grade": grade, "declined": str(declined).lower() == "true", "reason": reason}
    merged = judge_local.save(CACHE, new)
    print("%d grades in the table, %d new ones copied to the local cache (now %d)" % (len(rows), len(new), len(merged)))


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "deploy"
    w = dbx_auth.client()
    job_id = deploy(w)
    if what in ("run", "recheck"):
        n = sys.argv[2] if len(sys.argv) > 2 else ("200" if what == "recheck" else "0")
        run = w.jobs.run_now(job_id=job_id, notebook_params={"recheck": n, "limit": "0"} if what == "recheck" else {"limit": n, "recheck": "0"})
        print("run started:", "%s/jobs/%s/runs/%s" % (dbx_auth.HOST, job_id, run.run_id), flush=True)
        t0 = time.time()
        while True:
            r = w.jobs.get_run(run.run_id)
            life = r.state.life_cycle_state.value if r.state and r.state.life_cycle_state else "?"
            if life in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
                break
            time.sleep(15)
        result = r.state.result_state.value if r.state.result_state else life
        out = w.jobs.get_run_output(r.tasks[0].run_id)
        print("run %s in %.0f s | result: %s | %s" % (result, time.time() - t0, out.notebook_output.result if out.notebook_output else None,
                                                     (out.error or "")[:500]))
        if result == "SUCCESS" and what == "run":
            pull_grades(w)
