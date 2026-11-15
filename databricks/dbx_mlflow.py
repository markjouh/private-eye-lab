"""Log the fine-tune runs and their test results to Databricks-managed MLflow.

One experiment, one run per model (stock baseline, fine-tune v1, Witness-2B = fine-tune v2): settings, the
training-loss curve read from the log on markws, test metrics from the graded results, the scripts
and labelling prompts as artifacts, and the per-photo results as a table.

  DATABRICKS_HOST=... DATABRICKS_AUTH_TYPE=external-browser \
  uv run --with mlflow --with databricks-sdk --with pandas dbx_mlflow.py
"""
import json, os, re, subprocess, sys, tempfile

os.environ.setdefault("DATABRICKS_HOST", "https://dbc-5bd2d642-3eac.cloud.databricks.com")
os.environ.setdefault("DATABRICKS_AUTH_TYPE", "external-browser")
os.environ.setdefault("MLFLOW_USE_DATABRICKS_SDK_MODEL_ARTIFACTS_REPO_FOR_UC", "True")
import mlflow
import pandas as pd
from mlflow.models import ModelSignature
from mlflow.types import ColSpec, Schema

import dbx_auth

HERE = os.path.dirname(os.path.abspath(__file__))
E = os.path.join(HERE, "eval")
cache = json.load(open(os.path.join(E, "lfm3_judgements_gpt-6_1-sol.json")))  # grades from gpt-6.1-sol only
labels = {"vizwiz500": {r["id"]: r for r in json.load(open(os.path.join(E, "vizwiz_eval_labels.json"))) if "answerable" in r},
          "phone42": {r["id"]: r for r in json.load(open(os.path.join(E, "phone_labels.json")))}}


def results(config):
    rows = []
    for test_set, path, src in (("vizwiz500", "runs/%s.tsv" % config, "vizwiz"), ("phone42", "runs/phone_%s.tsv" % config, "phone")):
        full = os.path.join(E, path)
        if not os.path.exists(full):
            continue
        for line in open(full, encoding="utf-8"):
            p = line.rstrip("\n").split("\t")
            if len(p) < 3 or p[0] not in labels[test_set]:
                continue
            j = cache.get("%s|%s|%s" % (src, p[0], " ".join(p[2].lower().split())), {})
            lab = labels[test_set][p[0]]
            rows.append({"test_set": test_set, "id": p[0], "question": lab["question"], "answerable": lab["answerable"],
                         "answer_type": lab.get("answer_type"), "reference_answer": lab.get("reference_answer"),
                         "answer": p[2], "grade": j.get("grade"), "declined": j.get("declined"), "reason": j.get("reason")})
    return pd.DataFrame(rows)


def metrics(df):
    out = {}
    for test_set, d in df.groupby("test_set"):
        can, cannot = d[d.answerable != "no"], d[d.answerable == "no"]
        out.update({
            test_set + "_right": int((d.grade == "right").sum()), test_set + "_partly": int((d.grade == "partly").sum()),
            test_set + "_wrong": int((d.grade == "wrong").sum()), test_set + "_right_pct": round(100 * (d.grade == "right").mean(), 1),
            test_set + "_answerable_right": int((can.grade == "right").sum()),
            test_set + "_declined_on_answerable": int(can.declined.fillna(False).sum()),
            test_set + "_declined_correctly": int((cannot.grade == "right").sum()),
            test_set + "_invented_answers": int((cannot.grade == "wrong").sum()),
            test_set + "_mean_words": round(d.answer.str.split().str.len().mean(), 2)})
    return out


def train_log(run):
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", "markws", "cat ~/eyes-ft/runs_%s.log" % run], capture_output=True, text=True).stdout
    curve = [(int(m.group(1)), float(m.group(2))) for m in re.finditer(r"step (\d+)/\d+ \| loss ([\d.]+)", out)]
    before = re.search(r"val loss before: ([\d.]+)", out)
    after = re.search(r"val loss after: ([\d.]+) \| train time ([\d.]+) min", out)
    rows = re.search(r"(\d+) train, (\d+) val", out)
    return curve, before, after, rows, out


LAB = os.path.dirname(HERE)
UC_MODEL = "workspace.eyes.witness_2b"  # version 2 is Witness-2B; version 1 is the earlier fine-tune
ALIAS = {"v1": "on_phone", "v2": "candidate"}
SIGNATURE = ModelSignature(inputs=Schema([ColSpec("string", "request")]),
                           outputs=Schema([ColSpec("string", "file"), ColSpec("string", "path"), ColSpec("double", "megabytes")]))


