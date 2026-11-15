"""Run any llama.cpp vision model over the two test sets, to compare it with LFM3 and the fine-tune.

Usage:
  uv run --with pillow --with requests python3 run_other_model.py NAME model.gguf mmproj.gguf [--styled]
         [--port 8091] [--parallel 4] [--limit N]

Each model is served by llama-server (the same llama.cpp build as the app, b12383) with its own chat
template, and is sent what eyes-cli sends LFM3: the app's system prompt, the photo scaled to 768 px on
its long side, then the question. Thinking is switched off, as it is in the app.

  plain (default)  the question alone: the same input as runs D_plain_768 and G_ft_*_plain.
  --styled         the question plus the app's instruction for that kind of question. Kinds are read
                   from the baseline logs (runs/A.log, runs/pA.log), so they are the app's own choice.
                   The app's text filter is NOT applied: this measures what prompting alone gets.

Sampling is the app's: temp 0.1, top-k 50, repeat penalty 1.1, seed 1234, 160 new tokens at most
(400 for a styled "read" question, as in the app).

Writes eval/runs/NAME.tsv and eval/runs/phone_NAME.tsv (tag, words, answer) for judge_local.py, plus
eval/runs/NAME.meta.json (speed and length).
"""
import argparse, base64, concurrent.futures as cf, io, json, os, re, subprocess, sys, time

import requests
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
EV = os.path.join(HERE, "eval")
RUNS = os.path.join(EV, "runs")
SERVER = "/Users/mark/Documents/eyes/Vendor/macbin/llama-b12383/llama-server"

# Copied from the app (Eyes/LLM/AnswerStyle.swift).
SYSTEM = ("You are a sighted guide for a blind person. They show you what their phone camera sees and ask a "
          "question. Answer in as few words as you can, without full sentences.")
SUFFIX = {
    "read": "Read the text exactly as written.",
    "count": "Answer with the number and what, like \"Three umbrellas.\"",
    "locate": "Name it and say where it is in a few words with left, right or ahead, like \"Hat on shelf, left.\" "
              "If it is not in view, say \"Not visible.\"",
    "pick": "Say which one by where it is and its shape or size, not its color, like \"The left one, the shorter one.\"",
    "yesNo": "Answer yes or no, then a few words, like \"Yes, on shelf, left.\" or \"No.\"",
    "person": "Describe only hair, clothing and what they are doing, like \"Short gray hair, green jacket, reading a book.\"",
    "describe": "Name the nearest things and where they are in a few words, like \"Bed ahead, lamp left, door right.\"",
    "object": "Say what it is. If it has a label of its own, read it, like \"Shampoo bottle, Head and Shoulders, 13 ounces.\"",
    "general": "Answer in a short, specific phrase, like \"Round metal tin.\" or \"Reading a book.\"",
}


def read_pairs(path):
    out = []
    for line in open(path, encoding="utf-8"):
        f = line.rstrip("\n").split("\t")
        if len(f) >= 3 and not line.startswith("#"):
            out.append((f[0], f[1], f[2].strip()))
    return out


def read_kinds(log):
    kinds = {}
    for m in re.finditer(r"^\[(\S+) \S+ \d+x\d+, (\w+)\] Q:", open(log, encoding="utf-8").read(), re.M):
        kinds[m.group(1)] = m.group(2)
    return kinds


def data_uri(path, side=768):
    im = Image.open(path).convert("RGB")
    scale = min(1.0, side / max(im.size))
    if scale < 1.0:
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


