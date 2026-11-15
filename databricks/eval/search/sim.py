# Simulated 30-second searches built from the logged frames: each "view" is one saved frame held
# for 1 to 2.5 s (a sweep), the model's answer for a view is its measured yes-probability, a look
# takes 0.8 s and looks start 1.0 s apart (0.8 s when confirming a yes), as in Policy.searching.
import csv,json,os,random,sys,collections
SP=sys.argv[1]; random.seed(7)
lab=json.load(open(SP+'/eye_labels.json'))
def load(p,col=3):
    d={}
    for r in csv.reader(open(p),delimiter='\t'):
        if r[1].startswith('there is a '): d[(os.path.basename(r[0])[:-4],r[1].replace('there is a ','').replace(' in view',''))]=float(r[col])
    return d
allo=json.load(open(SP+'/detector_and_models.json'))
models={'Witness-2B':(load(SP+'/witness2b_yesno.tsv'),0.7,0.95),'stock LFM3':({tuple(k.split('|')):v[1] for k,v in allo.items()},0.9,0.98)}
objs=('person','chair','laptop','bottle','can')
LOOK=0.8; GAP=1.0; CONFIRM=0.3; LIMIT=30.0
def run(views,p,rule,bar,sure):
    # views: list of (start,end,frame). returns time found or None
    t=0.0; yes=0
    def view_at(t):
        for s,e,f in views:
            if s<=t<e: return f
        return views[-1][2]
    while t+LOOK<=LIMIT:
        pr=p[view_at(t)]; done=t+LOOK
        if rule=='single':
            if pr>=bar: return done
        elif rule=='double':
            yes = yes+1 if pr>=bar else 0
            if yes>=2: return done
        else: # sure-or-double
            if pr>=sure: return done
            yes = yes+1 if pr>=bar else 0
            if yes>=2: return done
        t=max(t+(CONFIRM if yes>0 else GAP),done)
    return None
def sweep(pool,until,start=0.0):
    v=[];t=start
    while t<until:
        d=random.uniform(1.0,2.5); v.append((t,min(t+d,until),random.choice(pool))); t+=d
    return v
for name,(p,bar,sure) in models.items():
    print(f'\n== {name}: bar {bar}, sure at {sure}')
    for rule in ('single','double','sure-or-double'):
        res=collections.Counter(); delays=collections.defaultdict(list); neg=0; negfire=0; negM=0; negMfire=0
        for o in objs:
            N=[t for t in lab if lab[t][o]=='N' and (t,o) in p]; Y=[t for t in lab if lab[t][o]=='Y' and (t,o) in p]; M=[t for t in lab if lab[t][o] in ('N','M') and (t,o) in p]
            po={t:p[(t,o)] for t in lab if (t,o) in p}
            for _ in range(4000):
                neg+=1; negfire+= run(sweep(N,LIMIT),po,rule,bar,sure) is not None
                negM+=1; negMfire+= run(sweep(M,LIMIT),po,rule,bar,sure) is not None
            for D in (1.0,1.5,2.0,3.0):
                for _ in range(2000):
                    t0=random.uniform(2,15)
                    views=sweep(N,t0)+[(t0,t0+D,random.choice(Y))]+sweep(N,LIMIT,t0+D)
                    f=run(views,po,rule,bar,sure)
                    if f is None: res[(D,'missed')]+=1
                    elif f<t0: res[(D,'false before')]+=1
                    elif f<=t0+D+2*LOOK: res[(D,'found')]+=1; delays[D].append(f-t0)
                    else: res[(D,'false after')]+=1
        print(f'{rule:15s} nothing there: false "found" in {100*negfire/neg:4.1f}% of 30 s searches ({100*negMfire/negM:4.1f}% if partly-visible ones count as absent)')
        for D in (1.0,1.5,2.0,3.0):
            n=sum(v for (d,_),v in res.items() if d==D); f=res[(D,'found')]
            dl=sorted(delays[D]); med=dl[len(dl)//2] if dl else float('nan')
            print(f'                in view for {D:.1f} s: found {100*f/n:4.1f}%, median {med:.1f} s after it appears; missed {100*res[(D,"missed")]/n:4.1f}%; false {100*(res[(D,"false before")]+res[(D,"false after")])/n:4.1f}%')
