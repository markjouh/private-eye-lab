"""LoRA fine-tune of LFM3-VL-2B on (photo, question) -> spoken answer. Runs on markws.

The prompt is built exactly as the Private Eye app builds it: the app's system prompt, then the
photo and the bare question in the user turn, then a direct answer with thinking switched off.
Only the language model gets LoRA weights; the vision tower and projector stay frozen, so the
app's existing mmproj file keeps working.

  python train_lfm3.py --base base --data data/train.jsonl --images data/train768 --out runs/v1
"""
import argparse, json, math, os, random, time

import torch
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModelForImageTextToText, AutoProcessor
from peft import LoraConfig, get_peft_model

SYSTEM = ("You are a sighted guide for a blind person. They show you what their phone camera sees and ask a "
          "question. Answer in as few words as you can, without full sentences.")
TARGETS = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|in_proj|out_proj|w1|w2|w3)"


def conversation(image, question, answer=None, system=True):
    msgs = [{"role": "system", "content": [{"type": "text", "text": SYSTEM}]}] if system else []
    msgs.append({"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": question}]})
    if answer is not None:
        msgs.append({"role": "assistant", "content": [{"type": "text", "text": answer}]})
    return msgs


def answer_loss(model, batch):
    """Cross-entropy on the answer tokens only. The vocabulary has 128k entries, so computing
    logits for every position (as the model's own loss does) costs gigabytes per batch."""
    core = model.base_model.model  # the original model with LoRA layers injected
    inputs = {k: v for k, v in batch.items() if k != "labels"}
    hidden = core.model(**inputs).last_hidden_state
    labels = batch["labels"][:, 1:]
    keep = labels != -100
    logits = core.lm_head(hidden[:, :-1][keep])
    return F.cross_entropy(logits.float(), labels[keep])


class Rows(Dataset):
    def __init__(self, rows, image_dir):
        self.rows, self.image_dir = rows, image_dir

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        r = self.rows[i]
        # "sys" false trains the row without the app's system prompt, so the model works either way.
        return Image.open(os.path.join(self.image_dir, r["image"])).convert("RGB"), r["question"], r["answer"], r.get("sys", True)


