"""v2 training labels in the style agreed on 2026-11-14: what a good sighted guide would say.

Two modes, both through the Databricks gateway, both resumable:

  taps      one label per photo: the reply to a tap (one object, or a scene described nearest first
            with reach), where-is-it and which-one examples, and a not-in-view example.
  declines  rewrites the reply for VizWiz questions the photo cannot (fully) answer so that it says
            what is wrong and what to do.

  uv run --with databricks-sdk --with requests --with pillow label_v2.py taps <list.json> <image dir> <out.jsonl> --count N
  uv run --with databricks-sdk --with requests --with pillow label_v2.py declines <labels.jsonl> <image dir> <out.jsonl> --count N
Model comes from RELABEL_MODEL (default gpt-6.1-sol). Use --part i/n to split work between streams.
"""
import argparse, json, os, random, sys, threading, time
import concurrent.futures as cf

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dbx_auth
from relabel_train import encode, output_text

MODEL = os.environ.get("RELABEL_MODEL", "gpt-6.1-sol")

VOICE = """How the app talks. Its replies are spoken aloud to someone who cannot see and cannot skim, so every word costs them time, and every word should help them act:
- Say it the way a good sighted guide standing beside them would. Short sentences or noun phrases. No lead-in ("There is", "I see", "The image shows"), and no repeating the question.
- Place things relative to the person and to each other, the way you would if you were standing next to them. Left and right are as the camera sees them; do not mentally rotate the photo.
- Write each reply fresh for this photo. Someone hears these replies all day, so a stock tag repeated on item after item ("within reach", "in front of you", "directly ahead") becomes noise, and so does a sentence pattern that never varies. The order already tells them what is nearest. Mention distance only when it changes what they would do, such as something at their feet or something across the room, and then say it plainly in whatever words fit that photo.
- Colour is welcome as description ("rust-coloured fleece"). It is never the way to tell one of several similar things apart, because the listener cannot use it; use position, shape and size for that.
- People are part of the scene: say where they are and what they are doing. Never their ethnicity, skin colour, age or build, and never a name.
- Only say what you can actually make out. Do not guess at text you cannot read."""

TAP_INSTRUCTIONS = """You are writing training data for a phone app used by blind people. The person points the phone and taps, which asks "What is in front of me?". You see the frame exactly as the camera took it. Write what the app should answer.

""" + VOICE + """

Fields to return:
- usable: false if the frame is too dark, too blurred, covered or too close to make anything out; true otherwise.
- one_object: true if one thing is held up to the camera or fills most of the frame; false for a scene or a place.
- tap_reply: the answer to the tap.
  - One object: what it is, as specifically as you can see, then anything printed on it that identifies it: "Red Bull energy drink, 8.4 ounce can." "Stainless steel water bottle, lid closed."
  - A scene: nearest first. Start with what the person would touch or walk into first, then what is behind or beside it, ending with what is farthest. Anything in their way (a step, an edge, an open door, a chair pulled out) comes first. Ten to fourteen words at most, and fewer when that covers it. Two examples of the shape, whose wording you should not reuse: "Water bottle by the keyboard. Two laptops behind it, one open. Someone typing across the desk." "Two steps down to a landing. Handrail on the right. Glass door beyond."
  - Unusable: what is wrong and the one thing to do about it, in at most eight words: "Too blurry, hold still." "Too dark, turn on a light." "Camera is covered, move your finger."
- where: up to two where-is-it questions about things clearly in the photo, worded the way people speak ("Where's my mug?", "Can you find the remote?"), each with the answer: where it is, relative to them and to the things around it, in a few words: "On the desk, left of the keyboard." "Hanging on the door behind the chair." Empty when one_object is true or usable is false.
- which: if the photo shows two or more things of the same kind (bottles, cans, doors, chairs, buttons), one which-one question about them and its answer. Pick the thing out by position and by shape or size, never by colour alone: question "Which bottle is the dish soap?", answer "The right one, the taller bottle with a pump." Leave both strings empty if there is no such group or you cannot tell them apart.
- absent_question and absent_reply: a where-is-it question about an everyday thing that is definitely not in the photo but could plausibly be looked for there, and the answer. Say it is not in view. If the photo itself suggests where to look next (the counter carries on to one side, there is a bag or a drawer, the floor is out of frame), add that in a few words; otherwise stop there. Do not fall back on a generic instruction such as "pan slowly"."""

