"""Turn the relabelled VizWiz training photos into fine-tuning rows.

Usage: python3 -I build_train_set.py <train_labels.jsonl> <out train.jsonl>
Each output row: image file, question as asked, and the spoken answer to learn.
Rows with an error or an empty answer are skipped; the mix of answerable and unanswerable photos
is kept as it is in the data, because learning when to decline depends on it.
"""
import collections, json, sys

src, dst = sys.argv[1:3]
seen, rows, skipped = set(), [], collections.Counter()
for line in open(src, encoding="utf-8"):
    r = json.loads(line)
    if "answerable" not in r:
        skipped["error"] += 1
        continue
    if r["image"] in seen:
        continue
    answer = " ".join((r.get("spoken_answer") or "").split())
    if not answer:
        skipped["empty answer"] += 1
        continue
    seen.add(r["image"])
    rows.append({"image": r["image"], "question": r["question"], "answer": answer,
                 "answerable": r["answerable"], "answer_type": r["answer_type"]})
with open(dst, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
words = [len(r["answer"].split()) for r in rows]
print(len(rows), "rows;", dict(skipped), "skipped")
print("answerable:", dict(collections.Counter(r["answerable"] for r in rows)))
print("answer type:", dict(collections.Counter(r["answer_type"] for r in rows).most_common()))
print("answer words: mean %.1f, median %d, over 12 words: %d" % (
    sum(words) / len(words), sorted(words)[len(words) // 2], sum(1 for w in words if w > 12)))
print("most common answers:", collections.Counter(r["answer"] for r in rows).most_common(12))
