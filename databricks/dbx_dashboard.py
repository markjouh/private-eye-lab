"""Create or update the AI/BI dashboard for the project and publish it.

  uv run --with databricks-sdk dbx_dashboard.py [genie space id]
Three pages: model quality (grades from gpt-6.1-sol), data and labelling, and Unity Gateway usage read
from the system tables. Re-running updates the same dashboard (its id is kept in dashboard_id.txt).
"""
import json, os, sys

import dbx_auth
from databricks.sdk.service.dashboards import Dashboard

HERE = os.path.dirname(os.path.abspath(__file__))
ID_FILE = os.path.join(HERE, "dashboard_id.txt")
S = "workspace.eyes"
GREEN, AMBER, RED, BLUE, GREY = "#3BA65E", "#E8A838", "#D9534F", "#2272B4", "#8A8F98"
MAIN = "('A_app_768', 'G_ft_v1_plain', 'G_ft_v2_plain')"


def lines(sql):
    return [l + "\n" for l in sql.strip().split("\n")]


DATASETS = [
    ("ds_headline", "Headline numbers", """
SELECT max(CASE WHEN config = 'A_app_768' THEN right_answers END) / max(photos) AS stock_right,
       max(CASE WHEN config = 'G_ft_v2_plain' THEN right_answers END) / max(photos) AS v2_right,
       max(CASE WHEN config = 'A_app_768' THEN invented_answers END) AS stock_invented,
       max(CASE WHEN config = 'G_ft_v2_plain' THEN invented_answers END) AS v2_invented,
       max(unanswerable_photos) AS unanswerable_photos, max(photos) AS photos
FROM %(S)s.eval_summary WHERE test_set = 'vizwiz500'"""),
    ("ds_grades", "Grades by configuration", """
SELECT test_set, config, label, sort_order, family, grade, count(*) AS photos
FROM %(S)s.eval_results WHERE grade IS NOT NULL GROUP BY ALL"""),
    ("ds_others", "Phone-size models compared, each at its better prompt", """
WITH runs AS (
  SELECT CASE WHEN config IN ('D_plain_768', 'A_app_768') THEN 'LFM3-VL-2B (stock)'
              WHEN config LIKE '%%ft_v1%%' THEN 'Private Eye fine-tune v1'
              WHEN config LIKE '%%ft_v2%%' THEN 'Witness-2B'
              ELSE split_part(model, ' (', 1) END AS model,
         config, right_answers, partly, wrong, invented_answers
  FROM %(S)s.eval_summary
  WHERE test_set = 'vizwiz500' AND ungraded = 0
    AND (family <> 'LFM3-VL-2B stock' OR config IN ('D_plain_768', 'A_app_768'))
), best AS (
  SELECT model, max_by(config, right_answers) AS best_config, min(invented_answers) AS invented FROM runs GROUP BY model
)
SELECT r.model, g.grade,
       CASE g.grade WHEN 'right' THEN r.right_answers WHEN 'partly' THEN r.partly ELSE r.wrong END AS photos,
       CASE WHEN g.grade = 'wrong' THEN b.invented ELSE 0 END AS invented
FROM runs r JOIN best b ON b.model = r.model AND b.best_config = r.config
CROSS JOIN (SELECT explode(array('right', 'partly', 'wrong')) AS grade) g"""),
    ("ds_invented", "Behaviour on photos that cannot answer the question", """
SELECT CASE config WHEN 'A_app_768' THEN 'Stock model' WHEN 'G_ft_v1_plain' THEN 'Fine-tune v1' ELSE 'Witness-2B' END AS model,
       CASE WHEN grade = 'right' THEN 'Says it cannot tell' WHEN grade = 'wrong' THEN 'Invents an answer' ELSE 'Partly' END AS behaviour,
       count(*) AS photos
FROM %(S)s.eval_results
WHERE test_set = 'vizwiz500' AND answerable = 'no' AND grade IS NOT NULL AND config IN %(MAIN)s GROUP BY ALL"""),
    ("ds_types", "Right answers by question type", """
SELECT CASE config WHEN 'A_app_768' THEN 'Stock model' WHEN 'G_ft_v1_plain' THEN 'Fine-tune v1' ELSE 'Witness-2B' END AS model, replace(answer_type, '_', ' ') AS answer_type, count(*) AS photos,
       count_if(grade = 'right') / count(*) AS right_share
FROM %(S)s.eval_results
WHERE test_set = 'vizwiz500' AND answerable <> 'no' AND grade IS NOT NULL AND config IN %(MAIN)s
GROUP BY ALL HAVING count(*) >= 15"""),
    ("ds_summary", "Summary table", """
SELECT CASE test_set WHEN 'vizwiz500' THEN 'VizWiz 500' ELSE 'Phone frames 42' END AS test_set, label, photos,
       right_answers, partly, wrong, right_pct, declined_on_answerable, declined_correctly, invented_answers, mean_words, sort_order
FROM %(S)s.eval_summary WHERE ungraded = 0 ORDER BY test_set DESC, sort_order"""),
    ("ds_flips", "Photos the stock model got wrong and Witness-2B got right", """
SELECT a.id, a.question,
       coalesce(a.reference_answer, concat('(Photo cannot answer: ', replace(l.unanswerable_reason, '_', ' '), ')')) AS reference_answer,
       a.answer AS stock_answer, b.answer AS v2_answer, b.reason AS judge_note
FROM %(S)s.eval_results a JOIN %(S)s.eval_results b ON a.test_set = b.test_set AND a.id = b.id
JOIN %(S)s.eval_labels l ON l.test_set = a.test_set AND l.id = a.id
WHERE a.config = 'A_app_768' AND b.config = 'G_ft_v2_plain' AND a.grade = 'wrong' AND b.grade = 'right' AND a.test_set = 'vizwiz500'
ORDER BY a.id LIMIT 300"""),
    ("ds_data", "Data counts", """
SELECT (SELECT count(*) FROM %(S)s.photos) AS photos_stored,
       (SELECT count(*) FROM %(S)s.vizwiz_relabel_train) + (SELECT count(*) FROM %(S)s.tap_labels_v2)
         + (SELECT count(*) FROM %(S)s.declines_v2) + (SELECT count(*) FROM %(S)s.eval_labels WHERE test_set = 'vizwiz500') AS labels_written,
       (SELECT count(*) FROM %(S)s.train_mix_v2) AS train_rows_v2,
       (SELECT count_if(crowd_verdict NOT IN ('agree', 'agrees', 'correct')) / count(*) FROM %(S)s.vizwiz_relabel_train) AS crowd_changed"""),
    ("ds_mix", "Training mix v2", """
SELECT CASE kind WHEN 'answer' THEN 'Question answered' WHEN 'tap' THEN 'Tap: what is in front of me'
                 WHEN 'decline' THEN 'Useful decline' WHEN 'where' THEN 'Where is it' WHEN 'which' THEN 'Which one'
                 WHEN 'absent' THEN 'Not in view' ELSE kind END AS kind, count(*) AS train_rows
FROM %(S)s.train_mix_v2 GROUP BY ALL"""),
    ("ds_crowd", "What relabelling did to the crowd answers", """
SELECT crowd_verdict, count(*) AS photos FROM %(S)s.vizwiz_relabel_train GROUP BY ALL"""),
    ("ds_reasons", "Why a photo cannot answer its question", """
SELECT unanswerable_reason, count(*) AS photos FROM %(S)s.vizwiz_relabel_train
WHERE answerable = 'no' AND unanswerable_reason <> 'not_applicable' GROUP BY ALL"""),
    ("ds_sources", "Photos stored by set", """
SELECT photo_set, count(*) AS photos, round(sum(bytes) / 1e6, 1) AS megabytes FROM %(S)s.photos GROUP BY ALL"""),
    ("ds_taps", "Tap replies side by side", """
SELECT image, max(label) AS reference,
       max(CASE WHEN model LIKE '%%stock%%' THEN reply END) AS stock_app,
       max(CASE WHEN model = 'Fine-tune v1' THEN reply END) AS fine_tune_v1,
       max(CASE WHEN model = 'Witness-2B' THEN reply END) AS witness_2b
FROM %(S)s.tap_comparison GROUP BY image ORDER BY image"""),
    ("ds_gw", "Gateway requests", """
SELECT date_trunc('HOUR', event_time) AS hour, destination_model AS model,
       CASE WHEN status_code = 200 THEN 'Succeeded' WHEN status_code = 429 THEN 'Rate limited, retried' ELSE 'Other error' END AS outcome,
       count(*) AS requests, sum(coalesce(input_tokens, 0)) AS input_tokens, sum(coalesce(output_tokens, 0)) AS output_tokens,
       sum(CASE WHEN status_code = 200 THEN latency_ms END) / 1000.0 AS latency_seconds_total,
       count_if(status_code = 200) AS succeeded
FROM system.ai_gateway.usage WHERE service_name = 'workspace.default.openai' GROUP BY ALL"""),
    ("ds_spend", "Gateway spend", """
SELECT usage_start_time AS hour, usage_metadata.model AS model, sum(usage_quantity) AS usd
FROM system.ai_gateway.external_model_spend WHERE usage_unit = 'USD' GROUP BY ALL"""),
]


