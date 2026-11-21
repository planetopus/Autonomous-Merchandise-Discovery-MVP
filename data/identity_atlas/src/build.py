import json,re,collections,datetime
from merge import merged
import os; OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')+'/'
wiki=json.load(open('wiki_glossary.json'))
d=merged()
LEG={'A':'seed list from ant / brief','S':'funny sticker/tee marketplace niche (Redbubble search pages sampled this run; Etsy/eBay returned 403 so not fetched)','B':'bumper-sticker / t-shirt culture','O':"r/oddlyspecific / r/funnysigns style signal via R&D Reddit list or Redbubble titles",'W':'Wikipedia "List of subcultures" (fetched this run)','X':"own discovery: 'as a ___' self-identification / common self-label"}
def src(s):
  out=[]
  for part in s.split(';'):
    part=part.strip()
    if part.startswith('R:'): out.append(f"subreddit community {part[2:]} exists (self-ID; Reddit API 403 this run, not fetched)")
    elif part in LEG: out.append(LEG[part])
  return out
OWN_IDS={'amputees','wheelchair_users','deaf_folks','autistic_people','lgbtq_folks','lesbians','gay_men','bi_folks','gay_uncles','subaru_lesbians','jewish_folks','muslim_folks','chronic_illness','cancer_survivors','depression','ocd'}
for k in ['sports_fans','swimmers']: pass
subs=[];groups=collections.OrderedDict()
for k,v in d.items():
  own = v['parent']=='Identity & Heritage' or k in OWN_IDS or '(ownership)' in v['name']
  avoid=[o.replace('(avoid)','').strip() for o in v['outsider'] if '(avoid)' in o]
  outs=[o for o in v['outsider'] if '(avoid)' not in o]
  ov=[o for o in v['overlaps'] if o in d]
  subs.append(dict(id=k,name=v['name'].replace(' (ownership)',''),parent_group=v['parent'],
    traits=v['traits'],self_terms=v['self'],outsider_terms=outs,never_use_terms=avoid,
    overlaps=ov,buyer_pride=v['pride'],dark_tolerance=v['dark'],
    ownership_only=own,
    ownership_note=("in-group voice only: write as a member celebrating their own culture/condition; never an outsider punchline" if own else None),
    source=src(v['source'])))
  groups.setdefault(v['parent'],[]).append(k)
atlas=dict(version=1,generated=str(datetime.date.today()),
  theory="People break into groups, subgroups and stereotypes; stereotypes exist because they come from truth. Best line truthfully names a real overlapping identity in words the group wouldn't use about itself (often Gen Z/Alpha slang on older or wholesome groups) so the target thinks 'haha that's me' and buys it. Model: THICC DADS WHO VAPE FOR CHRIST.",
  guardrails=["affectionate, self-ownable humor only","no slurs; never_use_terms are outsider insults to avoid","race/ethnicity/disability/sexual-orientation subgroups are ownership_only: in-group pride voice, never an outsider punchline","keep Etsy/eBay/Redbubble safe: no explicit sexual content, no partisan attack lines"],
  field_notes=dict(buyer_pride="1-10: how proudly a member would wear a joke about themselves",dark_tolerance="0 none,1 light,2 medium (death/body/vice jokes ok),3 gallows humor welcome",overlaps="ids of subgroups that commonly co-occur in the same person"),
  source_legend=LEG,
  counts=dict(top_level_groups=len(groups),subgroups=len(subs)),
  groups=[dict(name=g,subgroup_ids=ids) for g,ids in groups.items()],
  subgroups=subs)
