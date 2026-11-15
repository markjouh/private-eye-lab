"""Upload photo sets to the Unity Catalog volume, in parallel and resumable.

  uv run --with databricks-sdk dbx_upload_photos.py <set name> <local dir> [limit]
Photos land in /Volumes/workspace/eyes/files/photos/<set name>/. Phone frames are uploaded too, except
the ones showing the student ID card, which stay off every server.
"""
import concurrent.futures as cf
import os, sys, time

import dbx_auth

name, local = sys.argv[1], sys.argv[2]
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0
w = dbx_auth.client()
base = "/Volumes/workspace/eyes/files/photos/%s" % name
try:
    w.files.create_directory(base)
except Exception:
    pass
have = set()
try:
    have = {e.name for e in w.files.list_directory_contents(base)}
except Exception:
    pass
files = sorted(f for f in os.listdir(local) if f.lower().endswith((".jpg", ".jpeg", ".png")) and f not in have)
if limit:
    files = files[:limit]
print("%s: %d already there, %d to upload" % (name, len(have), len(files)), flush=True)


def up(f):
    for attempt in range(4):
        try:
            with open(os.path.join(local, f), "rb") as fh:
                w.files.upload("%s/%s" % (base, f), fh, overwrite=True)
            return os.path.getsize(os.path.join(local, f))
        except Exception:
            time.sleep(1 + attempt)
    return 0


t0, done, size = time.time(), 0, 0
with cf.ThreadPoolExecutor(max_workers=24) as pool:
    for n in pool.map(up, files):
        done += 1
        size += n
        if done % 1000 == 0 or done == len(files):
            el = time.time() - t0
            print("%d/%d | %.1f MB | %.1f files/s | %.2f MB/s" % (done, len(files), size / 1e6, done / el, size / 1e6 / el), flush=True)
print("DONE", name, flush=True)
