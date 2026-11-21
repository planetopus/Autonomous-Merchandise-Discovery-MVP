import glob,re
from parse import load
def norm(s): return set(w for w in re.findall(r"[a-z0-9]+",s.lower()) if w not in {'the','a','an','of','to','in','on','is','and','for','it','my','i','you','your','s','t'})
def dup(a,b):
  A,B=norm(a),norm(b)
  if not A or not B: return True
  return len(A&B)/min(len(A),len(B))>=0.6
def merged():
  d=load()
  for f in sorted(glob.glob('extras*.txt')):
    for ln in open(f):
      ln=ln.strip()
      if not ln or '|' not in ln: continue
      k,v=ln.split('|',1)
      if k not in d: print('unknown extra id',k,f); continue
      for t in v.split(';'):
        t=t.strip().strip('|')
        if t and len(d[k]['traits'])<10 and not any(dup(t,x) for x in d[k]['traits']+d[k]['self']):
          d[k]['traits'].append(t)
  return d
if __name__=='__main__':
  d=merged()
  short=[(k,len(v['traits'])) for k,v in d.items() if len(v['traits'])<5]
  print(len(d),len(short)); print(' '.join(f'{k}:{n}' for k,n in short))
