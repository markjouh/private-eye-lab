"""Build the Devpost gallery images for Private Eye (3:2, 1500x1000 design px, rendered at 2x).

Usage: uv run --with pillow python3 -I build.py
Writes pages/*.html here and JPGs to ~/Documents/s26-eyes-lab/pitch/devpost-images/.
Numbers come from eval/others_summary.json (sample answers and grades) and the counts below
(every model on the bare question, graded by gpt-6.1-sol).
"""
import html, json, os, subprocess
from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
LAB = "/Users/mark/Documents/s26-eyes-lab"
DECK_IMG = "/private/tmp/claude-501/-Users-mark--claude-spares-spare-bPLub9/45bb31f6-71b4-4d59-a5a3-ae4de73fe687/scratchpad/deck/img"
OUT = os.path.join(LAB, "pitch", "devpost-images")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
for d in ("pages", "img"):
    os.makedirs(os.path.join(HERE, d), exist_ok=True)
os.makedirs(OUT, exist_ok=True)

S = json.load(open(os.path.join(LAB, "databricks/eval/others_summary.json")))


def esc(t):
    return html.escape(t.replace("'", "’"), quote=False)


def photo(sid):
    dst = os.path.join(HERE, "img", "s-%s.jpg" % sid)
    im = ImageOps.exif_transpose(Image.open(os.path.join(LAB, "pitch/samples/VizWiz_val_%s.jpg" % sid))).convert("RGB")
    ImageOps.fit(im, (480, 640), Image.LANCZOS).save(dst, quality=90)
    return "../img/s-%s.jpg" % sid


def frame(name):
    dst = os.path.join(HERE, "img", name)
    Image.open(os.path.join(DECK_IMG, name)).convert("RGB").save(dst, quality=92)
    return "../img/" + name


DOTS = '<svg width="{w}" height="{h}" viewBox="0 0 372 398"><circle cx="90" cy="90" r="90" fill="{c}"/><circle cx="90" cy="308" r="90" fill="{c}"/><circle cx="282" cy="199" r="90" fill="{c}"/></svg>'