def field(name, expr=None):
    return {"name": name, "expression": expr or "`%s`" % name}


def widget(name, ds, fields, spec, pos, disagg=False, filters=None):
    q = {"datasetName": ds, "fields": fields, "disaggregated": disagg}
    if filters:
        q["filters"] = [{"expression": f} for f in filters]
    return {"widget": {"name": name, "queries": [{"name": "main_query", "query": q}], "spec": spec},
            "position": dict(zip(("x", "y", "width", "height"), pos))}


def text(name, body, pos):
    return {"widget": {"name": name, "multilineTextboxSpec": {"lines": body}},
            "position": dict(zip(("x", "y", "width", "height"), pos))}


def counter(name, ds, col, title, pos, fmt=None, agg=None, desc=None):
    fname = "%s(%s)" % (agg.lower(), col) if agg else col
    enc = {"fieldName": fname, "displayName": title}
    if fmt:
        enc["format"] = fmt
    frame = {"showTitle": True, "title": title}
    if desc:
        frame.update({"showDescription": True, "description": desc})
    return widget(name, ds, [field(fname, "%s(`%s`)" % (agg, col) if agg else None)],
                  {"version": 2, "widgetType": "counter", "encodings": {"value": enc}, "frame": frame}, pos, disagg=not agg)


def table(name, ds, cols, title, pos):
    return widget(name, ds, [field(c) for c, _ in cols],
                  {"version": 2, "widgetType": "table",
                   "encodings": {"columns": [{"fieldName": c, "displayName": d} for c, d in cols]},
                   "frame": {"showTitle": True, "title": title}}, pos, disagg=True)


