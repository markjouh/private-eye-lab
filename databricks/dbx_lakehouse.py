"""Load the project's data into Unity Catalog: schema workspace.eyes, a volume for files, Delta tables,
and views that join model answers to their grades. Safe to re-run; it replaces the tables.

  uv run --with databricks-sdk dbx_lakehouse.py            # everything
  uv run --with databricks-sdk dbx_lakehouse.py eval       # only the evaluation tables (after a new run)
"""
import glob, io, json, os, sys, time

import dbx_auth
from databricks.sdk.service.sql import StatementState

LAB = "/Users/mark/Documents/s26-eyes-lab"
T, E = LAB + "/databricks/train/", LAB + "/databricks/eval/"
SCHEMA = "workspace.eyes"
VOL = "/Volumes/workspace/eyes/files"
# Every reported grade comes from the strongest model in the gateway provider.
JUDGE, JUDGE_CACHE = "gpt-6.1-sol", "lfm3_judgements_gpt-6_1-sol.json"
# Test frames kept off the server (a card is visible in the frame).
HELD_BACK = {"163243-788.jpg"}
w = dbx_auth.client()
WAREHOUSE = list(w.warehouses.list())[0].id

CONFIGS = {
    "A_app_768": ("LFM3-VL-2B stock (QAD Q4)", "app answer style", "Baseline: the app as shipped", "Stock model, app prompt (as shipped)"),
    "B_app_1024": ("LFM3-VL-2B stock (QAD Q4)", "app answer style, 1024 px", "Larger image", "Stock, larger image (1024 px)"),
    "C_label_768": ("LFM3-VL-2B stock (QAD Q4)", "label-first prompt", "Prompt that asks it to decline", "Stock, prompt asking it to decline"),
    "D_plain_768": ("LFM3-VL-2B stock (QAD Q4)", "bare question", "No instruction", "Stock, bare question"),
    "E_app_q8": ("LFM3-VL-2B stock (Q8)", "app answer style", "Less compressed weights", "Stock, 8-bit weights"),
    "F_app_q8_f16": ("LFM3-VL-2B stock (Q8, F16 projector)", "app answer style", "Less compressed weights and projector", "Stock, 8-bit weights and F16 projector"),
    "G_ft_v1_plain": ("eyes-ft-v1 (Q4_K_M)", "bare question", "Fine-tune v1, as trained", "Fine-tune v1, bare question"),
    "H_ft_v1_app": ("eyes-ft-v1 (Q4_K_M)", "app answer style", "Fine-tune v1 with the app's instruction lines", "Fine-tune v1, app prompt"),
    "G_ft_v2_plain": ("Witness-2B (Q4_K_M)", "bare question", "Witness-2B (our second fine-tune, file eyes-ft-v2), as trained", "Witness-2B, bare question"),
    "H_ft_v2_app": ("Witness-2B (Q4_K_M)", "app answer style", "Witness-2B with the app's instruction lines", "Witness-2B, app prompt"),
    # Other phone-size models, run by run_other_model.py through llama-server with the app's system prompt and sampling.
    # "app instructions" = the app's per-question instruction line, without the app's text filter.
    "K_qwen35_plain": ("Qwen3.5-2B (Q4_K_M)", "bare question", "Other 2B-class model", "Qwen3.5-2B, bare question"),
    "K_qwen35_styled": ("Qwen3.5-2B (Q4_K_M)", "app instructions", "Other 2B-class model", "Qwen3.5-2B, app instructions"),
    "L_qwen3vl_plain": ("Qwen3-VL-2B (Q4_K_M)", "bare question", "Other 2B-class model", "Qwen3-VL-2B, bare question"),
    "L_qwen3vl_styled": ("Qwen3-VL-2B (Q4_K_M)", "app instructions", "Other 2B-class model", "Qwen3-VL-2B, app instructions"),
    "M2_gemma4_560_plain": ("Gemma 4 E2B (Q4_0, 560 image tokens)", "bare question", "Other 2B-class model", "Gemma 4 E2B, bare question"),
    "M2_gemma4_560_styled": ("Gemma 4 E2B (Q4_0, 560 image tokens)", "app instructions", "Other 2B-class model", "Gemma 4 E2B, app instructions"),
    "N_smolvlm2_plain": ("SmolVLM2-2.2B (Q4_K_M)", "bare question", "Other 2B-class model", "SmolVLM2-2.2B, bare question"),
    "N_smolvlm2_styled": ("SmolVLM2-2.2B (Q4_K_M)", "app instructions", "Other 2B-class model", "SmolVLM2-2.2B, app instructions"),
    "O_internvl35_plain": ("InternVL3.5-2B (Q4_K_M)", "bare question", "Other 2B-class model", "InternVL3.5-2B, bare question"),
    "O_internvl35_styled": ("InternVL3.5-2B (Q4_K_M)", "app instructions", "Other 2B-class model", "InternVL3.5-2B, app instructions"),
}


