"""Bounded same-Goal live cases, never passes expected answers to product."""
import json,time,hashlib
from pathlib import Path
import httpx
BASE=Path(__file__).resolve().parent
ROOT=BASE.parent
cases=json.loads((ROOT/'acceptance-matrix.json').read_text())['cases']
assert len(cases)==20
summary=[]
with httpx.Client(base_url='http://127.0.0.1:8091',timeout=240) as client:
 token=client.get('/api/config').json()['token']
 client.headers['X-RAG-Token']=token
 def post(path,body,name):
  r=client.post(path,json=body)
  data=r.json()
  with (BASE/name).open('x') as f:json.dump(data,f,ensure_ascii=False,indent=2)
  r.raise_for_status()
  return data
 for case in cases:
  q=case['query'];cid=case['id'];t=time.monotonic()
  if cid=='continued_table':
   native=json.loads(next((ROOT/'runtime').glob('web-9b631815dd1e4672-generation-*.json')).read_text())
   batch=post('/api/query',{'query':q,'strategies':['pg+local'],'generate':False,'submission_id':'paired-r1-'+cid},cid+'-retrieval.json')
   left=native;right=batch['results'][0]
   left['paired_reuse']='same-Goal previously generated original local'
  else:
   batch=post('/api/query',{'query':q,'strategies':['local','pg+local'],'generate':False,'submission_id':'paired-r1-'+cid},cid+'-retrieval.json')
   left,right=batch['results']
  if any(r['status'] in ('failure','budget_failure','stale') for r in (left,right)):
   summary.append({'id':cid,'left':left['status'],'right':right['status'],'halt':True})
   break
  if cid!='continued_table':
   left=post('/api/generate',{'record_id':left['record_id']},cid+'-local.json')
  # 12 complete enum requests + only 3 general controls; others must clarify without LLM.
  if case['category']!='control' or cid in ('general-mixing','general-footnote','general-assessment'):
   right=post('/api/generate',{'record_id':right['record_id']},cid+'-enhanced.json')
  with (BASE/(cid+'-pair.json')).open('x') as f:json.dump({'local':left,'enhanced':right},f,ensure_ascii=False,indent=2)
  row={'id':cid,'local':left['generation_status'],'enhanced':right['generation_status'],'range':right['status'],'items':len((right.get('enumeration') or {}).get('answer',{}).get('items',[])),'elapsed_s':round(time.monotonic()-t,2)}
  summary.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
 with (BASE/'run-summary.json').open('x') as f:json.dump(summary,f,ensure_ascii=False,indent=2)
print('finished',len(summary),flush=True)