PCT = {"type": "number-percent", "decimalPlaces": {"type": "max", "places": 1}}
COUNT = {"type": "number", "abbreviation": "compact", "decimalPlaces": {"type": "max", "places": 1}}
USD = {"type": "number-currency", "currencyCode": "USD", "decimalPlaces": {"type": "max", "places": 2}}
GRADES = {"type": "categorical", "sort": {"by": "custom-order", "orderedValues": ["wrong", "partly", "right"]},
          "mappings": [{"value": "right", "color": GREEN}, {"value": "partly", "color": AMBER}, {"value": "wrong", "color": RED}]}


def grade_bars(name, title, desc, pos, where):
    return widget(name, "ds_grades", [field("label"), field("grade"), field("sum(photos)", "SUM(`photos`)")],
                  {"version": 3, "widgetType": "bar",
                   "encodings": {"x": {"fieldName": "sum(photos)", "scale": {"type": "quantitative"}, "displayName": "Test photos"},
                                 "y": {"fieldName": "label", "scale": {"type": "categorical", "sort": {"by": "custom-order", "orderedValues": ORDER}},
                                       "displayName": "Configuration"},
                                 "color": {"fieldName": "grade", "scale": GRADES, "displayName": "Grade"},
                                 "label": {"show": True}},
                   "frame": {"showTitle": True, "title": title, "showDescription": True, "description": desc}}, pos, filters=where)


