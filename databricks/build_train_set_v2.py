"""Build the v2 fine-tuning mix (style agreed 2026-11-14: what a good sighted guide would say).

Usage: python3 -I build_train_set_v2.py <train dir> <eval dir>
Reads the v1 question labels (all_labels.jsonl), the rewritten declines (v2_declines_*.jsonl) and the
tap labels (v2_taps_*.jsonl); writes <train dir>/train_v2.jsonl and <eval dir>/tap_holdout.json.

Every prompt is the bare question; a tap is "What is in front of me?". Half the rows are marked to
train without the app's system prompt, so the model behaves the same whether or not the app sends it.
Held out for comparing tap replies afterwards: 30 phone tap frames and 40 COCO photos.
"""
import collections, glob, json, os, random, re, sys

train_dir, eval_dir = sys.argv[1:3]
rng = random.Random(7)
TAP_QUESTION = "What is in front of me?"


def load(pattern, key):
    out = {}
    for f in sorted(glob.glob(os.path.join(train_dir, pattern))):
        for line in open(f, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:
                continue
            if key in r and r["image"] not in out:
                out[r["image"]] = r
    return out


def clean(text):
    return " ".join((text or "").split())


rows, skipped = [], collections.Counter()

# 1. VizWiz questions: answers from the first labelling, declines rewritten to say what to do.
declines = load("v2_declines_*.jsonl", "reply")
seen = set()
for line in open(os.path.join(train_dir, "all_labels.jsonl"), encoding="utf-8"):
    r = json.loads(line)
    if "answerable" not in r or r["image"] in seen:
        continue
    seen.add(r["image"])
    if r["answerable"] == "yes":
        answer, kind = clean(r.get("spoken_answer")), "answer"
    elif r["image"] in declines:
        answer, kind = clean(declines[r["image"]]["reply"]), "decline"
    else:
        skipped["decline not rewritten"] += 1
        continue
    if answer:
        rows.append({"image": "train768/" + r["image"], "question": r["question"], "answer": answer, "kind": kind})

# 2. Taps, where-is, which-one and not-in-view, from three photo sources.
phone_routes = {x["image"]: x.get("route") for x in json.load(open(os.path.join(train_dir, "phone_frames_train.json")))}
sources = [("phone768", load("v2_taps_phone.jsonl", "tap_reply")),
           ("coco768", load("v2_taps_coco_*.jsonl", "tap_reply")),
           ("train768", load("v2_taps_vizwiz_*.jsonl", "tap_reply"))]
hold_phone = set(rng.sample(sorted(n for n in sources[0][1] if phone_routes.get(n) == "description"), 30))
hold_coco = set(rng.sample(sorted(sources[1][1]), 40))
holdout = [{"dir": "phone768", "image": n, "reference": sources[0][1][n]["tap_reply"]} for n in sorted(hold_phone)] + \
          [{"dir": "coco768", "image": n, "reference": sources[1][1][n]["tap_reply"]} for n in sorted(hold_coco)]
json.dump(holdout, open(os.path.join(eval_dir, "tap_holdout.json"), "w"), indent=1)

for folder, labels in sources:
    for name, r in labels.items():
        if name in hold_phone or name in hold_coco:
            continue
        image = folder + "/" + name
        tap = clean(r["tap_reply"])
        if not tap or len(tap.split()) > 26:
            skipped["tap reply empty or too long"] += 1
            continue
        rows.append({"image": image, "question": TAP_QUESTION, "answer": tap, "kind": "tap"})
        if not r["usable"]:
            continue
        if not r["one_object"] and r["where"]:
            q = rng.choice(r["where"])
            if clean(q["question"]) and clean(q["answer"]):
                rows.append({"image": image, "question": clean(q["question"]), "answer": clean(q["answer"]), "kind": "where"})
        if clean(r["which"]["question"]) and clean(r["which"]["answer"]):
            rows.append({"image": image, "question": clean(r["which"]["question"]), "answer": clean(r["which"]["answer"]), "kind": "which"})
        if rng.random() < 1 / 3 and clean(r["absent_question"]) and clean(r["absent_reply"]):
            rows.append({"image": image, "question": clean(r["absent_question"]), "answer": clean(r["absent_reply"]), "kind": "absent"})

for r in rows:
    r["sys"] = rng.random() < 0.5
rng.shuffle(rows)
with open(os.path.join(train_dir, "train_v2.jsonl"), "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

mix = collections.Counter(r["kind"] for r in rows)
print(len(rows), "rows |", {k: "%d (%.0f%%)" % (v, 100 * v / len(rows)) for k, v in mix.most_common()})
print("skipped:", dict(skipped), "| held out for tap comparison:", len(holdout))
by_src = collections.Counter(r["image"].split("/")[0] for r in rows if r["kind"] == "tap")
print("tap photos by source:", dict(by_src))
spoken = [r["answer"] for r in rows if r["kind"] in ("tap", "where", "which", "absent")]
grams = collections.Counter()
for t in spoken:
    w = re.findall(r"[a-z']+", t.lower())
    for g in set(" ".join(w[i:i + 3]) for i in range(len(w) - 2)):
        grams[g] += 1
print("stock-phrase check on %d tap-style replies: 'within reach' in %d; most repeated 3-word phrases: %s" % (
    len(spoken), sum("within reach" in t.lower() for t in spoken),
    [(g, "%.1f%%" % (100 * v / len(spoken))) for g, v in grams.most_common(6)]))
dec = [r["answer"] for r in rows if r["kind"] == "decline"]
print("declines: %d, mean %.1f words; most common: %s" % (len(dec), sum(len(d.split()) for d in dec) / max(1, len(dec)),
                                                         collections.Counter(dec).most_common(5)))
