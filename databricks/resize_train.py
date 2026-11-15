"""Make 768 px copies of the VizWiz training photos (the size the app gives LFM3) for fine-tuning.

Usage: uv run --with pillow resize_train.py <train.json> <image dir> <out dir> [side]
"""
import json, os, sys
from concurrent.futures import ProcessPoolExecutor
from PIL import Image, ImageOps

ann, src, dst = sys.argv[1:4]
side = int(sys.argv[4]) if len(sys.argv) > 4 else 768


def one(name):
    out = os.path.join(dst, name)
    if os.path.exists(out):
        return 0
    img = ImageOps.exif_transpose(Image.open(os.path.join(src, name))).convert("RGB")
    img.thumbnail((side, side), Image.LANCZOS)
    img.save(out, format="JPEG", quality=90)
    return 1


if __name__ == "__main__":
    os.makedirs(dst, exist_ok=True)
    names = [x["image"] for x in json.load(open(ann))]
    with ProcessPoolExecutor(max_workers=6) as pool:
        made = sum(pool.map(one, names, chunksize=64))
    print(len(names), "photos,", made, "resized now")
