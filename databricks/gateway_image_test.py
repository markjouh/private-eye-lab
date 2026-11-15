# Databricks notebook source
# One-image test of the Unity Gateway provider workspace.default.openai.
# Draws a known number on an image, sends it to gpt-6.1-sol as base64, and checks the reply.

import base64, io
from PIL import Image, ImageDraw, ImageFont

NUMBER = "4821"
small = Image.new("RGB", (60, 20), "white")
ImageDraw.Draw(small).text((8, 4), NUMBER, fill="black", font=ImageFont.load_default())
img = small.resize((480, 160), Image.NEAREST)
buf = io.BytesIO()
img.save(buf, format="PNG")
IMAGE_B64 = base64.b64encode(buf.getvalue()).decode()
print("test image:", img.size, "PNG,", len(buf.getvalue()), "bytes")
img

# COMMAND ----------

import requests

HOST = "https://dbc-5bd2d642-3eac.cloud.databricks.com"
URL = HOST + "/ai-gateway/openai/v1/responses"

# Use the notebook's own sign-in; the token is never printed.
try:
    from databricks.sdk import WorkspaceClient
    headers = dict(WorkspaceClient().config.authenticate())
    auth_source = "databricks-sdk"
except Exception as e:  # fall back to the notebook context token
    token = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
    headers = {"Authorization": "Bearer " + token}
    auth_source = "notebook context (sdk failed: %s)" % type(e).__name__

headers["Content-Type"] = "application/json"
headers["Databricks-Model-Provider-Service"] = "workspace.default.openai"

payload = {
    "model": "gpt-6.1-sol",
    "max_output_tokens": 1024,
    "input": [{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "What number is written in this image? Reply with the number only."},
            {"type": "input_image", "image_url": "data:image/png;base64," + IMAGE_B64},
        ],
    }],
}

r = requests.post(URL, headers=headers, json=payload, timeout=120)
print("auth:", auth_source)
print("HTTP", r.status_code)
if r.status_code == 200:
    data = r.json()
    texts = [c.get("text", "") for item in data.get("output", []) if item.get("type") == "message"
             for c in item.get("content", []) if c.get("type") == "output_text"]
    answer = " ".join(texts).strip()
    print("model:", data.get("model"))
    print("model reply:", repr(answer))
    print("expected:   ", repr(NUMBER))
    print("RESULT:", "PASS - image was read correctly" if NUMBER in answer.replace(",", "").replace(" ", "") else "CHECK - reply does not contain the number")
    print("usage:", data.get("usage"))
else:
    print("RESULT: FAIL")
    print(r.text[:2000])