def family(config):
    return "Private Eye fine-tune" if config[0] in "GH" else "LFM3-VL-2B stock" if config[0] in "ABCDEF" else "Other 2B-class model"


def complete(name):
    """A configuration is loaded only when both of its answer files are finished (500 + 42 lines)."""
    def n(p):
        return sum(1 for _ in open(p, encoding="utf-8")) if os.path.exists(p) else 0
    return n(E + "runs/%s.tsv" % name) >= 500 and n(E + "runs/phone_%s.tsv" % name) >= 42


def sql(statement, quiet=False):
    r = w.statement_execution.execute_statement(warehouse_id=WAREHOUSE, statement=statement, wait_timeout="50s")
    for _ in range(450):  # up to 30 minutes, for batch ai_query statements
        if r.status.state in (StatementState.SUCCEEDED, StatementState.FAILED, StatementState.CANCELED, StatementState.CLOSED):
            break
        time.sleep(4)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError("%s\n%s" % (statement[:200], getattr(r.status, "error", r.status.state)))
    rows = (r.result.data_array or []) if r.result else []
    if not quiet and rows:
        print("   ", rows[:6])
    return rows


def norm(answer):
    return " ".join(answer.lower().split())


def jsonl(path):
    out = []
    for f in sorted(glob.glob(path)):
        for line in open(f, encoding="utf-8"):
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def dedupe(rows, key, need):
    seen, out = set(), []
    for r in rows:
        if need in r and r[key] not in seen:
            seen.add(r[key])
            out.append(r)
    return out


def stage(name, rows):
    """Upload rows as JSON Lines to the volume and (re)create a Delta table from them."""
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows).encode("utf-8")
    path = "%s/staging/%s.jsonl" % (VOL, name)
    w.files.upload(path, io.BytesIO(body), overwrite=True)
    sql("CREATE OR REPLACE TABLE %s.%s AS SELECT * EXCEPT (_rescued_data) FROM read_files('%s', format => 'json')" % (SCHEMA, name, path), quiet=True)
    n = sql("SELECT count(*) FROM %s.%s" % (SCHEMA, name), quiet=True)[0][0]
    print("%-24s %7s rows  (%0.1f MB staged)" % (name, n, len(body) / 1e6), flush=True)


def comment(table, text):
    sql("COMMENT ON TABLE %s.%s IS '%s'" % (SCHEMA, table, text.replace("'", "''")), quiet=True)


