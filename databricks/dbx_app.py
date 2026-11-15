"""Create or redeploy the results-browser Databricks App (source in app/).

  uv run --with databricks-sdk dbx_app.py
The app runs as its own service principal, which gets read-only access to workspace.eyes (tables,
views and the photo volume) and may use the SQL warehouse. On Free Edition an app stops 24 hours
after it was last started or deployed: run this again (or press Start in the Apps page) before a demo.
"""
import os, sys

import dbx_auth
import dbx_lakehouse as L
from databricks.sdk.service.apps import (App, AppDeployment, AppDeploymentMode, AppResource, AppResourceSqlWarehouse,
                                         AppResourceSqlWarehouseSqlWarehousePermission as WhPerm)
from databricks.sdk.service.workspace import ImportFormat

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "private-eye-results"

w = dbx_auth.client()
wh = list(w.warehouses.list())[0].id
me = w.current_user.me().user_name
try:
    app = w.apps.get(NAME)
    print("app exists:", app.url)
except Exception:
    print("creating app (takes a few minutes)...", flush=True)
    app = w.apps.create_and_wait(App(name=NAME, description="Private Eye: browse test photos, model answers and grades from Unity Catalog",
                                     resources=[AppResource(name="sql-warehouse",
                                                            sql_warehouse=AppResourceSqlWarehouse(id=wh, permission=WhPerm.CAN_USE))]))
sp = app.service_principal_client_id
for grant in ("GRANT USE CATALOG ON CATALOG workspace TO `%s`", "GRANT USE SCHEMA ON SCHEMA workspace.eyes TO `%s`",
              "GRANT SELECT ON SCHEMA workspace.eyes TO `%s`", "GRANT READ VOLUME ON VOLUME workspace.eyes.files TO `%s`"):
    L.sql(grant % sp, quiet=True)
print("read-only access to workspace.eyes granted to the app's service principal", flush=True)

src = "/Workspace/Users/%s/private-eye/results-app" % me
w.workspace.mkdirs(src)
for f in ("app.py", "app.yaml", "requirements.txt"):
    w.workspace.upload("%s/%s" % (src, f), open(os.path.join(HERE, "app", f), "rb").read(), format=ImportFormat.AUTO, overwrite=True)
try:
    state = w.apps.get(NAME).compute_status.state.value
except Exception:
    state = "?"
if state not in ("ACTIVE", "STARTING"):
    print("starting app compute (was %s)..." % state, flush=True)
    w.apps.start_and_wait(NAME)
d = w.apps.deploy_and_wait(app_name=NAME, app_deployment=AppDeployment(source_code_path=src, mode=AppDeploymentMode.SNAPSHOT))
print("deployment:", d.status.state.value if d.status and d.status.state else d.status, "|", d.status.message if d.status else "")
print("app url:", w.apps.get(NAME).url)
