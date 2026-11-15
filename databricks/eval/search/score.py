import csv,json,collections,os,sys
SP=sys.argv[1]
lab=json.load(open(SP+'/eye_labels.json'))
allo=json.load(open(SP+'/detector_and_models.json'))   # key frame|obj -> [key, stock, v2yn, det]
def load(p,col=3):
    d={}
    if not os.path.exists(p): return d
    for r in csv.reader(open(p),delimiter='\t'):
        if r[1].startswith('there is a '): d[(os.path.basename(r[0])[:-4],r[1].replace('there is a ','').replace(' in view',''))]=float(r[col])
    return d
judges={'detector':{tuple(k.split('|')):v[3] for k,v in allo.items()},
        'stock LFM3 (yes/no)':{tuple(k.split('|')):v[1] for k,v in allo.items()},
        'Witness-2B (yes/no)':load(SP+'/witness2b_yesno.tsv'),
        'Witness-2B (bare)':load(SP+'/witness2b_bare.tsv')}
objs=('person','chair','laptop','bottle','can')
def table(name,score,bars):
    if not score: return
    print(f'\n== {name}')
    print('bar   '+'  '.join(f'{o:>20s}' for o in objs)+'                 ALL')
    for b in bars:
        cells=[];tf=tn=tm=tp=0
        for o in objs:
            N=[t for t in lab if lab[t][o]=='N' and (t,o) in score]; Y=[t for t in lab if lab[t][o]=='Y' and (t,o) in score]
            fp=sum(score[(t,o)]>=b for t in N); fn=sum(score[(t,o)]<b for t in Y)
            cells.append(f'{fp:3d}/{len(N):3d} f {fn:3d}/{len(Y):3d} m'); tf+=fp;tn+=len(N);tm+=fn;tp+=len(Y)
        print(f'{b:.2f}  '+'  '.join(f'{c:>20s}' for c in cells)+f'   {tf}/{tn} ({100*tf/tn:.1f}%) false, {tm}/{tp} ({100*tm/tp:.1f}%) missed')
    b=bars[len(bars)//2]
    print('marginal (M) passing at %.2f: '%b+', '.join(f"{o} {sum(score[(t,o)]>=b for t in lab if lab[t][o]=='M' and (t,o) in score)}/{sum(1 for t in lab if lab[t][o]=='M' and (t,o) in score)}" for o in objs))
table('detector',judges['detector'],[0.25,0.35,0.5,0.6,0.7,0.8])
for n in list(judges)[1:]: table(n,judges[n],[0.5,0.6,0.7,0.8,0.9,0.95,0.98])
