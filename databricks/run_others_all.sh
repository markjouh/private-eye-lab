#!/bin/zsh
# Run the five other 2B-class models over both test sets, plain and with the app's style instructions.
# Usage: ./run_others_all.sh            (models must be in ../models/other/, see run_other_model.py)
cd /Users/mark/Documents/s26-eyes-lab/databricks
O=/Users/mark/Documents/s26-eyes-lab/models/other
run() {  # run <NAME> <model> <mmproj>
  for mode in plain styled; do
    flag=""; [ $mode = styled ] && flag="--styled"
    if [ -s eval/runs/$1_$mode.tsv ] && [ -s eval/runs/phone_$1_$mode.tsv ]; then echo "$1_$mode already done"; continue; fi
    uv run --quiet --with pillow --with requests python3 run_other_model.py $1_$mode $2 $3 --port 8093 ${=flag} || echo "FAILED $1_$mode"
  done
}
run K_qwen35     $O/qwen35/Qwen3.5-2B-Q4_K_M.gguf                     $O/qwen35/mmproj-F16.gguf
run L_qwen3vl    $O/qwen3vl/Qwen3VL-2B-Instruct-Q4_K_M.gguf           $O/qwen3vl/mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf
run M_gemma4     $O/gemma4/gemma-4-E2B_q4_0-it.gguf                   $O/gemma4/gemma-4-E2B-it-mmproj.gguf
run N_smolvlm2   $O/smolvlm2/SmolVLM2-2.2B-Instruct-Q4_K_M.gguf       $O/smolvlm2/mmproj-SmolVLM2-2.2B-Instruct-Q8_0.gguf
run O_internvl35 $O/internvl35/OpenGVLab_InternVL3_5-2B-Q4_K_M.gguf   $O/internvl35/mmproj-OpenGVLab_InternVL3_5-2B-f16.gguf
echo "all runs finished at $(date +%T)"
