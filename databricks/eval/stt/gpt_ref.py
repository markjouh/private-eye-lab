# Reference transcripts from OpenAI's transcription model, one request per recording.
#   uv run --with requests python gpt_ref.py <key file> <list.txt> <out.tsv> [model] [limit]
import sys, os, requests, concurrent.futures, time
key = open(sys.argv[1]).read().strip()
paths = [l.strip() for l in open(sys.argv[2]) if l.strip()]
out, model = sys.argv[3], (sys.argv[4] if len(sys.argv) > 4 else 'gpt-transcribe')
if len(sys.argv) > 5: paths = paths[:int(sys.argv[5])]
def one(p):
    for attempt in range(4):
        try:
            with open(p, 'rb') as f:
                r = requests.post('https://api.openai.com/v1/audio/transcriptions', headers={'Authorization': 'Bearer ' + key},
                                  files={'file': ('audio.m4a', f, 'audio/mp4')}, data={'model': model, 'language': 'en', 'response_format': 'json'}, timeout=120)
            if r.status_code == 200: return p, r.json().get('text', '').strip().replace('\t', ' ').replace('\n', ' '), ''
            err = f'{r.status_code} {r.text[:200]}'
            if r.status_code not in (429, 500, 502, 503): return p, '', err
        except Exception as e:
            err = str(e)[:200]
        time.sleep(2 * (attempt + 1))
    return p, '', err
done = {}
with concurrent.futures.ThreadPoolExecutor(4) as pool:
    for i, (p, text, err) in enumerate(pool.map(one, paths)):
        done[p] = (text, err)
        if err: print('error', os.path.basename(p), err, flush=True)
        if i % 40 == 0: print(i + 1, len(paths), flush=True)
with open(out, 'w') as f:
    for p in paths: f.write(p + '\t' + done[p][0] + '\n')
print('errors:', sum(1 for t, e in done.values() if e), 'empty:', sum(1 for t, e in done.values() if not t and not e))
