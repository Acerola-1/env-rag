"""Offline request preview; never constructs backend clients or sends HTTP."""
import copy
import hashlib
import json
import urllib.parse
from pathlib import Path

from env_rag_final.answer import _SYNTH_SYSTEM, _synthesis_context, _question_slot_terms
from env_rag_final.enumerate_.prose_enum import UnitText, bind_citations, extract_clauses_regex, verify_citations
from env_rag_final.search.expand import _split_category_sentences

root=Path.cwd(); base=root/'reports/pg-retrieval'
old=json.loads((base/'phase-3-answer-syn/answer-runtime-latest.json').read_text())
result=old['results'][0]; sections=[]; detail=[]
inv={r['doc_id']:r for r in [json.loads(l) for l in (base/'phase-0/inventory.jsonl').read_text().splitlines()] if r.get('kind')=='db_doc'}
for exp in result['expansions']:
    doc=inv[exp['doc_id']]; directory=Path(urllib.parse.unquote(doc['sidecar_location'].removeprefix('file://')))
    blockfile=next(directory.glob('*.blocks.jsonl'))
    blocks={b.get('blockid'):b.get('content') for b in [json.loads(l) for l in blockfile.read_text().splitlines()] if b.get('type')=='content'}
    units=[]; cursor=0
    for uid in exp['unit_ids']:
        txt=blocks[uid]
        units.append(UnitText(uid,txt,[],{'file':str(blockfile.relative_to(directory)),'blockid':uid},cursor,cursor+len(txt),False,'parsed_block'))
        cursor+=len(txt)+2
    text='\n\n'.join(u.text for u in units)
    if exp['scope_id'].endswith(':3'):
        body=text.lstrip(); body=body.split('\n',1)[1] if body.startswith('#') else body;body=body.strip()
        items=_split_category_sentences(body,text)
    else:
        items=[it for it in extract_clauses_regex(text) if it["clause"] != exp["scope_id"].rsplit(":",1)[-1]]
    items=verify_citations(bind_citations(items,'default',exp['doc_id'],'4919b3938ad93747',units),text,units)
    assert len(items)==exp['items_count']
    assert all(i['citation_verified'] for i in items)
    label=next(s['label'] for s in result['model']['sections'] if s['doc_id']==exp['doc_id'])
    section={'label':label,'doc_id':exp['doc_id'],'items':items}
    sections.append(section)
    for item in items:
        cit=item['citation']; raw=blocks[cit['unit_id']]
        segments=cit.get('unit_segments') or [{'unit_id':cit['unit_id'],'rel_start':cit['unit_rel_start'],'rel_end':cit['unit_rel_end']}]
        slices=''.join(blocks[s['unit_id']][s['rel_start']:s['rel_end']] for s in segments)
        assert ''.join(cit['quote'].split()) in ''.join(slices.split())
        detail.append({'edition':label,'doc_id':exp['doc_id'],'scope_id':exp['scope_id'],'clause':item['clause'],'text':item['text'],'citation':cit,'raw_block_sha256':hashlib.sha256(raw.encode()).hexdigest(),'raw_slice_sha256':hashlib.sha256(slices.encode()).hexdigest(),'raw_position_verified':True,'scope_chunk_ids_from_historical_log':exp['chunk_ids'],'per_unit_chunk_mapping':'not re-queried; execution must obtain current formal catalogue mapping','contains_appendix_context':'## 附' in item['text']})
context,_=_synthesis_context(sections)
assert hashlib.sha256(context.encode()).hexdigest()==result['model']['context_sha256']
old_messages=result['model']['request_messages']
assert old_messages[1]['content'].split('上下文：\n',1)[1]==context
messages=copy.deepcopy(old_messages);messages[0]['content']=_SYNTH_SYSTEM
prep_path=base/'phase-3/syn-prep-syn004.json';prep=json.loads(prep_path.read_text())
prep['offline_review_reconstruction']={'method':'Original sidecar bytes + published unit IDs/order; same extraction/binding functions, no database/model call. Raw positions verified offline; current production identity/chunk mappings still require guarded execution.','context_sha_matches_historical':True,'raw_citations_verified':len(detail),'citations_file':'reports/pg-retrieval/phase-3/syn004-source-citations.json','appendix_context_note':'The existing GB3095 7.3 item includes Appendix A in its parsed block; preserved verbatim. Full member processing is not independent proof of a clean chapter boundary. Do not treat appendix statements as chapter-7 requirements.'}
prep['intended_request']['messages']=messages
prep['intended_request']['context_text']=context
prep['intended_request']['user_content_chars']=len(messages[1]['content'])
prep['intended_request']['context_chars']=len(context)
prep['intended_request']['system_prompt_current']=_SYNTH_SYSTEM
prep['intended_request']['messages_sha256']=hashlib.sha256(json.dumps(messages,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
prep['intended_request']['executed']=False
prep['intended_request']['system_prompt_sha256']=hashlib.sha256(_SYNTH_SYSTEM.encode()).hexdigest()
prep['replayed_inputs']['answer_entry_sha256']='src/env_rag_final/answer.py = '+hashlib.sha256((root/'src/env_rag_final/answer.py').read_bytes()).hexdigest()+' (only prompt aligned with accepted C1 proof contract; no runtime issued)'
prep['contract_consistency_note_and_minimal_proposal']={'decision':'Minimal prompt sentence applied by main agent; body-context bytes unchanged, no second validation/model call. Existing 64 owning tests are rerun. Real compliance remains unverified.','previous_code_sha256':'29e0aa29b2b49be4370adbedd3e6bfc746d9ca9530d992f98d731a8056e213c7'}
prep['required_slots_derived_by_accepted_code']['raw_derived_terms']=list(_question_slot_terms(result['query']))
prep['success_and_failure_semantics']['manual_answer_check']='The application slots are edition-only for this qualitative query. A main-agent check must also confirm each actual answer claim addresses the requested environmental element with its literal source evidence; HTTP200/complete alone does not prove question relevance.'
prep_path.write_text(json.dumps(prep,ensure_ascii=False,indent=2)+'\n')
(base/'phase-3/syn004-source-citations.json').write_text(json.dumps({'origin':'Offline reconstruction, not a new runtime','workspace':'default','snapshot_id':'4919b3938ad93747','context_sha256':hashlib.sha256(context.encode()).hexdigest(),'items':detail},ensure_ascii=False,indent=2)+'\n')
print('offline positions',len(detail),'context/user chars',len(context),len(messages[1]['content']),'historical context SHA exact match')
