"""Package 20 VizWiz validation photos (10 labelled unanswerable, 10 answerable) for the relabel pilot.

Usage: python3 -I build_pilot_data.py <val.json> <val image dir> <resize work dir> <out.json>
The 20 ids are the first ten of each group from the random audit sample drawn earlier
(seed 20261114), so each one has also been checked by eye.
"""
import base64, json, os, subprocess, sys

ann_path, img_dir, work_dir, out_path = sys.argv[1:5]
IDS = [
    # labelled unanswerable by the dataset
    "00000212", "00000906", "00002849", "00003062", "00002376",
    "00002547", "00000467", "00002497", "00000067", "00002082",
    # labelled answerable by the dataset
    "00003468", "00003636", "00004216", "00003105", "00002270",
    "00002353", "00003875", "00001697", "00001409", "00001507",
]
by_name = {x["image"]: x for x in json.load(open(ann_path))}
os.makedirs(work_dir, exist_ok=True)
items = []
for i in IDS:
    name = f"VizWiz_val_{i}.jpg"
    x = by_name[name]
    dst = os.path.join(work_dir, name)
    subprocess.run(["sips", "-Z", "1024", "-s", "format", "jpeg", "-s", "formatOptions", "60",
                    os.path.join(img_dir, name), "--out", dst],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    items.append({
        "id": i,
        "image": name,
        "question": x["question"].strip(),
        "crowd_answers": [a["answer"] for a in x["answers"]],
        "dataset_answerable": x["answerable"],
        "image_b64": base64.b64encode(open(dst, "rb").read()).decode(),
    })
json.dump(items, open(out_path, "w"))
print(len(items), "items,", round(os.path.getsize(out_path) / 1e6, 2), "MB")
