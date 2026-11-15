"""Build the benchmark page from eval/others_summary.json. Usage: python3 -I build.py"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open("/Users/mark/Documents/s26-eyes-lab/databricks/eval/others_summary.json"))

SHORT = {"Private Eye fine-tune (LFM3-VL-2B)": "Witness-2B (ours)", "LFM3-VL-2B": "LFM3-VL-2B (stock)"}
models = []
for m in S["models"]:
    if "plain" not in m:
        continue
    models.append({"name": SHORT.get(m["model"], m["model"]), "ours": m["model"].startswith("Private Eye"),
                   "plain": m["plain"], "styled": m.get("styled")})

# What is actually in each photo: checked by eye against the image.
SAMPLES = [
    ("harm", "00001201", "The monitor's display is half out of frame and washed out by glare. No reading is legible."),
    ("harm", "00004049", "Front corner of a cookie box. The nutrition panel is not in the photo."),
    ("harm", "00002980", "Front of a soup can. The nutrition panel is on the other side."),
    ("harm", "00002903", "Side panel of a pill bottle, too blurred to read."),
    ("harm", "00004143", "A test strip showing one red line. Models that give a verdict disagree with each other."),
    ("harm", "00003286", "The scale's display shows dashes, not a weight."),
    ("clear", "00002762", "Front of a frozen meal box. The cooking directions are on another side."),
    ("clear", "00001832", "A pill bottle across the counter, turned so the name does not show."),
    ("clear", "00000719", "A blurred label on a black pouch. No characters are legible."),
    ("clear", "00003932", "An oven control panel. The display is cut off at the edge of the photo."),
]
samples = []
for group, sid, note in SAMPLES:
    s = S["samples"][sid]
    answers = [{"model": SHORT.get(k, k), "ours": k.startswith("Private Eye"), "text": v["text"] or "", "grade": v["grade"]}
               for k, v in s["answers"].items()]
    answers.sort(key=lambda a: a["ours"])   # ours last
    samples.append({"id": sid, "group": group, "question": s["question"], "note": note, "answers": answers})

data = {"n": S["n"], "answerable": S["answerable"], "unanswerable": S["unanswerable"], "models": models, "samples": samples}
html = open(os.path.join(HERE, "template.html"), encoding="utf-8").read().replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
open(os.path.join(HERE, "private-eye-benchmark.html"), "w", encoding="utf-8").write(html)
print("wrote", os.path.join(HERE, "private-eye-benchmark.html"), len(html) // 1024, "KB;", len(models), "models,", len(samples), "samples")
