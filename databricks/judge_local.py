"""Grade LFM3 answers from this Mac (text only), using the same instructions as the judge notebook.

Usage:
  uv run --with databricks-sdk --with requests judge_local.py <eval dir> NAME [NAME ...]
For each NAME it reads <eval dir>/runs/NAME.tsv (VizWiz 500) and runs/phone_NAME.tsv (phone frames),
grades them against the reference labels, and prints the same summary lines as the notebook.
The first NAME is the baseline for the better/worse comparison.

Labels for the 500 and the shared judgement cache live in the Databricks workspace; they are
downloaded once into <eval dir> (vizwiz_eval_labels.json, lfm3_judgements.json) and the cache is
kept up to date locally.
"""
import concurrent.futures as cf
import io, json, math, os, random, re, sys, time
from collections import Counter

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx_auth

# The judge is the strongest model available through the gateway. (The first rounds used the cheaper
# gpt-6.1-terra; those grades are kept in lfm3_judgements.json for the record but are not reported.)
MODEL = os.environ.get("JUDGE_MODEL", "gpt-6.1-sol")
WORKERS = 24
HERE = os.path.dirname(os.path.abspath(__file__))

# Reuse the notebook's grading instructions and schema verbatim.
_src = open(os.path.join(HERE, "judge_eval_v2.py")).read()
_block = _src[_src.index('INSTRUCTIONS = """'):_src.index("def auth_headers")]
exec(_block)  # defines INSTRUCTIONS and SCHEMA


def fetch(ev, name):
    path = os.path.join(ev, name)
    if not os.path.exists(path):
        w = dbx_auth.client()
        home = "/Users/" + w.current_user.me().user_name
        with w.workspace.download(home + "/" + name) as f:
            open(path, "wb").write(f.read())
        print("downloaded", name, os.path.getsize(path), "bytes")
    return json.load(open(path))


def read_tsv(path):
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                out[parts[0]] = parts[2].strip()
    return out


def key_of(source, qid, answer):
    return "%s|%s|%s" % (source, qid, " ".join(answer.lower().split()))


def output_text(data):
    return " ".join(c.get("text", "") for o in data.get("output", []) if o.get("type") == "message"
                    for c in o.get("content", []) if c.get("type") == "output_text").strip()


def judge(job):
    key, lab, answer = job
    user_text = ("Question: %s\nCan the photo answer it: %s\nReference answer: %s\nOther acceptable answers: %s\n"
                 "Reason if it cannot: %s\nModel's answer: %s") % (
        lab["question"], lab["answerable"], lab.get("reference_answer") or "(none)",
        "; ".join(lab.get("acceptable_answers") or []) or "(none)",
        lab.get("unanswerable_reason", "not_applicable"), answer if answer.strip() else "(said nothing)")
    payload = {"model": MODEL, "max_output_tokens": 1000, "instructions": INSTRUCTIONS,
               "input": [{"role": "user", "content": [{"type": "input_text", "text": user_text}]}],
               "text": {"format": {"type": "json_schema", "name": "grade", "schema": SCHEMA, "strict": True}}}
    out = {}
    for attempt in range(7):
        try:
            r = requests.post(dbx_auth.GATEWAY_URL, headers=dbx_auth.headers(), json=payload, timeout=120)
            if r.status_code in (429, 500, 502, 503, 504, 529):
                out = {"error": "%d %s" % (r.status_code, r.text[:200])}
                time.sleep(min(40, 2 ** attempt + random.random() * 2))
                continue
            if r.status_code != 200:
                out = {"error": "%d %s" % (r.status_code, r.text[:300])}
                break
            text = output_text(r.json())
            out = json.loads(text[text.find("{"):text.rfind("}") + 1])
            break
        except Exception as e:
            out = {"error": "%s: %s" % (type(e).__name__, str(e)[:200])}
            time.sleep(2)
    return key, out