CSS = """
* { margin: 0; box-sizing: border-box; }
body { width: 1500px; height: 1000px; overflow: hidden; background: #000; }
.page { width: 1500px; height: 1000px; position: relative; background: #000; color: #f5f3ea; padding: 58px 70px 0; display: flex; flex-direction: column; gap: 22px;
  font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; font-weight: 700; }
h1 { font-size: 52px; line-height: 1.08; letter-spacing: -1.6px; color: #ffd600; }
.sub { font-size: 23px; font-weight: 500; line-height: 1.38; color: #d4d2c7; max-width: 1300px; }
.cap { font-size: 16px; letter-spacing: 2.4px; color: #b3b1a6; }
.foot { position: absolute; left: 70px; right: 70px; bottom: 30px; display: flex; justify-content: space-between; align-items: center; font-size: 18px; font-weight: 500; color: #b3b1a6; }
.brand { display: flex; align-items: center; gap: 10px; font-weight: 700; }
.yellow { background: #ffd600; color: #000; }
.yellow .foot { color: #000; }

/* what it does */
.cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 24px; }
.card { background: #1a1a1a; border-radius: 20px; overflow: hidden; display: flex; flex-direction: column; }
.card img { width: 100%; height: 392px; object-fit: cover; display: block; }
.ctext { padding: 16px 18px 20px; display: flex; flex-direction: column; gap: 8px; }
.heard { font-size: 19px; font-weight: 500; line-height: 1.3; color: #b3b1a6; }
.reply { font-size: 22px; line-height: 1.28; color: #ffd600; }
.also { font-size: 21px; font-weight: 500; line-height: 1.4; color: #d4d2c7; }

/* samples */
.srow { display: grid; grid-template-columns: 141px 256px 1fr 290px; gap: 26px; align-items: center; }
.srow img { width: 141px; height: 188px; object-fit: cover; border-radius: 10px; display: block; }
.q { font-size: 25px; line-height: 1.22; }
.shows { font-size: 18px; font-weight: 500; line-height: 1.32; color: #b3b1a6; margin-top: 10px; }
.rivals { display: grid; grid-template-columns: 26px 168px 1fr; row-gap: 7px; align-items: baseline; }
.mk { font-size: 18px; } .mname { font-size: 17px; font-weight: 500; color: #b3b1a6; }
.mans { font-size: 20px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ours { border: 3px solid #ffd600; border-radius: 14px; padding: 16px 18px 18px; display: flex; flex-direction: column; gap: 8px; }
.ours .cap { color: #ffd600; }
.oans { font-size: 26px; line-height: 1.22; color: #ffd600; }
.heads { margin-bottom: -8px; }
.rule { height: 1px; background: #2a2a2a; }

/* results */
.duo { display: grid; grid-template-columns: 236px 600px 1fr; gap: 12px 34px; align-items: center; }
.chead { font-size: 24px; line-height: 1.2; } .cnote { font-size: 17px; font-weight: 500; color: #b3b1a6; margin-top: 6px; line-height: 1.3; }
.legend { display: flex; gap: 18px; margin-top: 8px; font-size: 17px; color: #b3b1a6; }
.key { display: flex; align-items: center; gap: 7px; } .sw { width: 16px; height: 16px; border-radius: 3px; }
.mlabel { font-size: 21px; color: #b3b1a6; }
.sbar { height: 46px; display: flex; gap: 3px; }
.seg { height: 46px; border-radius: 4px; min-width: 0; overflow: hidden; font-size: 20px; line-height: 46px; color: #000; text-align: center; }
.s1 { background: #ffd600; } .s2 { background: #a89020; } .s3 { background: #5c5c5c; color: #f5f3ea; } .s4 { background: #ff5d5d; }
.track { height: 46px; display: flex; align-items: center; gap: 12px; }
.bar { height: 46px; background: #ff5d5d; border-radius: 4px; } .val { font-size: 21px; }
.takes { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; }
.take { background: #1a1a1a; border-radius: 16px; padding: 20px 24px; display: flex; gap: 18px; align-items: center; }
.big { font-size: 58px; letter-spacing: -2px; color: #ffd600; line-height: 1; }
.ttext { font-size: 19px; font-weight: 500; line-height: 1.34; color: #d4d2c7; }

/* pipeline */
.stats { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.flow { display: grid; grid-template-columns: 1fr 36px 1fr 36px 1fr; gap: 10px; align-items: stretch; }
.step { background: #1a1a1a; border-radius: 14px; padding: 16px 20px 18px; display: flex; flex-direction: column; gap: 5px; }
.step .cap { color: #ffd600; } .hot { border: 3px solid #ffd600; }
.st { font-size: 24px; line-height: 1.15; } .sd { font-size: 17.5px; font-weight: 500; line-height: 1.34; color: #c9c7bc; }
.arrow { font-size: 34px; color: #ffd600; align-self: center; text-align: center; }
table { border-collapse: collapse; width: 100%; font-size: 19px; }
th { text-align: right; font-size: 16px; letter-spacing: 1.6px; color: #b3b1a6; padding: 0 16px 8px; }
th:first-child, td:first-child { text-align: left; padding-left: 0; }
td { text-align: right; padding: 12px 16px; border-top: 1px solid #2a2a2a; font-size: 22px; }
td:first-child { font-size: 19px; font-weight: 500; color: #d4d2c7; }

/* how it works */
.parts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
.io { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.iobox { border: 2px solid #3a3a3a; border-radius: 14px; padding: 14px 20px; display: flex; flex-direction: column; gap: 4px; }
.speed { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
.sp { display: flex; flex-direction: column; gap: 4px; } .spn { font-size: 46px; letter-spacing: -1.5px; color: #ffd600; line-height: 1; }

/* cover */
.cover { padding: 0 90px; justify-content: center; gap: 56px; }
.crow { display: flex; align-items: center; justify-content: space-between; }
.title { font-size: 168px; line-height: 0.95; letter-spacing: -6px; color: #000; }
.lead { font-size: 44px; letter-spacing: -0.8px; line-height: 1.15; margin-top: 26px; }
.points { display: grid; grid-template-columns: repeat(3, 1fr); gap: 36px; }
.point { border-top: 5px solid #000; padding-top: 18px; font-size: 27px; line-height: 1.25; }
.anat { background: #1a1a1a; border-radius: 14px; padding: 18px 22px 20px; display: flex; flex-direction: column; gap: 12px; }
.chunks { display: grid; grid-template-columns: 1fr 0.62fr 1.25fr; gap: 14px; }
.chunk { border-top: 4px solid #ffd600; padding-top: 10px; display: flex; flex-direction: column; gap: 6px; }
.csay { font-size: 23px; line-height: 1.25; color: #ffd600; } .cwho { font-size: 17px; font-weight: 500; color: #b3b1a6; }
.y { color: #ffd600; } .r { color: #ff5d5d; } .g { color: #b3b1a6; }
"""


