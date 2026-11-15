"""Private Eye results browser (Databricks App).

Pick a test photo and see the question a blind person asked, the reference answer, and what each
model configuration said, with the grade gpt-6.1-sol gave it. Photos come from the Unity Catalog
volume; answers and grades from the workspace.eyes tables. Runs as the app's service principal.
"""
import html
import os

import pandas as pd
import streamlit as st
from databricks import sql
from databricks.sdk import WorkspaceClient
from databricks.sdk.core import Config

S = "workspace.eyes"
VOL = "/Volumes/workspace/eyes/files/photos"
COLORS = {"right": "#3BA65E", "partly": "#E8A838", "wrong": "#D9534F"}

st.set_page_config(page_title="Private Eye results", layout="wide")
cfg = Config()
w = WorkspaceClient()


@st.cache_resource
def connection():
    return sql.connect(server_hostname=cfg.host.replace("https://", "").rstrip("/"),
                       http_path="/sql/1.0/warehouses/%s" % os.environ["DATABRICKS_WAREHOUSE_ID"],
                       credentials_provider=lambda: cfg.authenticate)


@st.cache_data(ttl=600, show_spinner="Loading results from Unity Catalog...")
def query(statement):
    with connection().cursor() as c:
        c.execute(statement)
        return c.fetchall_arrow().to_pandas()


@st.cache_data(ttl=3600, show_spinner=False)
def photo(path):
    try:
        return w.files.download(path).contents.read()
    except Exception:
        return None


def chip(grade):
    return '<span style="background:%s;color:white;padding:2px 10px;border-radius:10px;font-size:0.85em">%s</span>' % (
        COLORS.get(grade, "#8A8F98"), html.escape(str(grade or "not graded")))


def answers_table(rows, columns):
    head = "".join("<th style='text-align:left;padding:6px 10px'>%s</th>" % c for c in columns)
    body = ""
    for r in rows:
        body += "<tr>" + "".join("<td style='padding:6px 10px;vertical-align:top'>%s</td>" % c for c in r) + "</tr>"
    st.markdown("<table style='width:100%%;border-collapse:collapse'><tr>%s</tr>%s</table>" % (head, body), unsafe_allow_html=True)


st.title("Private Eye: what the phone model says, photo by photo")
st.caption("On-device model: LFM3-VL-2B and Witness-2B, our fine-tune of it. Grades by gpt-6.1-sol through Unity Gateway. "
           "Photos, labels, answers and grades are served from Unity Catalog (workspace.eyes).")
tab_results, tab_taps = st.tabs(["Questions", "Taps: what is in front of me?"])

with tab_results:
    res = query("SELECT test_set, config, label, sort_order, family, id, photo_path, question, answerable, answer_type, "
                "reference_answer, answer, grade, declined, reason FROM %s.eval_results" % S)
    left, right = st.columns([1, 3])
    with left:
        test_set = st.radio("Test set", ["vizwiz500", "phone42"],
                            format_func=lambda t: "VizWiz, 500 photos by blind people" if t == "vizwiz500" else "Our phone testing, 42 frames")
        view = st.selectbox("Show", ["All photos", "Stock wrong, Witness-2B right", "Witness-2B wrong",
                                     "Photo cannot answer the question", "Stock invented an answer"])
        family = st.multiselect("Model families", sorted(res["family"].dropna().unique()),
                                default=[f for f in sorted(res["family"].dropna().unique()) if f != "Other 2B-class model"])
    d = res[res.test_set == test_set]
    wide = d.pivot_table(index="id", columns="config", values="grade", aggfunc="first")
    stock = wide["A_app_768"] if "A_app_768" in wide else pd.Series(dtype=str)
    v2 = wide["G_ft_v2_plain"] if "G_ft_v2_plain" in wide else pd.Series(dtype=str)
    info = d.drop_duplicates("id").set_index("id")
    ids = list(info.index)
    if view == "Stock wrong, Witness-2B right":
        ids = [i for i in ids if stock.get(i) == "wrong" and v2.get(i) == "right"]
    elif view == "Witness-2B wrong":
        ids = [i for i in ids if v2.get(i) == "wrong"]
    elif view == "Photo cannot answer the question":
        ids = [i for i in ids if info.loc[i, "answerable"] == "no"]
    elif view == "Stock invented an answer":
        ids = [i for i in ids if info.loc[i, "answerable"] == "no" and stock.get(i) == "wrong"]
    ids = sorted(ids)
    with left:
        st.write("%d photos match" % len(ids))
        key = "pos_%s_%s" % (test_set, view)
        pos = st.session_state.get(key, 0)
        b1, b2 = st.columns(2)
        if b1.button("Previous", use_container_width=True) and pos > 0:
            pos -= 1
        if b2.button("Next", use_container_width=True) and pos < len(ids) - 1:
            pos += 1
        st.session_state[key] = pos = min(pos, max(0, len(ids) - 1))
    if not ids:
        st.info("No photos match this view.")
    else:
        qid = ids[pos]
        row = info.loc[qid]
        with left:
            st.write("Photo %d of %d (id %s)" % (pos + 1, len(ids), qid))
        with right:
            c1, c2 = st.columns([2, 3])
            with c1:
                data = photo(row["photo_path"]) if row["photo_path"] else None
                if data:
                    st.image(data, use_container_width=True)
                else:
                    st.info("This frame is not stored in the volume.")
            with c2:
                st.subheader(row["question"])
                if row["answerable"] == "no":
                    st.markdown("**Reference:** the photo cannot answer this. A good reply says so and what to do.")
                else:
                    st.markdown("**Reference answer:** %s" % html.escape(str(row["reference_answer"])))
                st.caption("Kind of question: %s" % str(row["answer_type"]).replace("_", " "))
                rows = d[(d.id == qid) & (d.family.isin(family))].sort_values("sort_order")
                answers_table([(html.escape(str(r.label)), html.escape(str(r.answer)) or "<i>(said nothing)</i>", chip(r.grade),
                                html.escape(str(r.reason or ""))) for r in rows.itertuples()],
                              ["Configuration", "Answer", "Grade", "Judge's note"])

with tab_taps:
    taps = query("SELECT image, source, label, model, reply FROM %s.tap_comparison" % S)
    images = sorted(taps["image"].unique())
    st.write("%d photos held out of training. The label is what a sighted guide would say on a tap." % len(images))
    n = st.slider("Photo", 1, len(images), 1)
    img = images[n - 1]
    t = taps[taps.image == img]
    folder = "phone_train" if t["source"].iloc[0] == "phone" else "coco_768"
    c1, c2 = st.columns([2, 3])
    with c1:
        data = photo("%s/%s/%s" % (VOL, folder, img))
        if data:
            st.image(data, use_container_width=True)
        else:
            st.info("This photo is not stored in the volume.")
    with c2:
        st.markdown("**Sighted-guide label:** %s" % html.escape(str(t["label"].iloc[0])))
        order = {"LFM3-VL-2B stock (app tap path)": 0, "Fine-tune v1": 1, "Witness-2B": 2}
        t = t.assign(o=t["model"].map(order).fillna(9)).sort_values("o")
        answers_table([(html.escape(str(r.model)), html.escape(str(r.reply))) for r in t.itertuples()], ["Model", "Reply to a tap"])
