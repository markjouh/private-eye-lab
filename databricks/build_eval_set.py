"""Draw the 500-photo VizWiz test set and package it for relabelling and for eyes-cli.

Usage: python3 -I build_eval_set.py <val.json> <val image dir> <resize work dir> <out dir>
Writes into <out dir>:
  eval_items.json            id, image, question, crowd answers, dataset flag (no pixels)
  chunks/vizwiz_eval_chunk_NN.json   the same items with a 1024 px JPEG as base64, under 9 MB each
  lfm3_styled.tsv / lfm3_label.tsv / lfm3_plain.tsv   batches for `eyes-cli ask --batch`
The 20 pilot photos are left out. Fixed seed, natural mix of answerable and unanswerable.
"""
import base64, json, os, random, subprocess, sys

ann_path, img_dir, work_dir, out_dir = sys.argv[1:5]
N, SEED, CHUNK_BYTES = 500, 500, 8_600_000
PILOT = {"00000212", "00000906", "00002849", "00003062", "00002376", "00002547", "00000467", "00002497",
         "00000067", "00002082", "00003468", "00003636", "00004216", "00003105", "00002270", "00002353",
         "00003875", "00001697", "00001409", "00001507"}
LABEL_SUFFIX = ('Answer in a short, specific phrase. If it has a label or brand, read it, like '
                '"Shampoo bottle, Head and Shoulders." If you cannot tell, say "Can\'t tell."')

val = json.load(open(ann_path))
pool = [x for x in val if x["image"].split("_")[-1].split(".")[0] not in PILOT]
random.seed(SEED)
sample = random.sample(pool, N)
os.makedirs(work_dir, exist_ok=True)
os.makedirs(os.path.join(out_dir, "chunks"), exist_ok=True)

items, chunk, chunk_size, chunk_no = [], [], 0, 0

def flush():
    global chunk, chunk_size, chunk_no
    if not chunk:
        return
    chunk_no += 1
    path = os.path.join(out_dir, "chunks", f"vizwiz_eval_chunk_{chunk_no:02d}.json")
    json.dump(chunk, open(path, "w"))
    print(os.path.basename(path), len(chunk), "items", round(os.path.getsize(path) / 1e6, 2), "MB")
    chunk, chunk_size = [], 0

for x in sample:
    i = x["image"].split("_")[-1].split(".")[0]
    dst = os.path.join(work_dir, x["image"])
    if not os.path.exists(dst):
        subprocess.run(["sips", "-Z", "1024", "-s", "format", "jpeg", "-s", "formatOptions", "60",
                        os.path.join(img_dir, x["image"]), "--out", dst],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    item = {"id": i, "image": x["image"], "question": " ".join(x["question"].split()),
            "crowd_answers": [a["answer"] for a in x["answers"]], "dataset_answerable": x["answerable"]}
    items.append(item)
    b64 = base64.b64encode(open(dst, "rb").read()).decode()
    if chunk_size + len(b64) > CHUNK_BYTES:
        flush()
    chunk.append(dict(item, image_b64=b64))
    chunk_size += len(b64) + 600
flush()

json.dump(items, open(os.path.join(out_dir, "eval_items.json"), "w"), indent=1)
with open(os.path.join(out_dir, "lfm3_styled.tsv"), "w") as a, \
     open(os.path.join(out_dir, "lfm3_label.tsv"), "w") as b, \
     open(os.path.join(out_dir, "lfm3_plain.tsv"), "w") as c:
    for it in items:
        p = os.path.join(img_dir, it["image"])
        a.write(f"{it['id']}\t{p}\t{it['question']}\n")
        b.write(f"{it['id']}\t{p}\t{it['question']}\t\t{LABEL_SUFFIX}\n")
        c.write(f"{it['id']}\t{p}\t{it['question']}\t\t\n")
print(len(items), "items;", sum(1 for it in items if it["dataset_answerable"] == 0), "labelled unanswerable by the dataset")
