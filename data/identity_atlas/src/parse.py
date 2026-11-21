import glob
def load():
  out={}
  for f in sorted(glob.glob('sg/*.txt')):
    for ln in open(f):
      ln=ln.strip()
      if not ln or ln.startswith('#'): continue
      p=ln.split('|')
      assert len(p)==10,(f,ln[:60],len(p))
      id_=p[0]
      assert id_ not in out, id_
      out[id_]=dict(id=id_,name=p[1],parent=p[2],traits=[t.strip() for t in p[3].split(';') if t.strip()],self=[x.strip() for x in p[4].split(',') if x.strip()],outsider=[x.strip() for x in p[5].split(',') if x.strip()],overlaps=[x.strip() for x in p[6].split(',') if x.strip()],pride=int(p[7]),dark=int(p[8]),source=p[9])
  return out