class Runner:
    def __init__(self, port, styled, kinds, repeat_penalty=1.1):
        self.url = "http://127.0.0.1:%d" % port
        self.styled, self.kinds, self.repeat_penalty = styled, kinds, repeat_penalty
        self.merge_system = False

    def ask(self, pair):
        tag, image, question = pair
        kind = self.kinds.get(tag, "general")
        text = question + ("\n" + SUFFIX[kind] if self.styled else "")
        limit = 400 if (self.styled and kind == "read") else 160
        img = {"type": "image_url", "image_url": {"url": data_uri(image)}}
        last = ""
        for attempt in range(4):
            if self.merge_system:
                messages = [{"role": "user", "content": [img, {"type": "text", "text": SYSTEM + "\n\n" + text}]}]
            else:
                messages = [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": [img, {"type": "text", "text": text}]}]
            body = {"messages": messages, "temperature": 0.1, "top_k": 50, "repeat_penalty": self.repeat_penalty, "seed": 1234,
                    "max_tokens": limit, "cache_prompt": False,
                    "chat_template_kwargs": {"enable_thinking": False}}
            try:
                r = requests.post(self.url + "/v1/chat/completions", json=body, timeout=300)
                if r.status_code != 200:
                    last = "%d %s" % (r.status_code, r.text[:300])
                    if "system" in r.text.lower() and not self.merge_system:
                        self.merge_system = True   # template has no system role: put it in the user turn
                    time.sleep(1)
                    continue
                d = r.json()
                msg = d["choices"][0]["message"]
                answer = re.sub(r"<think>.*?(</think>|$)", "", msg.get("content") or "", flags=re.S)
                answer = " ".join(answer.split())
                t = d.get("timings", {})
                return tag, answer, {"tok_s": t.get("predicted_per_second"), "prompt_ms": t.get("prompt_ms"),
                                     "prompt_tok": d.get("usage", {}).get("prompt_tokens"),
                                     "new_tok": d.get("usage", {}).get("completion_tokens"),
                                     "thought": bool(msg.get("reasoning_content")),
                                     "finish": d["choices"][0].get("finish_reason")}
            except Exception as e:
                last = "%s: %s" % (type(e).__name__, str(e)[:200])
                time.sleep(2)
        return tag, "", {"error": last}

    def run(self, pairs, out_path, workers):
        start = time.time()
        with cf.ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(self.ask, pairs))
        with open(out_path, "w", encoding="utf-8") as f:
            for tag, answer, _ in results:
                f.write("%s\t%d\t%s\n" % (tag, len(answer.split()), answer.replace("\t", " ")))
        errs = [m for _, _, m in results if "error" in m]
        ok = [m for _, _, m in results if "error" not in m]
        words = [len(a.split()) for _, a, m in results if "error" not in m]
        mean = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
        meta = {"n": len(results), "errors": len(errs), "first_error": errs[0]["error"] if errs else None,
                "empty": sum(1 for _, a, m in results if "error" not in m and not a),
                "seconds": round(time.time() - start), "mean_words": mean(words), "max_words": max(words or [0]),
                "mean_tok_s": mean([m["tok_s"] for m in ok if m.get("tok_s")]),
                "mean_prompt_tok": mean([m["prompt_tok"] for m in ok if m.get("prompt_tok")]),
                "hit_token_cap": sum(1 for m in ok if m.get("finish") == "length"),
                "thought": sum(1 for m in ok if m.get("thought"))}
        print(os.path.basename(out_path), json.dumps(meta), flush=True)
        return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name"); ap.add_argument("model"); ap.add_argument("mmproj")
    ap.add_argument("--styled", action="store_true")
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--repeat-penalty", type=float, default=1.1)
    ap.add_argument("--server-args", default="", help="extra llama-server flags, e.g. '--image-min-tokens 560'")
    a = ap.parse_args()

    log = open(os.path.join(RUNS, a.name + ".server.log"), "w")
    cmd = [SERVER, "-m", a.model, "--mmproj", a.mmproj, "--host", "127.0.0.1", "--port", str(a.port),
           "-c", str(8192 * a.parallel), "-np", str(a.parallel), "-ngl", "99",
           "--reasoning", "off", "--reasoning-budget", "0", "--no-webui"] + a.server_args.split()
    server = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(240):
            if server.poll() is not None:
                sys.exit("llama-server exited; see %s" % log.name)
            try:
                if requests.get("http://127.0.0.1:%d/health" % a.port, timeout=2).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            sys.exit("llama-server did not come up; see %s" % log.name)

        meta = {"model": os.path.basename(a.model), "mmproj": os.path.basename(a.mmproj), "styled": a.styled,
                "repeat_penalty": a.repeat_penalty, "server_args": a.server_args}
        for source, tsv, klog, out in (("vizwiz", "lfm3_plain.tsv", "A.log", a.name + ".tsv"),
                                       ("phone", "phone_plain.tsv", "pA.log", "phone_" + a.name + ".tsv")):
            pairs = read_pairs(os.path.join(EV, tsv))
            if a.limit:
                pairs = pairs[:a.limit]
            r = Runner(a.port, a.styled, read_kinds(os.path.join(RUNS, klog)), a.repeat_penalty)
            meta[source] = r.run(pairs, os.path.join(RUNS, out), a.parallel)
            meta[source]["system_in_user_turn"] = r.merge_system
        json.dump(meta, open(os.path.join(RUNS, a.name + ".meta.json"), "w"), indent=1)
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except Exception:
            server.kill()


if __name__ == "__main__":
    main()
