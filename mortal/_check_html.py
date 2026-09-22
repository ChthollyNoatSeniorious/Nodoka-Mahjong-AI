import re
import sys

h = open(sys.argv[1], encoding='utf-8').read()
print('entries:', h.count('<div class="entry">'))
print('chosen cands:', h.count('class="cand chosen"'))
print('ok tags:', h.count('tag-ok'), 'no tags:', h.count('tag-no'), 'top tags:', h.count('tag-top'))

# sanity: every cand block has consistent probability bar and tags
blocks = re.findall(r'<div class="cand(?: chosen)?">(.*?)</div>', h, re.S)
print('cand blocks:', len(blocks))
bad = [b for b in blocks if 'cand-bar' not in b or 'cand-p' not in b]
print('malformed cand blocks:', len(bad))

# show the first two decision entries stripped of tags for readability
entries = re.findall(r'<div class="entry">.*?</div>\s*</div>\s*</div>', h, re.S)[:2]
for e in entries:
    text = re.sub(r'<[^>]+>', ' ', e)
    text = re.sub(r'\s+', ' ', text).strip()
    print('---')
    print(text[:400])