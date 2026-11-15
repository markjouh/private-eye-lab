"""Collect eyes-cli outputs into one file for the judging notebook.

Usage: python3 -I build_answers.py <eval dir>
Reads <eval dir>/runs/*.tsv (tag, words, answer) and phone_labels.json; writes lfm3_answers.json.
"""
import json, os, sys

ev = sys.argv[1]
CONFIGS = {
    "A_app_768": "as the app runs it: answer style, 768 px, Q4 weights",
    "B_app_1024": "answer style, 1024 px image",
    "C_label_768": "one label-first prompt for every question, no filter",
    "D_plain_768": "question only, no instruction",
    "E_app_q8": "answer style, Q8 weights",
    "F_app_q8_f16": "answer style, Q8 weights and full-precision vision projector",
}

def read(path):
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 3:
            out[parts[0]] = parts[2].strip()
    return out

data = {"configs": CONFIGS, "vizwiz": {}, "phone": {},
        "phone_labels": json.load(open(os.path.join(ev, "phone_labels.json")))}
for name in CONFIGS:
    v = read(os.path.join(ev, "runs", name + ".tsv"))
    p = read(os.path.join(ev, "runs", "phone_" + name + ".tsv"))
    if v:
        data["vizwiz"][name] = v
    if p:
        data["phone"][name] = p
    print(name, len(v), "vizwiz answers,", len(p), "phone answers")
out = os.path.join(ev, "lfm3_answers.json")
json.dump(data, open(out, "w"))
print(out, round(os.path.getsize(out) / 1e3), "KB")