def data_tables():
    crowd = []
    for split in ("train", "val"):
        for x in json.load(open("%s/vizwiz/annotations/%s.json" % (LAB, split))):
            crowd.append({"split": split, "image": x["image"], "question": x["question"],
                          "crowd_answers": [a["answer"] for a in x["answers"]],
                          "crowd_confidence": [a["answer_confidence"] for a in x["answers"]],
                          "dataset_answerable": x["answerable"], "dataset_answer_type": x["answer_type"]})
    stage("vizwiz_crowd", crowd)
    comment("vizwiz_crowd", "Bronze. VizWiz-VQA train and validation questions as published: photos by blind people, the question asked aloud, ten crowd answers.")

    keep = ("image", "question", "answerable", "spoken_answer", "unanswerable_reason", "answer_type", "evidence",
            "crowd_verdict", "labeller", "in_tok", "out_tok", "seconds")
    rel = [{k: r.get(k) for k in keep} for r in dedupe(jsonl(T + "all_labels.jsonl"), "image", "answerable")]
    stage("vizwiz_relabel_train", rel)
    comment("vizwiz_relabel_train", "Silver. All 20,523 VizWiz training photos relabelled by GPT through Unity Gateway: answerable or not, a spoken answer, the obstacle, and whether the crowd majority was overturned.")

    ev = [dict(r, test_set="vizwiz500") for r in json.load(open(E + "vizwiz_eval_labels.json")) if "answerable" in r]
    ph = [dict(r, test_set="phone42", image=r["turn"] + ".jpg") for r in json.load(open(E + "phone_labels.json"))]
    for r in ev:
        r["photo_path"] = "%s/photos/vizwiz_eval_500/%s" % (VOL, r["image"])
    for r in ph:
        r["photo_path"] = None if r["image"] in HELD_BACK else "%s/photos/phone_eval/%s" % (VOL, r["image"])
    cols = ("test_set", "id", "image", "photo_path", "question", "answerable", "reference_answer", "acceptable_answers", "unanswerable_reason", "answer_type")
    stage("eval_labels", [{k: r.get(k) for k in cols} for r in ev + ph])
    comment("eval_labels", "Silver. Reference labels for the two test sets: 500 relabelled VizWiz validation photos and 42 frames saved from the phone (labelled by hand). photo_path points at the photo in the volume.")

    taps = []
    for src, pattern in (("phone", "v2_taps_phone.jsonl"), ("coco", "v2_taps_coco_*.jsonl"), ("vizwiz", "v2_taps_vizwiz_*.jsonl")):
        for r in dedupe(jsonl(T + pattern), "image", "tap_reply"):
            taps.append({"source": src, "image": r["image"], "usable": r["usable"], "one_object": r["one_object"],
                         "tap_reply": r["tap_reply"], "where_examples": r["where"], "which_question": r["which"]["question"],
                         "which_answer": r["which"]["answer"], "absent_question": r["absent_question"],
                         "absent_reply": r["absent_reply"], "labeller": r.get("labeller"),
                         "in_tok": r.get("in_tok"), "out_tok": r.get("out_tok")})
    stage("tap_labels_v2", taps)
    comment("tap_labels_v2", "Silver. Tap-style labels for the second fine-tune: what a sighted guide would say on a tap (nearest first), plus where-is-it, which-one and not-in-view examples. Sources: COCO, VizWiz and frames from phone testing.")

    dec = [{k: r.get(k) for k in ("image", "question", "answerable", "answer_type", "old_reply", "reply", "action", "labeller", "in_tok", "out_tok")}
           for r in dedupe(jsonl(T + "v2_declines_*.jsonl"), "image", "reply")]
    stage("declines_v2", dec)
    comment("declines_v2", "Silver. Replies for questions the photo cannot fully answer, rewritten to say what is wrong and what to do.")

    stage("train_mix_v1", [dict(r, mix="v1") for r in jsonl(T + "train.jsonl")])
    comment("train_mix_v1", "Gold. Training rows for fine-tune v1: VizWiz question and spoken answer.")
    stage("train_mix_v2", [dict(r, mix="v2") for r in jsonl(T + "train_v2.jsonl")])
    comment("train_mix_v2", "Gold. Training rows for Witness-2B (fine-tune v2): answers, useful declines, taps, where-is, which-one and not-in-view, all as bare questions.")


TAP_MODELS = (("stock", "LFM3-VL-2B stock (app tap path)"), ("v1", "Fine-tune v1"), ("v2", "Witness-2B"))


def tap_table():
    rows = []
    for r in json.load(open(E + "tap_comparison.json")):
        for key, model in TAP_MODELS:
            rows.append({"image": r["image"], "source": "phone" if r["dir"].startswith("phone") else "coco", "label": r["reference"],
                         "model": model, "reply": r[key], "words": len(r[key].split())})
    stage("tap_comparison", rows)
    comment("tap_comparison", "Gold. Replies to a tap (What is in front of me?) on 70 photos held out of training: the stock app, fine-tune v1 and Witness-2B, next to the sighted-guide label.")


def photo_table():
    rows = []
    for d in w.files.list_directory_contents(VOL + "/photos"):
        if d.is_directory:
            for f in w.files.list_directory_contents(d.path):
                rows.append({"photo_set": d.name, "file": f.name, "path": f.path, "bytes": f.file_size})
    stage("photos", rows)
    comment("photos", "Inventory of the photos stored in the volume: VizWiz training and test photos, COCO photos and frames from phone testing (none showing an ID card).")