ORDER = ["Stock model, app prompt (as shipped)", "Stock, bare question", "Stock, prompt asking it to decline",
         "Stock, larger image (1024 px)", "Stock, 8-bit weights", "Stock, 8-bit weights and F16 projector",
         "Fine-tune v1, bare question", "Fine-tune v1, app prompt", "Witness-2B, bare question", "Witness-2B, app prompt"]
MAIN_ORDER = ["Stock model", "Fine-tune v1", "Witness-2B"]
OTHERS = ["Witness-2B", "Private Eye fine-tune v1", "LFM3-VL-2B (stock)", "Qwen3.5-2B", "Qwen3-VL-2B",
          "Gemma 4 E2B", "SmolVLM2-2.2B", "InternVL3.5-2B"]
SERIES = {"type": "categorical", "sort": {"by": "custom-order", "orderedValues": MAIN_ORDER},
          "mappings": [{"value": MAIN_ORDER[0], "color": GREY}, {"value": MAIN_ORDER[1], "color": "#7FB3E0"}, {"value": MAIN_ORDER[2], "color": BLUE}]}


def pages():
    quality = [
        text("q-head", ["# Private Eye: does fine-tuning make the on-device model more trustworthy?\n", "\n",
                        "LFM3-VL-2B runs on the phone and answers a blind person's questions about what the camera sees. "
                        "Every answer below came from the same model file and llama.cpp runtime the phone uses, and was graded by gpt-6.1-sol "
                        "through Unity Gateway against relabelled reference answers. Test sets: 500 VizWiz photos taken by blind people, "
                        "and 42 frames from our own phone testing."],
             (0, 0, 12, 3)),
        counter("k-stock", "ds_headline", "stock_right", "Stock model: right answers", (0, 3, 3, 3), PCT, desc="VizWiz 500, app as shipped"),
        counter("k-v2", "ds_headline", "v2_right", "Witness-2B: right answers", (3, 3, 3, 3), PCT, desc="VizWiz 500, same phone-size model"),
        counter("k-inv-stock", "ds_headline", "stock_invented", "Stock model: invented answers", (6, 3, 3, 3),
                desc="On photos that cannot answer the question"),
        counter("k-inv-v2", "ds_headline", "v2_invented", "Witness-2B: invented answers", (9, 3, 3, 3),
                desc="Same photos, after fine-tuning"),
        grade_bars("g-main", "Grades on the 500 VizWiz test photos", "Every configuration we measured, graded by gpt-6.1-sol", (0, 6, 7, 8),
                   ["`test_set` = 'vizwiz500'", "`family` <> 'Other 2B-class model'"]),
        widget("g-invented", "ds_invented", [field("model"), field("behaviour"), field("sum(photos)", "SUM(`photos`)")],
               {"version": 3, "widgetType": "bar",
                "encodings": {"x": {"fieldName": "model", "scale": {"type": "categorical", "sort": {"by": "custom-order", "orderedValues": MAIN_ORDER}},
                                    "displayName": "Model"},
                              "y": {"fieldName": "sum(photos)", "scale": {"type": "quantitative"}, "displayName": "Photos"},
                              "color": {"fieldName": "behaviour", "displayName": "Behaviour",
                                        "scale": {"type": "categorical",
                                                  "sort": {"by": "custom-order", "orderedValues": ["Invents an answer", "Partly", "Says it cannot tell"]},
                                                  "mappings": [{"value": "Says it cannot tell", "color": GREEN}, {"value": "Partly", "color": AMBER},
                                                               {"value": "Invents an answer", "color": RED}]}},
                              "label": {"show": True}},
                "frame": {"showTitle": True, "title": "When the photo cannot answer the question",
                          "showDescription": True, "description": "Blurry, cut off, or the thing asked about is not in the frame"}}, (7, 6, 5, 8)),
        widget("g-types", "ds_types", [field("answer_type"), field("model"), field("avg(right_share)", "AVG(`right_share`)")],
               {"version": 3, "widgetType": "bar",
                "encodings": {"x": {"fieldName": "answer_type", "scale": {"type": "categorical"}, "displayName": "Kind of question"},
                              "y": {"fieldName": "avg(right_share)", "scale": {"type": "quantitative"}, "displayName": "Right answers", "format": PCT},
                              "color": {"fieldName": "model", "scale": SERIES, "displayName": "Model"}},
                "mark": {"layout": "group"},
                "frame": {"showTitle": True, "title": "Right answers by kind of question", "showDescription": True,
                          "description": "Answerable VizWiz photos only; kinds with at least 15 photos"}}, (0, 14, 7, 7)),
        grade_bars("g-phone", "Grades on 42 frames from our own phone testing", "Small set: read as a sanity check", (7, 14, 5, 7),
                   ["`test_set` = 'phone42'", "`family` <> 'Other 2B-class model'"]),
        widget("g-others", "ds_others", [field("model"), field("grade"), field("sum(photos)", "SUM(`photos`)")],
               {"version": 3, "widgetType": "bar",
                "encodings": {"x": {"fieldName": "sum(photos)", "scale": {"type": "quantitative"}, "displayName": "Test photos"},
                              "y": {"fieldName": "model", "scale": {"type": "categorical", "sort": {"by": "custom-order", "orderedValues": OTHERS}},
                                    "displayName": "Model"},
                              "color": {"fieldName": "grade", "scale": GRADES, "displayName": "Grade"},
                              "label": {"show": True}},
                "frame": {"showTitle": True, "title": "Against other phone-size models", "showDescription": True,
                          "description": "Same 500 photos, system prompt and sampling, 4-bit weights; each model at whichever of its two prompts gets more right"}}, (0, 21, 7, 7)),
        widget("g-others-inv", "ds_others", [field("model"), field("sum(invented)", "SUM(`invented`)")],
               {"version": 3, "widgetType": "bar",
                "encodings": {"x": {"fieldName": "sum(invented)", "scale": {"type": "quantitative"}, "displayName": "Invented answers (of 115 photos)"},
                              "y": {"fieldName": "model", "scale": {"type": "categorical", "sort": {"by": "custom-order", "orderedValues": OTHERS}},
                                    "displayName": "Model"},
                              "label": {"show": True}},
                "frame": {"showTitle": True, "title": "Invented answers, by model", "showDescription": True,
                          "description": "Photos that cannot answer the question; each model at whichever of its two prompts invents less"}}, (7, 21, 5, 7)),
        table("t-summary", "ds_summary",
              [("test_set", "Test set"), ("label", "Configuration"), ("photos", "Photos"), ("right_answers", "Right"), ("partly", "Partly"),
               ("wrong", "Wrong"), ("right_pct", "Right %"), ("declined_on_answerable", "Declined though answerable"),
               ("declined_correctly", "Declined correctly"), ("invented_answers", "Invented"), ("mean_words", "Mean words")],
              "All configurations", (0, 28, 12, 9)),
        table("t-flips", "ds_flips",
              [("question", "Question asked"), ("reference_answer", "Reference answer"), ("stock_answer", "Stock model said"),
               ("v2_answer", "Witness-2B said"), ("judge_note", "Judge's note")],
              "Photos the stock model got wrong and Witness-2B got right", (0, 37, 12, 8)),
    ]
    data = [
        text("d-head", ["# Data and labelling\n", "\n",
                        "VizWiz crowd answers are noisy, so every training photo was relabelled by GPT through Unity Gateway. "
                        "The second fine-tune adds COCO scenes and frames from our own phone testing, labelled the way a sighted guide would speak."],
             (0, 0, 12, 2)),
        counter("k-photos", "ds_data", "photos_stored", "Photos in the volume", (0, 2, 3, 3), COUNT),
        counter("k-labels", "ds_data", "labels_written", "Labels written through the gateway", (3, 2, 3, 3), COUNT),
        counter("k-rows", "ds_data", "train_rows_v2", "Training rows, Witness-2B", (6, 2, 3, 3), COUNT),
        counter("k-crowd", "ds_data", "crowd_changed", "Crowd answers changed by relabelling", (9, 2, 3, 3), PCT),
        widget("p-mix", "ds_mix", [field("kind"), field("sum(train_rows)", "SUM(`train_rows`)")],
               {"version": 3, "widgetType": "pie",
                "encodings": {"angle": {"fieldName": "sum(train_rows)", "scale": {"type": "quantitative"}, "displayName": "Training rows"},
                              "color": {"fieldName": "kind", "scale": {"type": "categorical"}, "displayName": "Kind of request"},
                              "label": {"show": True}},
                "frame": {"showTitle": True, "title": "What Witness-2B was trained on"}}, (0, 5, 5, 7)),
        widget("b-crowd", "ds_crowd", [field("crowd_verdict"), field("sum(photos)", "SUM(`photos`)")],
               {"version": 3, "widgetType": "bar",
                "encodings": {"x": {"fieldName": "sum(photos)", "scale": {"type": "quantitative"}, "displayName": "Training photos"},
                              "y": {"fieldName": "crowd_verdict", "scale": {"type": "categorical", "sort": {"by": "value"}}, "displayName": "Verdict on the crowd majority"},
                              "label": {"show": True}},
                "frame": {"showTitle": True, "title": "Relabelling against the crowd majority"}}, (5, 5, 7, 4)),
        widget("b-reasons", "ds_reasons", [field("unanswerable_reason"), field("sum(photos)", "SUM(`photos`)")],
               {"version": 3, "widgetType": "bar",
                "encodings": {"x": {"fieldName": "sum(photos)", "scale": {"type": "quantitative"}, "displayName": "Training photos"},
                              "y": {"fieldName": "unanswerable_reason", "scale": {"type": "categorical", "sort": {"by": "value"}}, "displayName": "Obstacle"},
                              "label": {"show": True}},
                "frame": {"showTitle": True, "title": "Why a photo cannot answer its question"}}, (5, 9, 7, 5)),
        table("t-sources", "ds_sources", [("photo_set", "Photo set"), ("photos", "Photos"), ("megabytes", "MB")],
              "Photos stored in the Unity Catalog volume", (0, 12, 5, 5)),
        table("t-taps", "ds_taps",
              [("image", "Held-out photo"), ("reference", "Sighted-guide label"), ("stock_app", "Stock app"),
               ("fine_tune_v1", "Fine-tune v1"), ("witness_2b", "Witness-2B")],
              "Tap replies on 70 photos held out of training", (0, 17, 12, 9)),
    ]
    gateway = [
        text("u-head", ["# Unity Gateway usage\n", "\n",
                        "All labelling and grading calls went to OpenAI through one governed provider, workspace.default.openai. "
                        "The key lives in a Unity Catalog secret; these numbers come from the gateway's system tables."], (0, 0, 12, 2)),
        counter("k-req", "ds_gw", "succeeded", "Successful model calls", (0, 2, 3, 3), COUNT, agg="SUM"),
        counter("k-in", "ds_gw", "input_tokens", "Input tokens", (3, 2, 3, 3), COUNT, agg="SUM"),
        counter("k-out", "ds_gw", "output_tokens", "Output tokens", (6, 2, 3, 3), COUNT, agg="SUM"),
        counter("k-usd", "ds_spend", "usd", "Spend on our own OpenAI key (USD)", (9, 2, 3, 3), USD, agg="SUM"),
        widget("l-req", "ds_gw", [field("hour"), field("model"), field("sum(succeeded)", "SUM(`succeeded`)")],
               {"version": 3, "widgetType": "bar",
                "encodings": {"x": {"fieldName": "hour", "scale": {"type": "temporal"}, "displayName": "Hour (UTC)"},
                              "y": {"fieldName": "sum(succeeded)", "scale": {"type": "quantitative"}, "displayName": "Successful calls"},
                              "color": {"fieldName": "model", "scale": {"type": "categorical"}, "displayName": "Model"}},
                "frame": {"showTitle": True, "title": "Successful calls per hour"}}, (0, 5, 7, 6)),
        widget("b-outcome", "ds_gw", [field("model"), field("outcome"), field("sum(requests)", "SUM(`requests`)")],
               {"version": 3, "widgetType": "bar",
                "encodings": {"x": {"fieldName": "model", "scale": {"type": "categorical"}, "displayName": "Model"},
                              "y": {"fieldName": "sum(requests)", "scale": {"type": "quantitative"}, "displayName": "Requests"},
                              "color": {"fieldName": "outcome", "displayName": "Outcome",
                                        "scale": {"type": "categorical",
                                                  "mappings": [{"value": "Succeeded", "color": GREEN}, {"value": "Rate limited, retried", "color": AMBER},
                                                               {"value": "Other error", "color": RED}]}},
                              "label": {"show": True}},
                "frame": {"showTitle": True, "title": "Requests by outcome", "showDescription": True,
                          "description": "Rate-limited calls were retried until they succeeded"}}, (7, 5, 5, 6)),
        widget("b-spend", "ds_spend", [field("hour"), field("model"), field("sum(usd)", "SUM(`usd`)")],
               {"version": 3, "widgetType": "bar",
                "encodings": {"x": {"fieldName": "hour", "scale": {"type": "temporal"}, "displayName": "Hour (UTC)"},
                              "y": {"fieldName": "sum(usd)", "scale": {"type": "quantitative"}, "displayName": "Spend", "format": USD},
                              "color": {"fieldName": "model", "scale": {"type": "categorical"}, "displayName": "Model"}},
                "frame": {"showTitle": True, "title": "Spend per hour"}}, (0, 11, 12, 6)),
    ]
    return [("quality", "Model quality", quality), ("data", "Data and labelling", data), ("gateway", "Gateway usage", gateway)]