def page(name, body, cls="", note=""):
    dot = "#000000" if "yellow" in cls else "#ffd600"
    foot = "" if "cover" in cls else '<div class="foot"><div class="brand">%s<span>Private Eye</span></div><span>%s</span></div>' % (DOTS.format(w=21, h=22, c=dot), note)
    doc = '<!doctype html><meta charset="utf-8"><style>%s</style><div class="page %s">%s%s</div>' % (CSS, cls, body, foot)
    open(os.path.join(HERE, "pages", name + ".html"), "w", encoding="utf-8").write(doc)
    return name


pages = []

# 1. Cover
pages.append(page("01-private-eye", """
<div class="crow"><div><div class="title">Private Eye</div><div class="lead">An assistant for blind people that runs<br>entirely on the iPhone</div></div>%s</div>
<div class="points">
<div class="point">Point the phone, tap, and it tells you what’s there, out loud</div>
<div class="point">Remembers your people and your own things</div>
<div class="point">Witness-2B, our fine-tuned model, makes things up 7× less than any other its size</div>
</div>""" % DOTS.format(w=400, h=428, c="#000000"), cls="yellow cover"))

# 2. What it does
CARDS = [("DESCRIBE", "Tap", "Canon EOS camera with a zoom lens on the desk. Laptop behind it, to the right.", "app-tap-camera.jpg"),
         ("FIND ANYTHING", "“Watch for a T-shirt that has code on it”", "Found a t-shirt that has code on it.", "app-find-tshirt.jpg"),
         ("KNOWS YOUR PEOPLE", "Tap", "Elias to your right. Charles ahead. 3 people in view. Two people walking on sidewalk, shopping bags.", "app-mem-street.jpg"),
         ("KNOWS YOUR THINGS", "Tap", "Your water bottle. Sleep mask.", "app-mem-bottle3.jpg")]
cards = "".join('<div class="card"><img src="%s"><div class="ctext"><div class="cap y">%s</div><div class="heard">%s</div><div class="reply">“%s”</div></div></div>'
                % (frame(f), lab, heard, esc(rep)) for lab, heard, rep, f in CARDS)
pages.append(page("02-what-it-does", """
<h1>Point, tap, and it tells you what’s there</h1>
<div class="sub">Four real moments from the app’s own log: what the camera saw, what the user did, and what Private Eye said out loud. Everything runs on the phone, with no upload and no account.</div>
<div class="cards">%s</div>
<div class="also">Also: hold and ask any question · reads labels, signs and screens · “How far is that?” from LiDAR · tells you where you last left your things</div>
""" % cards, note="Camera frames and replies from the app’s debug log"))

# 3 and 4. Samples: same photo, same question, seven models
RIVALS = [("LFM3-VL-2B", "LFM3-VL-2B (stock)"), ("Qwen3.5-2B", "Qwen3.5-2B"), ("Qwen3-VL-2B", "Qwen3-VL-2B"),
          ("Gemma 4 E2B", "Gemma 4 E2B"), ("SmolVLM2-2.2B", "SmolVLM2-2.2B"), ("InternVL3.5-2B", "InternVL3.5-2B")]
