"""Independent expected sets from raw parsed artifacts; never imported by product."""
import hashlib
import json
import re
from pathlib import Path

from lxml import html

ROOT = Path(__file__).resolve().parents[2]
PARSED = ROOT / 'datasets/corpus/parsed'
OUT = Path(__file__).parent
SEALED = ROOT / 'reports/pg-retrieval/enum-entry-20261010-r1/acceptance-sealed'


def file_for(part, suffix):
    found = list(PARSED.glob('*'+part+'*.pdf.parsed/*'+suffix))
    assert len(found) == 1, (part,found)
    return found[0]


def text_blocks(part):
    p = file_for(part, '.blocks.jsonl')
    blocks = [json.loads(x) for x in p.read_text().splitlines()]
    return p, blocks


def full_grid(markup):
    grid=[]; occupied={}
    for ri,tr in enumerate(html.fromstring(markup).xpath('.//tr')):
        row=[]; col=0
        for cell in tr.xpath('./th|./td'):
            while (ri,col) in occupied:
                row.append(occupied[(ri,col)]);col+=1
            text=''.join(cell.itertext()).strip()
            rs=int(cell.get('rowspan','1'));cs=int(cell.get('colspan','1'))
            for dy in range(rs):
                for dx in range(cs):occupied[(ri+dy,col+dx)]=text
            for dx in range(cs):row.append(text)
            col+=cs
        while (ri,col) in occupied:
            row.append(occupied[(ri,col)]);col+=1
        grid.append(row)
    return grid


def new_prose(part, numbers, query):
    p, blocks = text_blocks(part)
    alltext='\n'.join(b.get('text') or b.get('content') or '' for b in blocks)
    # Independent expected strings are explicitly transcribed below, checked
    # against raw source; no answer engine or corpus lookup is called.
    return {'query':query,'category':'prose','expected_clauses':numbers,
            'source':str(p.relative_to(ROOT)), 'raw_source_text':alltext}


rows=[]
queries={
'versions':'列出库内 GB3095 标准的全部文档及版本',
'amendments':'库内有哪些 GB18466-2005 的文档（含修改单）？',
'terms':'列出 GB18466-2005 第3章的全部术语和定义',
'clauses':'列出 GB8978-1996 第4.3节的全部要求',
'continued_table':'列出 GB8978-1996 表1的全部项目及限值',
'edition':'列出 GB3095-2012 第4.2条的全部规定'}
for name,query in queries.items():
    old=json.loads((SEALED/(name+'.json')).read_text())
    items=old['answer']['items']
    rows.append({'id':name,'query':query,'category':old['kind'],'origin':'existing_verified',
                 'expected_items':items, 'expected_count':len(items),
                 'source':str((SEALED/(name+'.json')).relative_to(ROOT))})

new=[
('GB3838-2002',['1.1','1.2'],'列出《地表水环境质量标准》1.1至1.2条的全部规定'),
('GB5084-2021',['4.1.1','4.1.2'],'逐条列出 GB5084-2021 第4.1.1至4.1.2条的全部规定'),
('GBT14848-2017',['3.1','3.2','3.3','3.4'],'完整列出 GB/T14848-2017 第3.1至3.4条的术语和定义'),
('GB11607-89',['4.1','4.2','4.3'],'列出 GB11607-89 第4.1至4.3条的全部渔业水质保护要求')]
for part,nums,query in new:
    r=new_prose(part,nums,query);r['id']='new-prose-'+part;r['origin']='independent_raw_source'
    # Preserve relevant whole source block(s), so the reviewer can verify the
    # entire definitions and clause boundaries before running either path.
    p,blocks=text_blocks(part)
    r['expected_source_blocks']=[b for b in blocks if any(re.search(r'(?<![\d.])'+re.escape(n)+r'(?![\d.])',b.get('text') or b.get('content') or '') for n in nums)]
    assert r['expected_source_blocks'],part
    r.pop('raw_source_text');r['expected_count']=len(nums);rows.append(r)
for part,skip,query in [
('HJ2.2-2018',1,'列出 HJ2.2-2018 表2的全部评价工作等级和分级判据'),
('GB13271-2014',2,'列出 GB13271-2014 表2新建锅炉全部污染物的限值和监控位置')]:
    p=file_for(part,'.tables.json');tables=json.loads(p.read_text())['tables']
    table=next(v for k,v in tables.items() if k.endswith('-0002'))
    grid=full_grid(table['content'])
    rows.append({'id':'new-table-'+part,'query':query,'category':'table','origin':'independent_raw_source',
                 'expected_cells':grid[skip:],'expected_count':len(grid)-skip,
                 'source':str(p.relative_to(ROOT)),'table_id':table['id'],
                 'expected_header':grid[:skip],'footnotes':table['footnotes']})
controls=[
('unconfirmed-table','列出 GB8978-1996 表2的全部项目','ambiguous'),
('judgement','GB3838-2002 的表1与 GB3095-2012 的表1是同一张表吗？','general_not_enumeration'),
('no-document','列出表1的全部项目和限值。','clarification'),
('name-year-ambiguity','列出《环境空气质量标准》表1全部限值。','clarification'),
('no-document-terms','列出第3章的全部术语和定义。','clarification'),
('general-mixing','GB3097-1997 对混合区有什么规定？','general_not_enumeration'),
('general-footnote','GB5084-2021 表1脚注 a、b 分别适用于哪些蔬菜？','general_not_enumeration'),
('general-assessment','GB3838-2002 的水质评价主要怎么做？','general_not_enumeration')]
for cid,q,e in controls:rows.append({'id':cid,'query':q,'category':'control','expected_behavior':e})
assert len(rows)==20 and sum(r['category']!='control' for r in rows)==12
sources={r['source'] for r in rows if 'source' in r}
manifest={s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in sorted(sources)}
with (OUT/'acceptance-matrix.json').open('x') as f:
 json.dump({'cases':rows,'source_sha256':manifest,'frozen_before_native_live':True,
            'criteria':{'corrected_local_set_errors_min':3,'new_errors_on_correct_local':0,
                        'controls_false_complete_enum':0},
            'interpretation':'Native original prompt product baseline; extra uniform generation is separate. No expectation enters generation.'},f,ensure_ascii=False,indent=2)
print('frozen cases',len(rows),'enum',12,'controls',8)
