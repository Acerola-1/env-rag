import json,time
from pathlib import Path
import httpx
BASE=Path(__file__).resolve().parent
ROOT=BASE.parent
cases=json.loads((ROOT/'acceptance-matrix.json').read_text())['cases']
with httpx.Client(base_url='http://127.0.0.1:8091',timeout=240)as client:
 client.headers['X-RAG-Token']=client.get('/api/config').json()['token']
 def post(path,body,name):
  response=client.post(path,json=body);data=response.json()
  with (BASE/name).open('x')as f:json.dump(data,f,ensure_ascii=False,indent=2)
  response.raise_for_status();return data
 for case in cases:
  if case['category']=='control':continue
  pair=json.loads((ROOT/'paired-r1'/(case['id']+'-pair.json')).read_text())
  result=post('/api/generate',{'record_id':pair['local']['record_id'],'profile':'uniform_evidence'},case['id']+'-uniform-local.json')
  print('uniform',case['id'],result['generation_status'],flush=True)
 for cid in ('general-mixing','general-footnote','general-assessment'):
  case=next(c for c in cases if c['id']==cid)
  data=post('/api/query',{'query':case['query'],'strategies':['pg+local'],'generate':True,'submission_id':'r2-'+cid},cid+'-enhanced.json')
  print('general',cid,[(r['status'],r['generation_status'])for r in data['results']],flush=True)
 q=next(c['query']for c in cases if c['id']=='continued_table')
 strategies=['naive','pg+naive','global','pg+global','hybrid','pg+hybrid','mix','pg+mix','pg']
 data=post('/api/query',{'query':q,'strategies':strategies,'generate':True,'submission_id':'r2-all-modes'},'mode-smokes.json')
 for r in data['results']:print('mode',r['strategy'],r['status'],r['generation_status'],len(r['chunks']),len(r['entities']),len(r['relations']),flush=True)
 data=post('/api/query',{'query':'请说明你是否使用了知识库检索。','strategies':['bypass'],'generate':True,'submission_id':'r2-bypass'},'bypass.json')
 print('bypass',data['results'][0]['generation_status'],flush=True)
 with (BASE/'budget-after.json').open('x')as f:json.dump(client.get('/api/config').json()['budget'],f,indent=2)
