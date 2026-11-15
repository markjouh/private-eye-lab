"""Which image embedding tells one object from another of its kind best?

Each model embeds the exact 224x224 crops the app shows its own model (written by
`eyes-cli things crops <models...> <photo dir> <out dir>` into <out dir>/inputs), and every pair of
crops in one category is scored by cosine: same object, or a look-alike (another object of that kind).

  python embedders.py <name>=<inputs dir>[:same groups] ... [--only substring]
  same groups: "book_0,book_2;cup_2,cup_6,cup_7" (clips that show one object)
"""
import sys, itertools, json, time
from pathlib import Path
import numpy as np, torch, timm
from PIL import Image

MODELS = [  # label, timm name, extra create args
    ("DINOv3 S/16 CLS (in the app)", "vit_small_patch16_dinov3.lvd1689m", dict(global_pool="token")),
    ("DINOv3 S/16 patch mean", "vit_small_patch16_dinov3.lvd1689m", dict(global_pool="avg")),
    ("DINOv3 B/16 CLS", "vit_base_patch16_dinov3.lvd1689m", dict(global_pool="token")),
    ("DINOv3 ConvNeXt-S", "convnext_small.dinov3_lvd1689m", {}),
    ("DINOv2 S/14 CLS", "vit_small_patch14_dinov2.lvd142m", dict(global_pool="token", img_size=224)),
    ("SigLIP 2 B/16", "vit_base_patch16_siglip_224.v2_webli", {}),
    ("SigLIP B/16", "vit_base_patch16_siglip_224.webli", {}),
    ("CLIP B/16 (OpenAI)", "vit_base_patch16_clip_224.openai", {}),
    ("CLIP B/16 (DFN-2B)", "vit_base_patch16_clip_224.dfn2b", {}),
    ("PE-Core B/16", "vit_pe_core_base_patch16_224.fb", {}),
    ("Supervised ViT-S/16 (ImageNet-21k)", "vit_small_patch16_224.augreg_in21k", {}),
    ("Supervised ViT-B/16 (ImageNet-21k)", "vit_base_patch16_224.augreg_in21k", {}),
]

def load(spec):
    name, rest = spec.split("=", 1)
    path, _, groups = rest.partition(":")
    same = [g.split(",") for g in groups.split(";") if g]
    files = sorted(Path(path).glob("*.png"))
    items = []
    for f in files:
        cat, inst, view = f.stem.split("_")
        scene = f"{cat}_{inst}"
        obj = next((g[0] for g in same if scene in g), scene)
        items.append((f, cat, obj))
    return name, items

def auc(pos, neg):
    pos, neg = np.asarray(pos), np.asarray(neg)
    order = np.argsort(np.concatenate([pos, neg])); ranks = np.empty(len(order)); ranks[order] = np.arange(1, len(order) + 1)
    return (ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))

def tar(pos, neg, far):
    thr = np.quantile(neg, 1 - far)
    return float((np.asarray(pos) > thr).mean()), float(thr)

def main():
    args = sys.argv[1:]
    only = None
    if "--only" in args:
        i = args.index("--only"); only = args[i + 1]; del args[i:i + 2]
    sets = [load(a) for a in args]
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    done = {json.loads(l)["model"] for l in Path("results.jsonl").read_text().splitlines() if l.startswith("{")} if Path("results.jsonl").exists() else set()
    for label, name, extra in MODELS:
        if label in done or (only and only.lower() not in label.lower()): continue
        t0 = time.time()
        try:
            net = timm.create_model(name, pretrained=True, num_classes=0, **extra).eval().to(device)
        except Exception as e:
            print(f"{label}\tFAILED to load: {str(e)[:120]}", flush=True); continue
        cfg = timm.data.resolve_model_data_config(net)
        mean, std = np.array(cfg["mean"], dtype=np.float32), np.array(cfg["std"], dtype=np.float32)
        side = cfg["input_size"][-1]
        if "img_size" in extra: side = extra["img_size"]
        params = sum(p.numel() for p in net.parameters()) / 1e6
        row = {"model": label, "params_m": round(params, 1)}
        for set_name, items in sets:
            xs = []
            for f, _, _ in items:
                im = Image.open(f).convert("RGB")
                if im.size != (side, side): im = im.resize((side, side), Image.BICUBIC)
                xs.append((np.asarray(im, dtype=np.float32) / 255 - mean) / std)
            x = torch.from_numpy(np.stack(xs)).permute(0, 3, 1, 2).to(device)
            with torch.no_grad():
                e = torch.cat([net(x[i:i + 32]) for i in range(0, len(x), 32)]).float().cpu().numpy()
            e /= np.linalg.norm(e, axis=1, keepdims=True)
            sims = e @ e.T
            pos, neg = [], []
            for i, j in itertools.combinations(range(len(items)), 2):
                if items[i][1] != items[j][1]: continue
                (pos if items[i][2] == items[j][2] else neg).append(float(sims[i, j]))
            t5, thr5 = tar(pos, neg, 0.05); t1, thr1 = tar(pos, neg, 0.01)
            row[set_name] = dict(pairs=[len(pos), len(neg)], auc=round(float(auc(pos, neg)), 3), right_at_5pct=round(t5, 3), thr5=round(thr5, 2),
                                 right_at_1pct=round(t1, 3), thr1=round(thr1, 2), same_p50=round(float(np.median(pos)), 2),
                                 alike_p50=round(float(np.median(neg)), 2), alike_max=round(float(max(neg)), 2),
                                 right_above_every_lookalike=round(float((np.asarray(pos) > max(neg)).mean()), 3))
        row["seconds"] = round(time.time() - t0, 1)
        print(json.dumps(row), flush=True)
        del net

main()
