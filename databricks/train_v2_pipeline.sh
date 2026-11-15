#!/bin/zsh
# v2 end to end, once labelling has been started: wait for labels and photos, build the mix, train on
# markws, convert, run both test sets, grade, and collect tap replies on held-out frames.
cd /Users/mark/Documents/s26-eyes-lab/databricks || exit 1
LAB=/Users/mark/Documents/s26-eyes-lab
E=$LAB/databricks/eval

while pgrep -f "label_all_v2.sh" > /dev/null; do sleep 5; done
echo "labels ready at $(date +%T)"
python3 -I build_train_set_v2.py train eval || exit 1

ssh -o BatchMode=yes -o ServerAliveInterval=30 markws 'n=0; until [ $(ls ~/eyes-ft/data/coco768 2>/dev/null | wc -l) -ge 5000 ] && [ $(ls ~/eyes-ft/data/phone768 2>/dev/null | wc -l) -ge 238 ] || [ $n -ge 240 ]; do sleep 5; n=$((n+1)); done; ls ~/eyes-ft/data/coco768 | wc -l; ls ~/eyes-ft/data/phone768 | wc -l'
scp -q -o BatchMode=yes train/train_v2.jsonl markws:eyes-ft/data/train_v2.jsonl || exit 1
ssh -o BatchMode=yes markws 'cd ~/eyes-ft && rm -rf runs/v2 && (nohup env CUDA_VISIBLE_DEVICES=0 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True ./venv/bin/python train_lfm3.py --base base --data data/train_v2.jsonl --images data --out runs/v2 --bs 6 --epochs 1 --workers 8 > runs_v2.log 2>&1 &); sleep 2; echo started'
echo "training launched at $(date +%T)"

./convert_and_eval.sh v2
echo "tests graded at $(date +%T)"

# Tap replies on frames held out of training: the app as shipped (stock model, full tap path),
# the first fine-tune and v2 (both asked the bare tap question).
python3 -I -c "
import json
rows = json.load(open('$E/tap_holdout.json'))
src = {'phone768': '$LAB/databricks/train/phone_frames_train/', 'coco768': '$LAB/coco/val2017/'}
with open('$E/tap_holdout.tsv', 'w') as f, open('$E/tap_holdout_files.txt', 'w') as g:
    for i, r in enumerate(rows):
        p = src[r['dir']] + r['image']
        f.write('t%02d\t%s\tWhat is in front of me?\t\t\n' % (i, p))
        g.write(p + '\n')
"
cd /Users/mark/Documents/eyes
CLI=build/Build/Products/Release/eyes-cli
P8=Models/mmproj-LFM3-VL-2B-Q8_0.gguf
$CLI ask $LAB/models/eyes-ft-v2-Q4_K_M.gguf $P8 --batch $E/tap_holdout.tsv --out $E/runs/tap_v2.tsv > $E/runs/tap_v2.log 2>/dev/null
$CLI ask $LAB/models/eyes-ft-v1-Q4_K_M.gguf $P8 --batch $E/tap_holdout.tsv --out $E/runs/tap_v1.tsv > $E/runs/tap_v1.log 2>/dev/null
$CLI describe Models/yoloe26m.mlpackage Eyes/Resources/yoloe_labels.json Models/LFM3-VL-2B-QAD-Q4_0.gguf $P8 $(cat $E/tap_holdout_files.txt) > $E/runs/tap_stock_describe.txt 2>/dev/null
echo "tap comparison done at $(date +%T)"
wc -l $E/runs/tap_v2.tsv $E/runs/tap_v1.tsv $E/runs/tap_stock_describe.txt