TAP_SCHEMA = {
    "type": "object",
    "properties": {
        "usable": {"type": "boolean"},
        "one_object": {"type": "boolean"},
        "tap_reply": {"type": "string"},
        "where": {"type": "array", "items": {
            "type": "object", "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
            "required": ["question", "answer"], "additionalProperties": False}},
        "which": {"type": "object", "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
                  "required": ["question", "answer"], "additionalProperties": False},
        "absent_question": {"type": "string"},
        "absent_reply": {"type": "string"},
    },
    "required": ["usable", "one_object", "tap_reply", "where", "which", "absent_question", "absent_reply"],
    "additionalProperties": False,
}

# Things people look for, offered a few at a time so the not-in-view examples do not all ask about mugs and keys.
THINGS = ["keys", "wallet", "phone", "phone charger", "glasses", "sunglasses", "mug", "water bottle", "remote control",
          "headphones", "earbuds", "backpack", "handbag", "umbrella", "jacket", "shoes", "hat", "scarf", "gloves",
          "white cane", "laptop", "tablet", "notebook", "pen", "scissors", "tape", "tissues", "napkins", "fork", "spoon",
          "knife", "plate", "bowl", "cup", "kettle", "toaster", "salt shaker", "dish towel", "sponge", "soap",
          "toothbrush", "towel", "hairbrush", "medicine bottle", "light switch", "door handle", "power outlet",
          "trash can", "recycling bin", "chair", "stool", "bench", "stairs", "elevator button", "exit sign",
          "coat hook", "mailbox", "leash", "pet bowl", "lunch box", "bus stop sign", "crosswalk button", "ticket machine"]

DECLINE_INSTRUCTIONS = """You are writing training data for a phone app used by blind people. The person took a photo and asked a question aloud. A careful reviewer has already decided that this photo cannot answer the question, or can answer only part of it. Your job is to write the reply the app should speak, so that the person knows what to do next instead of just hearing that it failed.

""" + VOICE + """

You get the photo, the question as transcribed, and the reviewer's note: whether the photo answers it partly or not at all, the main obstacle, and a draft reply.

Write `reply`:
- Not answerable: what is wrong with this photo and the one thing the person should do to fix it, as short as you can make it. Choose the action that would actually help with this photo: "Too blurry, hold still." "Label is facing away, turn the bottle." "Text is cut off at the top, move back." "Glare on the screen, tilt the phone." "Too dark, turn on a light." "Only the front of the card is showing, turn it over."
- Partly answerable: first the part that can be answered, then what to do to get the rest: "Campbell's soup. Turn the can to read the flavour."
- If the transcript is not a question about the photo: "No question heard. Ask about what the camera sees."
- Usually four to eight words; never more than twelve, and only that long when the first part is an answer. Do not add "and take another photo" or "try again": the person will. No apology, no "please", no "I".

Also return `action`: the kind of fix you chose, one of: hold_still, move_back, move_closer, turn_object, tilt_or_reduce_glare, more_light, reframe, uncover_camera, ask_again, none."""

DECLINE_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "action": {"type": "string", "enum": ["hold_still", "move_back", "move_closer", "turn_object", "tilt_or_reduce_glare",
                                             "more_light", "reframe", "uncover_camera", "ask_again", "none"]},
    },
    "required": ["reply", "action"],
    "additionalProperties": False,
}


