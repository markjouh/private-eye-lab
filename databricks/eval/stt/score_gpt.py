# Scores speech-to-text systems on the app's own press recordings against one reference
# transcript per recording (OpenAI gpt-transcribe).
#   uv run --with jiwer --with whisper-normalizer python score_gpt.py <dir> <eyes-cli> <reference.tsv> name=file.tsv[:column] ...
import sys, os, csv, subprocess, statistics, collections
import jiwer
from whisper_normalizer.english import EnglishTextNormalizer
norm_ = EnglishTextNormalizer()
norm = lambda t: ' '.join(norm_(t or '').split())
D, CLI, REF = sys.argv[1], sys.argv[2], sys.argv[3]
def load(path):
    return {os.path.basename(r[0]): r for r in csv.reader(open(path), delimiter='\t', quoting=csv.QUOTE_NONE) if r and r[0] != 'file'}
ref = {k: (v[1] if len(v) > 1 else '') for k, v in load(REF).items()}
keys = sorted(k for k in ref if norm(ref[k]))
def parses(texts):
    out = []
    for i in range(0, len(texts), 60):
        chunk = [t if t.strip() else '-' for t in texts[i:i+60]]
        res = subprocess.run([CLI, 'commands'] + chunk, capture_output=True, text=True).stdout.strip().split('\n')
        out += [l.split(' <- ')[0] for l in res]
    return out
ref_parse = dict(zip(keys, parses([ref[k] for k in keys])))
commands = [k for k in keys if ref_parse[k] != 'nil']
print(f'{len(ref)} recordings, {len(keys)} with words in the reference; {len(commands)} of them are app commands by the reference text')
print(f'\n{"system":40s} {"WER":>6s} {"exact":>9s} {"empty":>5s} {"same command":>13s} {"commands kept":>14s}   after release ms (median / p90 / max)')
errors = {}
for spec in sys.argv[4:]:
    name, path = spec.split('=', 1)
    col = 2
    if ':' in path: path, c = path.rsplit(':', 1); col = int(c)
    rows = load(path)
    hyp = {k: (v[col] if len(v) > col else '') for k, v in rows.items()}
    ks = [k for k in keys if k in hyp]
    r = [norm(ref[k]) for k in ks]; h = [norm(hyp[k]) for k in ks]
    hp = dict(zip(ks, parses([hyp[k] for k in ks])))
    line = f'{name:40s} {100*jiwer.wer(r, h):5.1f}% {sum(a == b for a, b in zip(r, h)):4d}/{len(ks):<4d} {sum(1 for x in h if not x):5d} {sum(hp[k] == ref_parse[k] for k in ks):8d}/{len(ks):<4d} {sum(hp[k] == ref_parse[k] for k in commands if k in hp):8d}/{len(commands):<4d}'
    try:
        fin = sorted(float(rows[k][3]) for k in ks)
        if col == 2 and fin[-1] > 0: line += f'   {statistics.median(fin):5.0f} / {fin[int(len(fin)*.9)]:5.0f} / {fin[-1]:5.0f}'
    except Exception: pass
    print(line)
    errors[name] = [(ref[k], hyp[k]) for k in ks if norm(ref[k]) != norm(hyp[k])]
if '--errors' in sys.argv[-1:]: pass
for name in [n for n in errors if os.environ.get('SHOW') and os.environ['SHOW'] in n]:
    print(f'\n-- {name}: {len(errors[name])} differ')
    for r, h in errors[name][:int(os.environ.get("N", "25"))]: print(f'   ref: {r[:62]:62s} | got: {h[:62]}')
