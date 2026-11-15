"""Summarise the 2B-model comparison on the relabelled VizWiz 500 from the cached grades.

Usage: python3 -I summarize_others.py [sample_id ...]
Reads eval/runs/*.tsv and the gpt-6.1-sol grades in eval/lfm3_judgements_gpt-6_1-sol.json (grade with judge_local.py first).
Writes eval/others_summary.json: per run the counts, and for the sample ids given every model's answer.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
EV = os.path.join(HERE, "eval")

MODELS = [  # label, plain run, styled run
    ("Private Eye fine-tune (LFM3-VL-2B)", "G_ft_v2_plain", "H_ft_v2_app"),
    ("LFM3-VL-2B", "D_plain_768", "A_app_768"),
    ("Qwen3.5-2B", "K_qwen35_plain", "K_qwen35_styled"),
    ("Qwen3-VL-2B", "L_qwen3vl_plain", "L_qwen3vl_styled"),
    ("Gemma 4 E2B", "M2_gemma4_560_plain", "M2_gemma4_560_styled"),
    ("SmolVLM2-2.2B", "N_smolvlm2_plain", "N_smolvlm2_styled"),
    ("InternVL3.5-2B", "O_internvl35_plain", "O_internvl35_styled"),
]


def read_tsv(name):
    path, out = os.path.join(EV, "runs", name + ".tsv"), {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            p = line.rstrip("\n").split("\t")
            if len(p) >= 3:
                out[p[0]] = p[2].strip()
    return out


def main():
    labels = {r["id"]: r for r in json.load(open(os.path.join(EV, "vizwiz_eval_labels.json"))) if "answerable" in r}
    cache = json.load(open(os.path.join(EV, "lfm3_judgements_gpt-6_1-sol.json")))   # the judge every reported grade uses
    grade = lambda q, a: cache.get("vizwiz|%s|%s" % (q, " ".join(a.lower().split())), {})
    out = {"n": len(labels), "answerable": sum(1 for l in labels.values() if l["answerable"] != "no"),
           "unanswerable": sum(1 for l in labels.values() if l["answerable"] == "no"), "runs": {}, "models": [], "samples": {}}
    answers = {}
    for label, plain, styled in MODELS:
        entry = {"model": label}
        for mode, name in (("plain", plain), ("styled", styled)):
            ans = read_tsv(name)
            answers[name] = ans
            if not ans:
                continue
            rows = [(labels[q], grade(q, a)) for q, a in ans.items() if q in labels]
            ungraded = sum(1 for _, g in rows if not g.get("grade"))
            can = [(l, g) for l, g in rows if l["answerable"] != "no"]
            cannot = [(l, g) for l, g in rows if l["answerable"] == "no"]
            r = {"run": name, "n": len(rows), "ungraded": ungraded,
                 "right": sum(1 for _, g in rows if g.get("grade") == "right"),
                 "partly": sum(1 for _, g in rows if g.get("grade") == "partly"),
                 "wrong": sum(1 for _, g in rows if g.get("grade") == "wrong"),
                 "answerable_right": sum(1 for _, g in can if g.get("grade") == "right"),
                 "answerable_declined": sum(1 for _, g in can if g.get("declined")),
                 "unanswerable_declined": sum(1 for _, g in cannot if g.get("grade") == "right"),
                 "unanswerable_invented": sum(1 for _, g in cannot if g.get("grade") == "wrong"),
                 "mean_words": round(sum(len(a.split()) for a in ans.values()) / len(ans), 1)}
            out["runs"][name] = r
            entry[mode] = r
            print("%-36s %-7s right %3d partly %3d wrong %3d | answerable right %3d/%d declined %2d | invented %3d/%d | words %.1f%s" % (
                label, mode, r["right"], r["partly"], r["wrong"], r["answerable_right"], len(can), r["answerable_declined"],
                r["unanswerable_invented"], len(cannot), r["mean_words"], "  UNGRADED %d" % ungraded if ungraded else ""))
        out["models"].append(entry)
    for q in sys.argv[1:]:
        l = labels[q]
        out["samples"][q] = {"question": l["question"], "answerable": l["answerable"], "reason": l.get("unanswerable_reason"),
                             "reference": l.get("reference_answer"), "evidence": l.get("evidence"),
                             "answers": {label: {"text": answers[plain].get(q), "grade": grade(q, answers[plain].get(q, "")).get("grade")}
                                         for label, plain, _ in MODELS if answers.get(plain)}}
    json.dump(out, open(os.path.join(EV, "others_summary.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
