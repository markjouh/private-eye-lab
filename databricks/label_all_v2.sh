#!/bin/zsh
# Labels everything for the v2 fine-tune in the agreed style, in parallel streams across two models,
# then mops up failures. Run from the databricks folder; progress in train/v2_*.log.
cd /Users/mark/Documents/s26-eyes-lab/databricks || exit 1
LAB=/Users/mark/Documents/s26-eyes-lab
U=(uv run --quiet --with databricks-sdk --with requests --with pillow python3 label_v2.py)
VZ=$LAB/vizwiz/annotations/train.json
VZI=$LAB/vizwiz/images/train

stream() {  # model  mode  source  images  out  [extra args...]
  local model=$1; shift
  RELABEL_MODEL=$model $U "$@" >> train/v2_label.log 2>&1 &
}

stream gpt-6.1-sol   taps train/phone_frames_train.json train/phone_frames_train train/v2_taps_phone.jsonl --workers 24
for job in "coco train/coco_val_list.json $LAB/coco/val2017 0" "vizwiz $VZ $VZI 3000"; do
  set -- ${=job}
  stream gpt-6.1-sol   taps $2 $3 train/v2_taps_$1_a.jsonl --count $4 --part 0/3 --workers 40
  stream gpt-6.1-terra taps $2 $3 train/v2_taps_$1_b.jsonl --count $4 --part 1/3 --workers 48
  stream gpt-6.1-terra taps $2 $3 train/v2_taps_$1_c.jsonl --count $4 --part 2/3 --workers 48
done
stream gpt-6.1-sol   declines train/all_labels.jsonl $VZI train/v2_declines_a.jsonl --part 0/3 --workers 40
stream gpt-6.1-terra declines train/all_labels.jsonl $VZI train/v2_declines_b.jsonl --part 1/3 --workers 48
stream gpt-6.1-terra declines train/all_labels.jsonl $VZI train/v2_declines_c.jsonl --part 2/3 --workers 48
wait
echo "first pass done at $(date +%T)"

# Mop up anything that failed (rate limits), twice, with the faster model.
for pass in 1 2; do
  RELABEL_MODEL=gpt-6.1-terra $U taps train/phone_frames_train.json train/phone_frames_train train/v2_taps_phone.jsonl --workers 16 >> train/v2_label.log 2>&1
  RELABEL_MODEL=gpt-6.1-terra $U taps train/coco_val_list.json $LAB/coco/val2017 train/v2_taps_coco_c.jsonl --also-done train/v2_taps_coco_a.jsonl train/v2_taps_coco_b.jsonl --workers 32 >> train/v2_label.log 2>&1
  RELABEL_MODEL=gpt-6.1-terra $U taps $VZ $VZI train/v2_taps_vizwiz_c.jsonl --count 3000 --also-done train/v2_taps_vizwiz_a.jsonl train/v2_taps_vizwiz_b.jsonl --workers 32 >> train/v2_label.log 2>&1
  RELABEL_MODEL=gpt-6.1-terra $U declines train/all_labels.jsonl $VZI train/v2_declines_c.jsonl --also-done train/v2_declines_a.jsonl train/v2_declines_b.jsonl --workers 32 >> train/v2_label.log 2>&1
done
echo "labelling finished at $(date +%T)"
python3 -I -c "
import json, glob
def count(pattern, key):
    seen = set()
    for f in glob.glob(pattern):
        for l in open(f):
            try:
                r = json.loads(l)
                if key in r: seen.add(r['image'])
            except Exception: pass
    return len(seen)
print('taps: phone', count('train/v2_taps_phone.jsonl', 'tap_reply'), '| coco', count('train/v2_taps_coco_*.jsonl', 'tap_reply'), '| vizwiz', count('train/v2_taps_vizwiz_*.jsonl', 'tap_reply'), '| declines', count('train/v2_declines_*.jsonl', 'reply'))"