OURS = "Private Eye fine-tune (LFM3-VL-2B)"
MARK = {"wrong": ("✕", "r"), "right": ("✓", ""), "partly": ("~", "")}


def sample_page(name, title, sub, items):
    rows = []
    for sid, q, shows in items:
        s = S["samples"][sid]
        cells = ""
        for key, label in RIVALS:
            a = s["answers"][key]
            m, c = MARK[a["grade"]]
            cells += '<div class="mk %s">%s</div><div class="mname">%s</div><div class="mans %s">%s</div>' % (c, m, label, c, esc(a["text"].replace("\n", " ")))
        assert s["answers"][OURS]["grade"] == "right", sid
        rows.append('<div class="srow"><img src="%s"><div><div class="q">“%s”</div><div class="shows">%s</div></div><div class="rivals">%s</div>'
                    '<div class="ours"><div class="cap">WITNESS-2B</div><div class="oans">“%s”</div></div></div>'
                    % (photo(sid), esc(q), esc(shows), cells, esc(s["answers"][OURS]["text"])))
    heads = '<div class="srow heads"><div class="cap">PHOTO</div><div class="cap">A BLIND USER ASKED</div><div class="cap">SIX OTHER 2B MODELS ANSWERED</div><div class="cap y">OURS ANSWERED</div></div>'
    body = '<h1>%s</h1><div class="sub">%s</div>%s%s' % (title, sub, heads, '<div class="rule"></div>'.join(rows))
    return page(name, body, note="✕ graded wrong · ✓ graded right · ~ partly right · photos and questions from VizWiz, grades by gpt-6.1-sol")


pages.append(sample_page("03-it-makes-things-up", "When a small model can’t see, it makes things up",
    "Blind users can’t check their shot, so many photos don’t contain the answer. Asked anyway, most 2-billion-parameter models invent one. Witness-2B, our fine-tune, says what is wrong and what to do about it.",
    [("00001201", "What is my blood pressure reading?", "The display is half out of frame and washed out by glare. No reading is legible."),
     ("00004049", "How much sodium is in this package?", "The front corner of a cookie box. The nutrition panel is not in the photo."),
     ("00002903", "What kind of medication is in this bottle?", "The side of a pill bottle, too blurred to read.")]))

pages.append(sample_page("04-more-examples", "Same photo, same question, seven models",
    "Three more questions that the photo cannot answer. A made-up weight, product key or recipe is worse than no answer, because the person asking has no way to check it.",
    [("00003286", "Can you tell me how much I weigh please?", "The scale’s display shows dashes, not a weight."),
     ("00000719", "What are the numbers on this product key?", "A blurred label on a black pouch. No characters are legible."),
     ("00002762", "Cooking directions.", "The front of a frozen meal box. The directions are on another side.")]))

# 5. Results (bare question to every model; counts of 500: right, partly, declined an answerable photo, wrong; invented of 115)
MODELS = [("Witness-2B (ours)", 332, 73, 30, 65, 9), ("Qwen3.5-2B", 250, 75, 1, 174, 92), ("Qwen3-VL-2B", 243, 97, 2, 158, 81),
          ("LFM3-VL-2B (stock)", 226, 100, 8, 166, 67), ("SmolVLM2-2.2B", 225, 94, 27, 154, 66), ("Gemma 4 E2B", 196, 107, 7, 190, 65),
          ("InternVL3.5-2B", 195, 109, 3, 193, 85)]
