#!/bin/zsh
# After a fine-tune on markws: wait for it, convert to GGUF, copy here, run it through eyes-cli on
# both test sets, and grade it against the baseline.   Usage: ./convert_and_eval.sh v1
RUN=${1:-v1}
LAB=/Users/mark/Documents/s26-eyes-lab
E=$LAB/databricks/eval
R=$E/runs
FT=$LAB/models/eyes-ft-$RUN-Q4_K_M.gguf

# 1. Wait for training to finish (or fail).
ssh -o BatchMode=yes -o ServerAliveInterval=30 markws "cd ~/eyes-ft; n=0; until grep -q -E 'saved merged model|Traceback|Error' runs_$RUN.log 2>/dev/null || [ \$n -ge 720 ]; do sleep 5; n=\$((n+1)); done; grep -v -E 'Warning|warn|processor_kwargs|Loading weights|^\s*\$' runs_$RUN.log | tail -22"
echo "training ended at $(date +%T)"

# 2. Convert and quantize on markws, then copy the 4-bit file here.
ssh -o BatchMode=yes -o ServerAliveInterval=30 markws "cd ~/eyes-ft && ./venv/bin/python llama.cpp/convert_hf_to_gguf.py runs/$RUN/merged --outfile runs/$RUN/ft-f16.gguf --outtype f16 > runs/$RUN/convert.log 2>&1 && ./llama.cpp/build/bin/llama-quantize runs/$RUN/ft-f16.gguf runs/$RUN/eyes-ft-$RUN-Q4_K_M.gguf Q4_K_M > runs/$RUN/quant.log 2>&1; ls -la runs/$RUN/*.gguf | cut -c24-" || exit 1
scp -q -o BatchMode=yes markws:eyes-ft/runs/$RUN/eyes-ft-$RUN-Q4_K_M.gguf $FT || exit 1
echo "model copied at $(date +%T)"

# 3. Run it the way it was trained (bare question) and the way the app asks today (with its answer style).
cd /Users/mark/Documents/eyes
CLI=build/Build/Products/Release/eyes-cli
P8=Models/mmproj-LFM3-VL-2B-Q8_0.gguf
$CLI ask $FT $P8 --batch $E/lfm3_plain.tsv --out $R/G_ft_${RUN}_plain.tsv > $R/G_$RUN.log 2>/dev/null
$CLI ask $FT $P8 --batch $E/phone_plain.tsv --out $R/phone_G_ft_${RUN}_plain.tsv > $R/pG_$RUN.log 2>/dev/null
echo "plain runs done at $(date +%T)"
$CLI ask $FT $P8 --batch $E/lfm3_styled.tsv --out $R/H_ft_${RUN}_app.tsv > $R/H_$RUN.log 2>/dev/null
$CLI ask $FT $P8 --batch $E/phone_styled.tsv --out $R/phone_H_ft_${RUN}_app.tsv > $R/pH_$RUN.log 2>/dev/null
echo "styled runs done at $(date +%T)"

# 4. Grade against the baseline.
cd $LAB/databricks
uv run --quiet --with databricks-sdk --with requests python3 judge_local.py eval A_app_768 D_plain_768 G_ft_${RUN}_plain H_ft_${RUN}_app
echo "graded at $(date +%T)"
