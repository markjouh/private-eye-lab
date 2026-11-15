#!/bin/zsh
# Finishes the two labelling streams, builds the training file, and starts the fine-tune on markws.
# Run from the databricks folder. Progress goes to train/finish.log.
cd /Users/mark/Documents/s26-eyes-lab/databricks || exit 1
A=/Users/mark/Documents/s26-eyes-lab/vizwiz/annotations/train.json
I=/Users/mark/Documents/s26-eyes-lab/vizwiz/images/train
run() { uv run --quiet --with databricks-sdk --with requests --with pillow python3 relabel_train.py $A $I "$@"; }
count() { python3 -I -c "
import json
seen=set()
for p in ('train/train_labels.jsonl','train/train_labels_terra.jsonl'):
    try:
        for l in open(p):
            try:
                r=json.loads(l)
                if 'answerable' in r: seen.add(r['image'])
            except Exception: pass
    except FileNotFoundError: pass
print(len(seen))"; }

# 1. When the terra stream finishes its half, it starts on the other half from the far end.
while pgrep -f "train_labels_terra.jsonl --also-done train/train_labels.jsonl --part 1/2" > /dev/null; do sleep 3; done
echo "terra half done at $(date +%T), labelled $(count)"
(RELABEL_MODEL=gpt-6.1-terra run train/train_labels_terra.jsonl --also-done train/train_labels.jsonl --reverse --workers 96 > train/relabel_terra2.log 2>&1 &)

# 2. Stop both streams once nearly everything is covered (they meet in the middle).
while true; do
  n=$(count)
  if [ "$n" -ge 20480 ] || ! pgrep -f "relabel_train.py" > /dev/null; then break; fi
  sleep 8
done
echo "streams met at $(date +%T), labelled $(count)"
pkill -f "relabel_train.py"; sleep 3

# 3. Mop up anything still missing (errors and in-flight requests), then build the training file.
RELABEL_MODEL=gpt-6.1-terra run train/train_labels_terra.jsonl --also-done train/train_labels.jsonl --workers 48 > train/relabel_final.log 2>&1
RELABEL_MODEL=gpt-6.1-terra run train/train_labels_terra.jsonl --also-done train/train_labels.jsonl --workers 16 >> train/relabel_final.log 2>&1
echo "labelling finished at $(date +%T), labelled $(count)"
cat train/train_labels.jsonl train/train_labels_terra.jsonl > train/all_labels.jsonl
python3 -I build_train_set.py train/all_labels.jsonl train/train.jsonl

# 4. Start the fine-tune on markws (one pass over the data).
scp -q -o BatchMode=yes train/train.jsonl markws:eyes-ft/data/train.jsonl
ssh -o BatchMode=yes markws 'cd ~/eyes-ft && (nohup env CUDA_VISIBLE_DEVICES=0 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True ./venv/bin/python train_lfm3.py --base base --data data/train.jsonl --images data/train768 --out runs/v1 --bs 8 --epochs 1 --workers 8 > runs_v1.log 2>&1 &); sleep 2; echo training started on markws'
echo "training launched at $(date +%T)"