def build(genie_space=None):
    d = {"datasets": [{"name": n, "displayName": t, "queryLines": lines(q % {"S": S, "MAIN": MAIN})} for n, t, q in DATASETS],
         "pages": [{"name": n, "displayName": t, "pageType": "PAGE_TYPE_CANVAS", "layoutVersion": "GRID_V1", "layout": w} for n, t, w in pages()]}
    if genie_space:
        d["uiSettings"] = {"genieSpace": {"isEnabled": True, "overrideId": genie_space, "enablementMode": "ENABLED"}}
    return d


if __name__ == "__main__":
    w = dbx_auth.client()
    wh = list(w.warehouses.list())[0].id
    me = w.current_user.me().user_name
    genie = sys.argv[1] if len(sys.argv) > 1 else (open(os.path.join(HERE, "genie_space_id.txt")).read().strip()
                                                   if os.path.exists(os.path.join(HERE, "genie_space_id.txt")) else None)
    body = json.dumps(build(genie))
    if os.path.exists(ID_FILE):
        did = open(ID_FILE).read().strip()
        w.lakeview.update(did, Dashboard(display_name="Private Eye: model quality and data", warehouse_id=wh, serialized_dashboard=body))
    else:
        parent = "/Workspace/Users/%s" % me
        did = w.lakeview.create(Dashboard(display_name="Private Eye: model quality and data", parent_path=parent,
                                          warehouse_id=wh, serialized_dashboard=body)).dashboard_id
        open(ID_FILE, "w").write(did)
    w.lakeview.publish(did, embed_credentials=True, warehouse_id=wh)
    print("draft:    ", "%s/sql/dashboardsv3/%s" % (dbx_auth.HOST, did))
    print("published:", "%s/dashboardsv3/%s/published" % (dbx_auth.HOST, did))