json.dump(atlas,open(OUT+'identity_atlas.json','w'),indent=1,ensure_ascii=False)
# slang
terms=[]
for ln in open('slang.txt'):
  if ln.startswith('#') or not ln.strip(): continue
  t,m,reg,mm,ex,st,s=ln.rstrip('\n').split('|')
  if s in wiki: sv=['Wikipedia: Glossary of 2020s slang (fetched this run): '+re.sub(r'\s+',' ',wiki[s])[:220]]
  elif s.startswith('UD:'): sv=['Urban Dictionary page fetched this run: '+s[3:]]
  elif s.startswith('KYM:'): sv=['Know Your Meme page fetched this run: '+s[4:]]
  else: sv=['common usage; not fetched this run ('+s[2:]+')']
  if t in ('era','mogging'): sv.append('note: UD top definition differs; meaning here is the current TikTok usage')
  avoid = st.endswith('crude') or 'avoid' in ex.lower()
  terms.append(dict(term=t,meaning=m,register={'gen_z':'Gen Z','alpha':'Gen Alpha','both':'Gen Z + Gen Alpha','millennial':'Millennial (dated)','regional':'Regional'}.get(reg,reg),
    funny_mismatch_score=int(mm),example_pattern=ex,status=st,
    dated_or_cringe=any(x in st for x in ('dated','cringe','ironic')),
    use_on_merch=not avoid,sources=sv))
lex=dict(version=1,generated=str(datetime.date.today()),
  how_to_use="Pick a subgroup with high buyer_pride, then a term with high funny_mismatch_score. Dated/cringe terms are deliberately funny when an older group uses them sincerely. Skip use_on_merch=false.",
  counts=dict(terms=len(terms),usable=sum(t['use_on_merch'] for t in terms),dated_or_cringe=sum(t['dated_or_cringe'] for t in terms)),terms=terms)
json.dump(lex,open(OUT+'slang_lexicon.json','w'),indent=1,ensure_ascii=False)
tset={t['term'].lower().strip('-') for t in terms}
combos=[]
for f in ['combos1.txt','combos2.txt','combos3.txt']:
  for ln in open(f):
    if ln.startswith('#') or not ln.strip(): continue
    ids,det,hook,line,pat,dk=ln.strip().split('|')
    ids=ids.split('+')
    combos.append(dict(id='c%03d'%(len(combos)+1),subgroups=ids,subgroup_names=[d[i]['name'].replace(' (ownership)','') for i in ids],
      shared_truth=det,slang_hook=hook,hook_in_lexicon=hook.lower().strip('-') in tset,example_line=line,pattern=pat,dark_level=int(dk),
      min_buyer_pride=min(d[i]['pride'] for i in ids),
      ownership_only=any(s['ownership_only'] for s in subs if s['id'] in ids)))
patterns=collections.Counter(c['pattern'] for c in combos)
oc=dict(version=1,generated=str(datetime.date.today()),
  pattern_guide=dict(identity_stack="[BODY/VIBE WORD] [PERSON TYPE] WHO [HABIT/VICE] FOR [SINCERE CAUSE] - the THICC DADS model",era="IN MY [UNGLAMOROUS REALITY] ERA",core="[GROUP] CORE: three true possessions",aura="+AURA for a mundane true habit",maxxing="[GROUP] [HABIT]MAXXING",confession="first-person true admission in slang",mismatch="old/wholesome group speaking Gen Z/Alpha slang sincerely",built_different="[GROUP WITH HARD TRUTH] BUILT DIFFERENT",fake_warning_sign="CAUTION-style sign",dark_label="cheerful label on a dark truth",roman_empire="[OBSESSION] IS MY ROMAN EMPIRE",its_giving="IT'S GIVING [TRUE VIBE]",drip="[WORK UNIFORM] DRIP",ate="[GROUP] ATE [TASK]",emotional_support="EMOTIONAL SUPPORT [OBJECT]"),
  counts=dict(combos=len(combos),patterns=dict(patterns)),combos=combos)
json.dump(oc,open(OUT+'overlap_combos.json','w'),indent=1,ensure_ascii=False)
print(atlas['counts'],lex['counts'],oc['counts'])
print('hooks not in lexicon:',[c['slang_hook'] for c in combos if not c['hook_in_lexicon']])
