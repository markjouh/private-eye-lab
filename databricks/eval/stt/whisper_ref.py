import sys, mlx_whisper
paths=[l.strip() for l in open(sys.argv[1]) if l.strip()]
out=open(sys.argv[2],'w')
for i,p in enumerate(paths):
    r=mlx_whisper.transcribe(p, path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="en", condition_on_previous_text=False, temperature=0.0)
    out.write(p+'\t'+r['text'].strip().replace('\t',' ').replace('\n',' ')+'\n'); out.flush()
    if i%40==0: print(i+1,len(paths),flush=True)
