"""Offline source comparison. Expectations never enter web/LLM requests."""
import json,re,hashlib,copy
from pathlib import Path
from env_rag_final.answer import _reverify_prose_items,_reverify_table_items
BASE=Path(__file__).resolve().parent;ROOT=BASE.parent
matrix=json.loads((ROOT/'acceptance-matrix.json').read_text())
completion={c['id']:c['expected_full_statements']for c in json.loads((ROOT/'acceptance-source-completion.json').read_text())['cases']}
rows=[]
norm=lambda s: re.sub(r'\s+',' ',s).strip()
for case in matrix['cases']:
 pair=json.loads((ROOT/'paired-r1'/(case['id']+'-pair.json')).read_text())
 result=pair['enhanced'];enum=result['enumeration'];items=(enum or{}).get('answer',{}).get('items',[])
 if case['category']=='control':
  latest=ROOT/'validation-r2'/(case['id']+'-enhanced.json')
  if latest.exists():result=json.loads(latest.read_text())['results'][0];enum=result['enumeration'];items=(enum or{}).get('answer',{}).get('items',[])
  okay=(result['status']=='ambiguous' if case['expected_behavior'] in ('ambiguous','clarification') else enum is None)
  rows.append({'id':case['id'],'category':'control','passed':okay,'range_status':result['status'],'items':len(items),'record_id':result['record_id']});continue
 expected=case.get('expected_items') or completion.get(case['id']) or case.get('expected_cells')
 def project(it):
  if case['category']=='files':return (it['doc_id'],it['doc_name'],it.get('self_code'),it.get('self_code_version'))
  if case['category']=='table':return tuple(map(norm,it['cells'])) if isinstance(it,dict) else tuple(map(norm,it))
  return (it['clause'],norm(it['text']))
 actual=list(map(project,items));wanted=list(map(project,expected))
 # Numbering-only blocks and body have protocol separators, preserve word boundary.
 missing=[x for x in wanted if x not in actual];extra=[x for x in actual if x not in wanted]
 problems=[]
 for it in copy.deepcopy(items):
  cit=it['citation'];assert cit['workspace']=='default' and cit['snapshot_id']=='4919b3938ad93747'
  assert cit.get('doc_id')==it['doc_id']
  assert it.get('citation_verified') is True and it.get('citation_reverified') is True
  if case['category']!='files':
   loc=cit.get('locator'); name=it.get('doc_name') or next(c['doc_name'] for c in result['chunks'] if c['doc_id']==it['doc_id'])
   parsed=Path('datasets/corpus/parsed')/(loc['parsed_dir'] if isinstance(loc,dict) else name+'.parsed')
   fn=_reverify_table_items if case['category']=='table' else _reverify_prose_items
   problems.extend(fn([it],parsed))
 rows.append({'id':case['id'],'category':case['category'],'expected':len(wanted),'produced':len(actual),'missing':missing,'extra':extra,'source_problems':problems,'passed':not(missing or extra or problems) and enum['coverage_status']=='complete','record_id':result['record_id']})
with(BASE/'source-set-verification.json').open('x')as f:json.dump(rows,f,ensure_ascii=False,indent=2)
print(json.dumps([{'id':r['id'],'passed':r['passed'],'missing':len(r.get('missing',[])),'extra':len(r.get('extra',[])),'source_problems':r.get('source_problems')}for r in rows],ensure_ascii=False,indent=2))
assert len(rows)==20 and all(r['passed']for r in rows)