class Collate:
    """Tokenises whole conversations and masks everything except the assistant's answer."""

    def __init__(self, processor):
        self.p = processor
        tok = processor.tokenizer
        self.im_start = tok.convert_tokens_to_ids("<|im_start|>")
        self.header = len(tok("assistant\n<think></think>", add_special_tokens=False)["input_ids"])
        self.pad = tok.pad_token_id

    def __call__(self, batch):
        convs = [conversation(img, q, a, system) for img, q, a, system in batch]
        enc = self.p.apply_chat_template(convs, tokenize=True, return_dict=True, return_tensors="pt", padding=True)
        ids = enc["input_ids"]
        labels = ids.clone()
        for row in range(ids.shape[0]):
            starts = (ids[row] == self.im_start).nonzero().flatten()
            labels[row, : starts[-1].item() + 1 + self.header] = -100  # up to and including the assistant header
        labels[enc["attention_mask"] == 0] = -100
        enc["labels"] = labels
        return enc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="base"), ap.add_argument("--data", required=True)
    ap.add_argument("--images", required=True), ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=1.0), ap.add_argument("--bs", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-4), ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0), ap.add_argument("--val", type=int, default=300)
    ap.add_argument("--max-pixels", type=int, default=768 * 768), ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-merge", action="store_true")
    args = ap.parse_args()
    random.seed(0), torch.manual_seed(0)
    os.makedirs(args.out, exist_ok=True)

    rows = [json.loads(l) for l in open(args.data)]
    random.shuffle(rows)
    val, train = rows[: args.val], rows[args.val:]
    if args.limit:
        train = train[: args.limit]
    print(len(train), "train,", len(val), "val", flush=True)

    processor = AutoProcessor.from_pretrained(args.base, trust_remote_code=True,
                                              size={"shortest_edge": 256 * 256, "longest_edge": args.max_pixels})
    processor.tokenizer.padding_side = "right"
    model = AutoModelForImageTextToText.from_pretrained(args.base, dtype=torch.bfloat16, trust_remote_code=True).cuda()
    model = get_peft_model(model, LoraConfig(r=args.rank, lora_alpha=2 * args.rank, lora_dropout=0.0,
                                             task_type="CAUSAL_LM", target_modules=TARGETS))
    for p in model.parameters():
        if p.requires_grad:
            p.data = p.data.float()
    model.print_trainable_parameters()

    collate = Collate(processor)
    loader = DataLoader(Rows(train, args.images), batch_size=args.bs, shuffle=True, num_workers=args.workers,
                        collate_fn=collate, drop_last=True, persistent_workers=True)
    val_loader = DataLoader(Rows(val, args.images), batch_size=args.bs, num_workers=2, collate_fn=collate)

    first = next(iter(val_loader))
    keep = first["labels"][0] != -100
    print("keys:", {k: tuple(v.shape) for k, v in first.items() if hasattr(v, "shape")}, flush=True)
    print("PROMPT  :", repr(processor.tokenizer.decode(first["input_ids"][0][~keep & (first["attention_mask"][0] == 1)][-40:])))
    print("TARGET  :", repr(processor.tokenizer.decode(first["input_ids"][0][keep])), flush=True)

    total = int(len(loader) * args.epochs)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr, weight_decay=0.0)
    warm = max(1, int(0.05 * total))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: (s + 1) / warm if s < warm else 0.5 * (1 + math.cos(math.pi * (s - warm) / max(1, total - warm))))

    def evaluate():
        model.eval()
        losses = []
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
            for b in val_loader:
                b = {k: v.cuda() for k, v in b.items() if hasattr(v, "cuda")}
                losses.append(answer_loss(model, b).item())
        model.train()
        return sum(losses) / max(1, len(losses))

    print("steps:", total, "| val loss before: %.3f" % evaluate(), flush=True)
    model.train()
    step, t0, running, skipped = 0, time.time(), [], 0
    done = False
    while not done:
        for b in loader:
            b = {k: v.cuda(non_blocking=True) for k, v in b.items() if hasattr(v, "cuda")}
            try:
                with torch.autocast("cuda", dtype=torch.bfloat16):
                    loss = answer_loss(model, b)
                loss.backward()
            except torch.OutOfMemoryError:
                # A rare batch of large photos and long text; drop it rather than lose the run.
                skipped += 1
                loss = None
                del b
                opt.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                print("skipped an oversized batch (%d so far)" % skipped, flush=True)
                continue
            torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
            opt.step(), sched.step(), opt.zero_grad(set_to_none=True)
            running.append(loss.item())
            step += 1
            if step % 25 == 0 or step == total:
                el = time.time() - t0
                print("step %d/%d | loss %.3f | %.2f it/s | eta %.1f min | mem %.1f GB" % (
                    step, total, sum(running[-25:]) / len(running[-25:]), step / el, (total - step) / (step / el) / 60,
                    torch.cuda.max_memory_allocated() / 2**30), flush=True)
            if step % 500 == 0:
                model.save_pretrained(os.path.join(args.out, "lora"))  # so a crash keeps the work so far
            if step >= total:
                done = True
                break
    print("val loss after: %.3f | train time %.1f min" % (evaluate(), (time.time() - t0) / 60), flush=True)

    model.eval()
    tok = processor.tokenizer
    for r in val[:12]:
        img = Image.open(os.path.join(args.images, r["image"])).convert("RGB")
        enc = processor.apply_chat_template([conversation(img, r["question"])], tokenize=True, return_dict=True,
                                            return_tensors="pt", add_generation_prompt=True, enable_thinking=False)
        enc = {k: v.cuda() for k, v in enc.items() if hasattr(v, "cuda")}
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
            out = model.generate(**enc, max_new_tokens=40, do_sample=False)
        print("Q: %s | want: %s | got: %s" % (r["question"][:50], r["answer"],
                                              tok.decode(out[0][enc["input_ids"].shape[1]:], skip_special_tokens=True)), flush=True)

    model.save_pretrained(os.path.join(args.out, "lora"))
    if not args.no_merge:
        merged = model.merge_and_unload()
        merged.save_pretrained(os.path.join(args.out, "merged"))
        AutoProcessor.from_pretrained(args.base, trust_remote_code=True).save_pretrained(os.path.join(args.out, "merged"))
        print("saved merged model to", os.path.join(args.out, "merged"), flush=True)


if __name__ == "__main__":
    main()