def call(instructions, schema, text, image_path):
    out = {}
    try:
        b64 = encode(image_path)
    except Exception as e:
        return {"error": "image: %s" % e}
    payload = {
        "model": MODEL, "max_output_tokens": 2000, "instructions": instructions,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": text},
                                               {"type": "input_image", "image_url": "data:image/jpeg;base64," + b64}]}],
        "text": {"format": {"type": "json_schema", "name": "label", "schema": schema, "strict": True}},
    }
    for attempt in range(7):
        try:
            r = requests.post(dbx_auth.GATEWAY_URL, headers=dbx_auth.headers(), json=payload, timeout=180)
            if r.status_code in (429, 500, 502, 503, 504, 529):
                out = {"error": r.text[:200]}
                time.sleep(min(60, 2 ** attempt + random.random() * 2))
                continue
            if r.status_code != 200:
                return {"error": r.text[:300]}
            data = r.json()
            t = output_text(data)
            out = json.loads(t[t.find("{"):t.rfind("}") + 1])
            usage = data.get("usage") or {}
            out["in_tok"], out["out_tok"] = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
            return out
        except Exception as e:
            out = {"error": "%s: %s" % (type(e).__name__, str(e)[:200])}
            time.sleep(2 + random.random() * 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["taps", "declines"])
    ap.add_argument("source"), ap.add_argument("image_dir"), ap.add_argument("out")
    ap.add_argument("--count", type=int, default=0), ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--part", default=""), ap.add_argument("--also-done", nargs="*", default=[])
    args = ap.parse_args()

    if args.mode == "taps":
        items = [{"image": x["image"]} for x in json.load(open(args.source))]
        key = "tap_reply"
    else:
        seen, items = set(), []
        for line in open(args.source, encoding="utf-8"):
            r = json.loads(line)
            if r.get("answerable") in ("no", "partly") and r["image"] not in seen:
                seen.add(r["image"])
                items.append(r)
        key = "reply"
    random.Random(2026).shuffle(items)
    if args.count:
        items = items[: args.count]
    done = set()
    for path in [args.out] + args.also_done:
        if os.path.exists(path):
            for line in open(path):
                try:
                    r = json.loads(line)
                    if key in r:
                        done.add(r["image"])
                except Exception:
                    pass
    todo = [x for x in items if x["image"] not in done]
    if args.part:
        i, n = (int(v) for v in args.part.split("/"))
        todo = todo[i::n]
    print("%s: %d chosen, %d done, %d to do with %s" % (args.mode, len(items), len(done), len(todo), MODEL), flush=True)
    dbx_auth.headers()

    def work(x):
        path = os.path.join(args.image_dir, x["image"])
        if args.mode == "taps":
            row = {"image": x["image"], "labeller": MODEL}
            hint = ", ".join(random.Random(x["image"]).sample(THINGS, 4))
            row.update(call(TAP_INSTRUCTIONS, TAP_SCHEMA, "The person tapped. Here is the camera frame.\n"
                            "For the not-in-view example, ask about one of these if it fits the place and is not in the photo, "
                            "otherwise about something else that fits better: " + hint + ".", path))
        else:
            row = {"image": x["image"], "labeller": MODEL, "question": x["question"], "answerable": x["answerable"],
                   "answer_type": x.get("answer_type"), "old_reply": x.get("spoken_answer")}
            text = "Question as transcribed: %s\nReviewer's note: answerable = %s; main obstacle = %s; draft reply = %s" % (
                x["question"], x["answerable"], x.get("unanswerable_reason"), x.get("spoken_answer"))
            row.update(call(DECLINE_INSTRUCTIONS, DECLINE_SCHEMA, text, path))
        return row

    lock, t0, ok = threading.Lock(), time.time(), 0
    with open(args.out, "a") as out, cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for n, fut in enumerate(cf.as_completed([pool.submit(work, x) for x in todo]), 1):
            row = fut.result()
            with lock:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                ok += key in row
            if n % 200 == 0 or n == len(todo):
                print("%d/%d | %.1f/s | ok %d" % (n, len(todo), n / (time.time() - t0), ok), flush=True)
    print("DONE in %.0f s" % (time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
