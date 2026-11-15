"""Shared Databricks sign-in for scripts run from this Mac.

Uses the Databricks SDK's browser sign-in (OAuth). The first call opens a browser tab; the SDK
caches the sign-in under the home folder and refreshes it, so no token is ever printed or stored
in this project. Run directly to check the sign-in:  uv run --with databricks-sdk dbx_auth.py
"""
from databricks.sdk import WorkspaceClient

HOST = "https://dbc-5bd2d642-3eac.cloud.databricks.com"
PROVIDER = "workspace.default.openai"
GATEWAY_URL = HOST + "/ai-gateway/openai/v1/responses"

_client = None


def client():
    global _client
    if _client is None:
        _client = WorkspaceClient(host=HOST, auth_type="external-browser")
    return _client


def headers():
    h = dict(client().config.authenticate())
    h["Content-Type"] = "application/json"
    h["Databricks-Model-Provider-Service"] = PROVIDER
    return h


if __name__ == "__main__":
    me = client().current_user.me()
    print("signed in to", HOST, "as", me.user_name)
