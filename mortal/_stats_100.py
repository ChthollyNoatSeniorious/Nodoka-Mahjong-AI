import gzip, json, glob, math

def softmax(vals):
    m = max(vals)
    ex = [math.exp(x - m) for x in vals]
    s = sum(ex)
    return [x / s for x in ex]

MB = 46
MJAI = ["1m","2m","3m","4m","5m","6m","7m","8m","9m","1p","2p","3p","4p","5p","6p","7p","8p","9p",
        "1s","2s","3s","4s","5s","6s","7s","8s","9s","E","S","W","N","P","F","C"]
TOT, EQ, PI_BUCK, PI_SUM = 0, 0, [0,0,0,0], 0.0
GAMES = 0
for fn in sorted(glob.glob(r'output/1v3_100/*.json.gz')):
    chal = None
    names = None
    with gzip.open(fn, 'rt', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line: continue
            ev = json.loads(line)
            t = ev['type']
            if t == 'start_game':
                names = ev.get('names') or []
                chal = names.index('mortal') if 'mortal' in names else None
                continue
            if t == 'end_game':
                break
            if chal is None: continue
            if t not in ('dahai','reach','chi','pon','daiminkan','ankan','kakan'):
                continue
            if ev.get('actor') != chal: continue
            meta = ev.get('meta') or {}
            q = meta.get('q_values') or []
            q = [v if isinstance(v,(int,float)) else -1e9 for v in q]
            if not q: continue
            mb = int(meta.get('mask_bits', 0))
            bits = [i for i in range(MB) if (mb >> i) & 1][:len(q)]
            probs = softmax(q)
            top = max(range(len(probs)), key=lambda i: probs[i])
            top_idx = bits[top]
            if t == 'dahai':
                pai = ev['pai']
                tid = -1
                if pai in MJAI: tid = MJAI.index(pai)
                if tid < 0 and len(pai) == 3 and pai[1] in 'mps':  # aka 5sr
                    tid = {'m':4,'p':13,'s':22}[pai[1]]
                act = tid
            elif t == 'reach': act = 37
            elif t == 'chi':
                ids = sorted(int(c[0]) for c in ev['consumed'])
                act = 38 + (ids[0] % 3)
            elif t == 'pon': act = 41
            elif t in ('daiminkan','ankan','kakan'): act = 42
            else: act = -1
            if act < 0: continue
            TOT += 1
            p = probs[top] * 100
            PI_SUM += p
            if p < 40: PI_BUCK[0] += 1
            elif p < 60: PI_BUCK[1] += 1
            elif p < 80: PI_BUCK[2] += 1
            else: PI_BUCK[3] += 1
            if act == top_idx: EQ += 1
    GAMES += 1
print(f'games={GAMES} decisions={TOT} top1_agree={EQ/TOT*100:.2f}% avg_top_pi={PI_SUM/TOT:.1f}%')
print(f'buckets(<40,40-60,60-80,>=80): {PI_BUCK} = {[round(b/TOT*100,1) for b in PI_BUCK]}%')