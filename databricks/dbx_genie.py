"""Create (or update) a Genie space over the evaluation and training tables, then ask it one question.

  uv run --with databricks-sdk dbx_genie.py
Lets anyone on the team ask the results in plain English ("which model invents the fewest answers?").
The space id is kept in genie_space_id.txt; dbx_dashboard.py reads it to add the Ask Genie button.
"""
import json, os, sys, uuid

import dbx_auth
import dbx_lakehouse as L

HERE = os.path.dirname(os.path.abspath(__file__))
ID_FILE = os.path.join(HERE, "genie_space_id.txt")
S = "workspace.eyes"

EXAMPLES = [
    ("How often does each model invent an answer when the photo cannot answer the question?",
     "SELECT eval_summary.label, eval_summary.invented_answers, eval_summary.declined_correctly, eval_summary.unanswerable_photos "
     "FROM workspace.eyes.eval_summary WHERE eval_summary.test_set = 'vizwiz500' ORDER BY eval_summary.invented_answers"),
    ("Which questions did the stock model get wrong that Witness-2B got right?",
     "SELECT a.id, a.question, a.reference_answer, a.answer AS stock_answer, b.answer AS witness_2b_answer "
     "FROM workspace.eyes.eval_results a JOIN workspace.eyes.eval_results b ON a.test_set = b.test_set AND a.id = b.id "
     "WHERE a.config = 'A_app_768' AND b.config = 'G_ft_v2_plain' AND a.grade = 'wrong' AND b.grade = 'right' AND a.test_set = 'vizwiz500'"),
    ("What share of answerable questions does each model get right, by kind of question?",
     "SELECT eval_results.label, eval_results.answer_type, count(*) AS photos, "
     "round(100 * count_if(eval_results.grade = 'right') / count(*), 1) AS right_pct "
     "FROM workspace.eyes.eval_results WHERE eval_results.test_set = 'vizwiz500' AND eval_results.answerable <> 'no' "
     "GROUP BY eval_results.label, eval_results.answer_type ORDER BY eval_results.label, photos DESC"),
]
QUESTIONS = ["Which configuration gets the most answers right on the VizWiz test set?",
             "How often does each model invent an answer when the photo cannot answer the question?",
             "Which kinds of question does Witness-2B still get wrong most often?",
             "How do the other 2B-class models compare with Witness-2B?",
             "What share of the crowd answers did relabelling overturn?"]
RULES = [
    "This space covers Private Eye, an on-device assistant for blind people. A small vision model (LFM3-VL-2B) answers spoken questions about what the phone camera sees. ",
    "eval_results has one row per model configuration and test photo, with the grade given by gpt-6.1-sol: 'right', 'partly' or 'wrong'. eval_summary has one row per configuration and test set. ",
    "Test sets: 'vizwiz500' (500 VizWiz photos taken by blind people) is the main one; 'phone42' is 42 frames from our own phone testing and is too small for firm conclusions. Use vizwiz500 unless the question names the phone frames. ",
    "The stock model as shipped in the app is config 'A_app_768'. Our fine-tuned model is called Witness-2B: config 'G_ft_v2_plain' (it is the second fine-tune; people may also call it Witness-2B). The earlier fine-tune v1 is 'G_ft_v1_plain'. Both are asked the bare question, as trained. Use the label column for display. ",
    "An invented answer is a 'wrong' grade on a photo whose answerable column is 'no': the model gave a specific answer the photo cannot support. Declining correctly is a 'right' grade on such a photo. ",
    "family groups configurations: 'LFM3-VL-2B stock', 'Private Eye fine-tune', 'Other 2B-class model'. When comparing with other models use the bare-question configurations. ",
    "vizwiz_relabel_train holds the relabelled training photos; crowd_verdict says whether the new label 'agrees' with, 'refines' or 'overturns' the crowd majority. train_mix_v2 holds the training rows of Witness-2B by kind.",
]


def hexid():
    return uuid.uuid4().hex


def build():
    tables = [("eval_results", "One row per model configuration and test photo: question, reference answer, the model's answer, and its grade."),
              ("eval_summary", "One row per model configuration and test set: counts of right, partly and wrong answers, invented answers and declines."),
              ("train_mix_v2", "Training rows of Witness-2B: image, question, answer and kind (answer, tap, decline, where, which, absent)."),
              ("vizwiz_relabel_train", "All 20,523 VizWiz training photos relabelled by GPT through Unity Gateway.")]
    return {
        "version": 2,
        "config": {"sample_questions": sorted([{"id": hexid(), "question": [q]} for q in QUESTIONS], key=lambda x: x["id"])},
        "data_sources": {"tables": sorted([{"identifier": "%s.%s" % (S, t), "description": [d]} for t, d in tables], key=lambda x: x["identifier"])},
        "instructions": {
            "example_question_sqls": sorted([{"id": hexid(), "question": [q], "sql": [sql]} for q, sql in EXAMPLES], key=lambda x: x["id"]),
            "text_instructions": [{"id": hexid(), "content": RULES}],
        },
    }


if __name__ == "__main__":
    for q, sql in EXAMPLES:  # every example must run before it goes in
        print("example ok:", q[:60], "->", len(L.sql(sql, quiet=True)), "rows")
    w = dbx_auth.client()
    wh = list(w.warehouses.list())[0].id
    me = w.current_user.me().user_name
    body = json.dumps(build())
    title = "Private Eye: ask the evaluation"
    desc = "Ask about how the on-device model and its fine-tunes score on the test photos, what they get wrong, and what they were trained on."
    if os.path.exists(ID_FILE):
        sid = open(ID_FILE).read().strip()
        w.genie.update_space(sid, serialized_space=body, title=title, description=desc, warehouse_id=wh)
    else:
        sid = w.genie.create_space(warehouse_id=wh, serialized_space=body, title=title, description=desc,
                                   parent_path="/Workspace/Users/%s" % me).space_id
        open(ID_FILE, "w").write(sid)
    print("genie space:", "%s/genie/rooms/%s" % (dbx_auth.HOST, sid))
    if "--no-ask" not in sys.argv:
        q = "Which configuration invents the fewest answers on the VizWiz test set, and how many?"
        msg = w.genie.start_conversation_and_wait(sid, q)
        print("asked:", q)
        for a in msg.attachments or []:
            if a.text and a.text.content:
                print("  text:", a.text.content[:500])
            if a.query:
                print("  sql:", (a.query.query or "")[:600].replace("\n", " "))
                try:
                    res = w.genie.get_message_attachment_query_result(sid, msg.conversation_id, msg.message_id, a.attachment_id)
                    print("  rows:", (res.statement_response.result.data_array or [])[:5])
                except Exception as e:
                    print("  (could not fetch rows: %s)" % str(e)[:200])