def register(train_run, tmp):
    """Log the phone model file and the LoRA adapter as one model version in Unity Catalog."""
    lora = os.path.join(tmp, "lora")
    subprocess.run(["scp", "-q", "-r", "-o", "BatchMode=yes", "markws:eyes-ft/runs/%s/lora" % train_run, lora], check=True)
    gguf = os.path.join(LAB, "models", "eyes-ft-%s-Q4_K_M.gguf" % train_run)
    info = mlflow.pyfunc.log_model(name="phone_model", python_model=os.path.join(HERE, "eyes_model.py"),
                                   artifacts={"gguf_q4_k_m": gguf, "lora_adapter": lora}, signature=SIGNATURE,
                                   pip_requirements=["mlflow", "pandas"], registered_model_name=UC_MODEL)
    client = mlflow.MlflowClient(registry_uri="databricks-uc")
    v = info.registered_model_version
    client.set_registered_model_alias(UC_MODEL, ALIAS[train_run], v)
    client.update_model_version(UC_MODEL, v, description="Fine-tune %s of LFM3-VL-2B (LoRA r16 on the language model, merged, Q4_K_M GGUF). "
                                "Runs on the phone with the stock vision projector; not served from Databricks." % train_run)
    return v


RUNS = [
    ("stock-baseline", None, "A_app_768", {"model_file": "LFM3-VL-2B-QAD-Q4_0.gguf", "prompt": "app answer style", "fine_tuned": False}),
    ("fine-tune-v1", "v1", "G_ft_v1_plain", {"model_file": "eyes-ft-v1-Q4_K_M.gguf", "prompt": "bare question", "fine_tuned": True,
                                              "data": "VizWiz Q&A, relabelled by GPT through Unity Gateway", "batch_size": 6}),
    ("witness-2b", "v2", "G_ft_v2_plain", {"model_file": "eyes-ft-v2-Q4_K_M.gguf", "prompt": "bare question", "fine_tuned": True,
                                              "data": "VizWiz Q&A + useful declines + taps, where-is, which-one, not-in-view (COCO, VizWiz, phone frames)",
                                              "batch_size": 6}),
]
COMMON = {"base_model": "LiquidAI/LFM3-VL-2B", "method": "LoRA on language model", "lora_rank": 16, "lora_alpha": 32,
          "learning_rate": 2e-4, "epochs": 1, "image_max_side_px": 768, "quantization": "Q4_K_M (llama.cpp b12383)",
          "hardware": "1x RTX 5090 (own workstation)", "labeller": "gpt-6.1-sol / gpt-6.1-terra via Unity Gateway",
          "judge": "gpt-6.1-sol via Unity Gateway"}

if __name__ == "__main__":
    me = dbx_auth.client().current_user.me().user_name
    mlflow.set_tracking_uri("databricks")
    mlflow.set_registry_uri("databricks-uc")
    exp = mlflow.set_experiment("/Users/%s/eyes-lfm3-finetune" % me)
    # Earlier runs carried grades from a weaker judge; remove them so only gpt-6.1-sol numbers remain.
    for old in mlflow.search_runs([exp.experiment_id], output_format="list"):
        mlflow.delete_run(old.info.run_id)
        print("removed earlier run", old.info.run_name)
    with_models = "--no-models" not in sys.argv
    for name, train_run, config, params in RUNS:
        df = results(config)
        with mlflow.start_run(run_name=name) as run:
            mlflow.set_tags({"project": "private-eye", "eval_config": config, "test_sets": "vizwiz500, phone42",
                             "eval_tables": "workspace.eyes.eval_results",
                             "training_table": {"v1": "workspace.eyes.train_mix_v1", "v2": "workspace.eyes.train_mix_v2"}.get(train_run, "none")})
            mlflow.log_params({**({k: v for k, v in COMMON.items() if train_run or k in ("base_model", "judge", "image_max_side_px")}), **params})
            mlflow.log_metrics(metrics(df))
            mlflow.log_table(df, "eval/per_photo_results.json")
            if train_run:
                curve, before, after, rows, raw = train_log(train_run)
                for step, loss in curve:
                    mlflow.log_metric("train_loss", loss, step=step)
                if before:
                    mlflow.log_metric("val_loss_before", float(before.group(1)))
                if after:
                    mlflow.log_metric("val_loss_after", float(after.group(1)))
                    mlflow.log_metric("train_minutes", float(after.group(2)))
                if rows:
                    mlflow.log_param("train_rows", int(rows.group(1)))
                with tempfile.TemporaryDirectory() as tmp:
                    open(os.path.join(tmp, "train.log"), "w").write(raw)
                    mlflow.log_artifact(os.path.join(tmp, "train.log"), "training")
                for f in ("train_lfm3.py", "relabel_train.py", "label_v2.py", "build_train_set.py", "build_train_set_v2.py", "judge_local.py"):
                    mlflow.log_artifact(os.path.join(HERE, f), "code")
                if with_models:
                    with tempfile.TemporaryDirectory() as tmp:
                        print(name, "registered as", UC_MODEL, "version", register(train_run, tmp), flush=True)
            print(name, "logged:", run.info.run_id, {k: v for k, v in metrics(df).items() if k.endswith("500_right") or k.endswith("invented_answers")})