rows = ""
for i, (name, a, b, c, d, inv) in enumerate(MODELS):
    assert a + b + c + d == 500
    segs = ""
    for cls, n, always in (("s1", a, True), ("s2", b, False), ("s3", c, False), ("s4", d, True)):
        if n == 0:
            continue
        pct = round(n / 5)
        segs += '<div class="seg %s" style="flex:%d">%s</div>' % (cls, n, ("%d%%" % pct) if (always or pct >= 5) else "")
    ip = round(inv / 115 * 100)
    rows += '<div class="mlabel %s">%s</div><div class="sbar">%s</div><div class="track"><div class="bar" style="width:%.1f%%"></div><div class="val %s">%d%%</div></div>' % (
        "y" if i == 0 else "", name, segs, ip * 0.84, "y" if i == 0 else "", ip)
legend = "".join('<div class="key"><div class="sw %s"></div>%s</div>' % (c, t) for c, t in (("s1", "Right"), ("s2", "Partly right"), ("s3", "Wrongly said “can’t tell”"), ("s4", "Wrong")))
pages.append(page("05-results", """
<h1>7× fewer made-up answers than any other 2B model</h1>
<div class="sub">We ran seven 2-billion-parameter vision models on 500 real photos taken by blind people, each with the question that person asked. 115 of those photos cannot answer the question at all.</div>
<div class="duo">
<div></div>
<div><div class="chead">Every answer to all 500 questions, graded</div><div class="legend">%s</div></div>
<div><div class="chead">Hallucinations</div><div class="cnote">How often it invents an answer on the 115 photos that can’t give one</div></div>
%s
</div>
<div class="takes">
<div class="take"><div class="big">8%%</div><div class="ttext">invented answers when the photo can’t answer. The other six models: 57%% to 80%%.</div></div>
<div class="take"><div class="big">13%%</div><div class="ttext">of all its answers are wrong. Every other model is wrong on 31%% to 39%%.</div></div>
<div class="take"><div class="big">→</div><div class="ttext">When it can’t see, it says what to do: “Glare obscures the reading. Tilt the phone.”</div></div>
</div>""" % (legend, rows), note="“Right” includes correctly saying it can’t tell · same bare question to every model · graded by gpt-6.1-sol"))

# 6. Data and Databricks pipeline
STEPS = [("1 · DATASET", "VizWiz", "20,000 photos taken by blind people, each with the question they asked and ten crowd answers.", ""),
         ("2 · AI GATEWAY", "Relabel every photo", "gpt-6.1-sol rewrites each label from the photo and the crowd’s answers. 20,000 labels for $87.", ""),
         ("3 · UNITY CATALOG", "One source of truth", "Labels, photos, grades and model versions are governed tables, so every number here can be traced.", ""),
         ("4 · FINE-TUNE, RUN 1", "20,000 examples, 13 min", "LoRA on one GPU. Invented answers fall from 58% to 9%, but it now refuses photos it could have answered.", ""),
         ("5 · JOBS + MLFLOW", "Grade every run", "One Databricks Job scores any model on 500 held-out photos. An AI/BI dashboard and Genie sit on top.", ""),
         ("6 · FINE-TUNE, RUN 2", "40,000 examples, 25 min", "Adds 19,400 tap and where-is-it examples, and rewrites 6,400 refusals to say what to do next. This is Witness-2B.", " hot")]


def flow(steps):
    out = []
    for cap, t, d, cls in steps:
        out.append('<div class="step%s"><div class="cap">%s</div><div class="st">%s</div><div class="sd">%s</div></div>' % (cls, cap, t, d))
    return '<div class="flow">%s</div>' % '<div class="arrow">→</div>'.join(out)