def save(cache_path, new):
    """Merge this run's grades into the file on disk and return the merged cache.

    Two runs can grade at the same time (different model sets); writing our in-memory copy over the
    file would drop whatever the other run saved since we loaded it.
    """
    import fcntl
    with open(cache_path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        disk = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
        disk.update({k: v for k, v in new.items() if "grade" in v or k not in disk})
        tmp = "%s.tmp%d" % (cache_path, os.getpid())
        json.dump(disk, open(tmp, "w"))
        os.replace(tmp, cache_path)
    return disk


def sign_test(better, worse):
    n, k = better + worse, min(better, worse)
    return 1.0 if n == 0 else min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def main():
    ev, names = sys.argv[1], sys.argv[2:]
    labels = {"vizwiz": {r["id"]: r for r in fetch(ev, "vizwiz_eval_labels.json") if "answerable" in r},
              "phone": {r["id"]: r for r in json.load(open(os.path.join(ev, "phone_labels.json")))}}
    cache_path = os.path.join(ev, "lfm3_judgements.json" if "terra" in MODEL else "lfm3_judgements_%s.json" % MODEL.replace(".", "_"))
    if "terra" in MODEL:
        cache = fetch(ev, "lfm3_judgements.json")
    else:
        cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    answers = {"vizwiz": {n: read_tsv(os.path.join(ev, "runs", n + ".tsv")) for n in names},
               "phone": {n: read_tsv(os.path.join(ev, "runs", "phone_" + n + ".tsv")) for n in names}}

    jobs = {}
    for source in answers:
        for name, by_id in answers[source].items():
            for qid, a in by_id.items():
                k = key_of(source, qid, a)
                if qid in labels[source] and (k not in cache or "grade" not in cache[k]):
                    jobs[k] = (k, labels[source][qid], a)
    print(len(jobs), "new judgements to make")
    new = {}
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for n, (k, out) in enumerate(pool.map(judge, list(jobs.values())), 1):
            cache[k] = new[k] = out
            if n % 250 == 0:
                save(cache_path, new)
                print("judged", n, flush=True)
    cache.update(save(cache_path, new))
    print("judge:", MODEL, "| grades in cache:", sum(1 for v in cache.values() if "grade" in v), "| failed:", sum(1 for v in cache.values() if "grade" not in v))

    rank = {"wrong": 0, "partly": 1, "right": 2}
    for source in ("vizwiz", "phone"):
        base = None
        print("\n===== %s (%d items) =====" % (source, len(labels[source])))
        for name in names:
            rows = []
            for qid, lab in labels[source].items():
                a = answers[source][name].get(qid)
                if a is None:
                    continue
                j = cache.get(key_of(source, qid, a), {})
                if j.get("grade"):
                    rows.append((qid, lab, a, j["grade"], j.get("declined")))
            if not rows:
                print("CONFIG %-18s no answers" % name)
                continue
            got = {r[0]: r[3] for r in rows}
            if base is None:
                base = got
            c = Counter(r[3] for r in rows)
            can = [r for r in rows if r[1]["answerable"] != "no"]
            cannot = [r for r in rows if r[1]["answerable"] == "no"]
            better = sum(1 for q, g in got.items() if q in base and rank[g] > rank[base[q]])
            worse = sum(1 for q, g in got.items() if q in base and rank[g] < rank[base[q]])
            words = sum(len(r[2].split()) for r in rows) / len(rows)
            print("CONFIG %-18s n=%d right=%d partly=%d wrong=%d | answerable: right %d/%d, partly %d, declined %d | "
                  "not answerable: declined %d/%d, invented %d | words %.1f | vs %s: better %d, worse %d, p=%.3f" % (
                      name, len(rows), c["right"], c["partly"], c["wrong"],
                      sum(1 for r in can if r[3] == "right"), len(can), sum(1 for r in can if r[3] == "partly"),
                      sum(1 for r in can if r[4]),
                      sum(1 for r in cannot if r[3] == "right"), len(cannot), sum(1 for r in cannot if r[3] == "wrong"),
                      words, names[0], better, worse, sign_test(better, worse)))
        types = Counter(lab.get("answer_type", "other") for lab in labels[source].values() if lab["answerable"] != "no")
        print("--- right% by answer type (answerable only): " + " ".join(names))
        for t, tn in types.most_common():
            cells = []
            for name in names:
                rs = [(lab, cache.get(key_of(source, qid, answers[source][name].get(qid, "")), {}).get("grade"))
                      for qid, lab in labels[source].items()
                      if lab["answerable"] != "no" and lab.get("answer_type", "other") == t and qid in answers[source][name]]
                rs = [g for _, g in rs if g]
                cells.append("%.0f" % (100 * sum(1 for g in rs if g == "right") / max(1, len(rs))))
            print("TYPE %-16s %3d  %s" % (t, tn, "  ".join(cells)))


if __name__ == "__main__":
    main()