def eval_tables():
    answers, present = [], []
    for name in CONFIGS:
        if not complete(name):
            continue
        for test_set, path in (("vizwiz500", E + "runs/%s.tsv" % name), ("phone42", E + "runs/phone_%s.tsv" % name)):
            present.append(name)
            for line in open(path, encoding="utf-8"):
                p = line.rstrip("\n").split("\t")
                if len(p) >= 3:
                    answers.append({"test_set": test_set, "config": name, "id": p[0], "answer": p[2].strip(),
                                    "answer_norm": norm(p[2]), "words": len(p[2].split())})
    stage("eval_answers", answers)
    comment("eval_answers", "Gold. What each model configuration answered on each test photo, produced on the Mac by the app's own command-line tool.")

    cache = json.load(open(E + JUDGE_CACHE))
    judged = []
    for key, j in cache.items():
        src, qid, ans = key.split("|", 2)
        if "grade" in j:
            judged.append({"test_set": "vizwiz500" if src == "vizwiz" else "phone42", "id": qid, "answer_norm": ans,
                           "grade": j["grade"], "declined": bool(j.get("declined")), "reason": j.get("reason"), "judge": JUDGE})
    stage("eval_judgements", judged)
    comment("eval_judgements", "Gold. One grade per distinct answer to a test photo, from gpt-6.1-sol through Unity Gateway. The judge sees the question, the reference label and the answer (no photo). The job grade-new-answers adds rows for answers not graded yet.")

    stage("model_configs", [{"config": k, "model": v[0], "prompt": v[1], "description": v[2], "label": v[3], "sort_order": i,
                             "fine_tuned": k[0] in "GH", "family": family(k), "has_results": k in set(present)}
                            for i, (k, v) in enumerate(CONFIGS.items())])
    comment("model_configs", "The model and prompt behind each evaluated configuration.")

    sql("DROP VIEW IF EXISTS %s.eval_summary" % SCHEMA, quiet=True)
    sql("""CREATE OR REPLACE VIEW %(s)s.eval_results AS
SELECT a.test_set, a.config, c.label, c.sort_order, c.fine_tuned, c.family, c.model, c.prompt, a.id, l.photo_path, l.question, l.answerable,
       l.answer_type, l.reference_answer, a.answer, a.words, j.grade, j.declined, j.reason, j.judge
FROM %(s)s.eval_answers a
JOIN %(s)s.eval_labels l ON l.test_set = a.test_set AND l.id = a.id
JOIN %(s)s.model_configs c ON c.config = a.config
LEFT JOIN %(s)s.eval_judgements j ON j.test_set = a.test_set AND j.id = a.id AND j.answer_norm = a.answer_norm""" % {"s": SCHEMA}, quiet=True)
    sql("""CREATE OR REPLACE VIEW %(s)s.eval_summary AS
SELECT test_set, config, label, sort_order, fine_tuned, family, model, prompt, count(*) AS photos,
       count(*) - count(grade) AS ungraded,
       count_if(grade = 'right') AS right_answers, count_if(grade = 'partly') AS partly, count_if(grade = 'wrong') AS wrong,
       round(100 * count_if(grade = 'right') / nullif(count(grade), 0), 1) AS right_pct,
       count_if(answerable <> 'no') AS answerable_photos,
       count_if(answerable <> 'no' AND grade = 'right') AS answerable_right,
       count_if(answerable <> 'no' AND declined) AS declined_on_answerable,
       count_if(answerable = 'no') AS unanswerable_photos,
       count_if(answerable = 'no' AND grade = 'right') AS declined_correctly,
       count_if(answerable = 'no' AND grade = 'wrong') AS invented_answers,
       round(avg(words), 1) AS mean_words
FROM %(s)s.eval_results GROUP BY ALL""" % {"s": SCHEMA}, quiet=True)
    print("views eval_results, eval_summary ready")
    for r in sql("SELECT config, right_answers, partly, wrong, invented_answers, ungraded FROM %s.eval_summary WHERE test_set = 'vizwiz500' ORDER BY sort_order" % SCHEMA, quiet=True):
        print("    %-22s right %s  partly %s  wrong %s  invented %s  ungraded %s" % tuple(r))


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else "all"
    sql("CREATE SCHEMA IF NOT EXISTS %s COMMENT 'Private Eye: data, labels and evaluation for the on-device assistant for blind users'" % SCHEMA, quiet=True)
    sql("CREATE VOLUME IF NOT EXISTS %s.files COMMENT 'Staged label files and photos'" % SCHEMA, quiet=True)
    if only == "all":
        data_tables()
    if only in ("all", "taps"):
        tap_table()
    if only in ("all", "photos"):
        photo_table()
    if only not in ("photos", "taps"):
        eval_tables()