pages.append(page("06-data-pipeline", """
<h1>Under the model: fixing the data, on Databricks</h1>
<div class="stats">
<div class="take"><div class="big">31%%</div><div class="ttext">of the photos can’t fully answer their question, and 20%% can’t answer it at all. They are blurry, dark or miss the thing, because the person taking them can’t check the shot.</div></div>
<div class="take"><div class="big">51%%</div><div class="ttext">of the crowd-written labels needed work. Relabelling every photo overturned 14%% of them and refined another 37%%.</div></div>
</div>
%s%s
<table>
<tr><th>WHAT EACH TRAINING RUN CHANGED</th><th>STOCK LFM3</th><th>RUN 1</th><th>RUN 2 = WITNESS-2B</th></tr>
<tr><td>Invents an answer when the photo can’t give one</td><td class="r">58%%</td><td>9%%</td><td class="y">8%%</td></tr>
<tr><td>Refuses a photo it could have answered (of 385)</td><td>10</td><td class="r">71</td><td class="y">37</td></tr>
<tr><td>Scene descriptions that say where things are</td><td>81%%</td><td class="r">62%%</td><td class="y">82%%</td></tr>
<tr><td>Fully right answers, all 500 questions</td><td>45%%</td><td>65%%</td><td class="y">66%%</td></tr>
</table>""" % (flow(STEPS[:3]), flow(STEPS[3:])), note="Run 1 fixed the made-up answers and broke two other things. Grading every run is how we caught it."))

# 7. How it works on the phone
PARTS = [("LANGUAGE MODEL", "Witness-2B", "Our fine-tune of LFM3-VL-2B, 4-bit, run with llama.cpp. Answers every question, describes the scene on a tap, and judges each look during a search."),
         ("DETECTION + SEGMENTATION", "YOLOE", "Finds people and objects in every frame and cuts out the thing you are teaching it, so memory stores the object and not the background."),
         ("FACE MEMORY", "ArcFace", "Say “This is Sarah” once. After that the app names her from an embedding of her face, with her distance."),
         ("BELONGING MEMORY", "DINOv3", "Say “Remember this as my water bottle”. It then tells your bottle from any other, and recalls where and when it last saw it."),
         ("DISTANCE", "LiDAR", "“How far is that?” and the distances in replies are measured in feet, not guessed by the model."),
         ("READING, HEARING, SPEAKING", "On-device speech and text", "Text recognition reads labels and signs. Speech recognition and the voice also run on the phone.")]
parts = "".join('<div class="step"><div class="cap">%s</div><div class="st">%s</div><div class="sd">%s</div></div>' % p for p in PARTS)
pages.append(page("07-how-it-works", """
<h1>How it works: every model runs on the phone</h1>
<div class="sub">An iPhone 17 Pro, its camera, LiDAR and microphone, and five models. No upload, no account, no signal needed.</div>
<div class="parts">%s</div>
<div class="anat"><div class="cap">ANATOMY OF ONE REPLY TO A TAP, AND WHICH PART SAID WHAT</div><div class="chunks"><div class="chunk"><div class="csay">“Elias to your right. Charles ahead.”</div><div class="cwho">Face memory names the people it knows</div></div><div class="chunk"><div class="csay">“3 people in view.”</div><div class="cwho">The detector counts everyone</div></div><div class="chunk"><div class="csay">“Two people walking on sidewalk, shopping bags.”</div><div class="cwho">Witness-2B describes the scene</div></div></div></div>
<div class="speed">
<div class="sp"><div class="spn">1 s</div><div class="ttext">to load the language model</div></div>
<div class="sp"><div class="spn">0.7 s</div><div class="ttext">to read a camera frame, started the moment you press</div></div>
<div class="sp"><div class="spn">40–50</div><div class="ttext">tokens a second while it speaks</div></div>
<div class="sp"><div class="spn">0.26 s</div><div class="ttext">from the end of your question to its first words (median of 54)</div></div>
</div>
<div class="also">The language model only ever gets the photo and the question. Names, distances and locations come from the other parts.</div>
""" % parts, note="Speeds measured on the phone"))

# Render
for name in pages:
    png = os.path.join(HERE, "pages", name + ".png")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2", "--window-size=1500,1000",
                    "--screenshot=" + png, "file://" + os.path.join(HERE, "pages", name + ".html")], capture_output=True)
    im = Image.open(png).convert("RGB")
    jpg = os.path.join(OUT, name + ".jpg")
    im.save(jpg, quality=92, optimize=True)
    im.resize((1200, 800), Image.LANCZOS).save(os.path.join(HERE, "pages", name + "_s.png"))
    print("%s %s %d KB" % (name, im.size, os.path.getsize(jpg) // 1024))
