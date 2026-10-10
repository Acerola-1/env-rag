"""Offline acceptance audit; reads submitted files and original sidecars only."""
import hashlib
import json
import re
import urllib.parse
from pathlib import Path

from env_rag_final.enumerate_.tables import read_html_table

root = Path.cwd()
out = root / 'reports/pg-retrieval/phase-3-answer-review'
manifest = json.loads((root / 'reports/pg-retrieval/phase-3-answer/answer-manifest.json').read_text())
sha_checks = []
for path, expected in manifest['sha256'].items():
    actual = hashlib.sha256((root / path).read_bytes()).hexdigest()
    sha_checks.append({'path': path, 'expected': expected, 'actual': actual, 'match': actual == expected})

inv = [json.loads(line) for line in (root / 'reports/pg-retrieval/phase-0/inventory.jsonl').read_text().splitlines()]
docs = {r['doc_id']: r for r in inv if r.get('kind') == 'db_doc'}
cache = {}
def sources(doc_id):
    if doc_id not in cache:
        directory = Path(urllib.parse.unquote(docs[doc_id]['sidecar_location'].removeprefix('file://')))
        table_data = json.loads(next(directory.glob('*.tables.json')).read_text())['tables']
        blocks = [json.loads(line) for line in next(directory.glob('*.blocks.jsonl')).read_text().splitlines()]
        cache[doc_id] = (table_data, {b.get('blockid'): b.get('content', '') for b in blocks})
    return cache[doc_id]

def normalize(s):
    return re.sub(r'\s+', '', s)

runs = []
for directory in ['phase-3-answer', 'phase-3-answer-enums', 'phase-3-answer-syn-check', 'phase-3-answer-syn', 'phase-3-answer-syn2']:
    path = root / 'reports/pg-retrieval' / directory / 'answer-runtime-latest.json'
    report = json.loads(path.read_text())
    results = []
    for result in report['results']:
        checks = []
        for item in (result.get('answer') or {}).get('items') or []:
            citation = item.get('citation') or {}
            tables, blocks = sources(citation['doc_id'])
            if item['kind'] == 'table_row':
                grid = read_html_table(tables[citation['table_id']]['content'])
                row = grid[citation['row_in_fragment']]
                valid = [normalize(c) for c in row] == [normalize(c) for c in item['cells']]
            else:
                segments = citation.get('unit_segments') or [{'unit_id': citation['unit_id'], 'rel_start': citation['unit_rel_start'], 'rel_end': citation['unit_rel_end']}]
                parts = [blocks[s['unit_id']][s['rel_start']:s['rel_end']] for s in segments]
                valid = normalize(citation['quote']) in normalize(''.join(parts))
            checks.append({'kind': item['kind'], 'doc_id': citation['doc_id'], 'locator': citation.get('locator'), 'valid': valid})
        model = result.get('model') or {}
        results.append({'query_id': result['query_id'], 'coverage_status': result['coverage_status'], 'raw_citation_checks': checks, 'model_status': model.get('status'), 'model_failure': model.get('failure'), 'model_receipt': model.get('call'), 'submitted_reverification': result.get('reverification'), 'note': 'Failed synthesis has no answer items; its eight source position claims are not independently accepted from summary counts alone.' if model.get('used') else None})
    runs.append({'path': str(path.relative_to(root)), 'model_calls_used': report.get('model_calls_used'), 'identity_matches_in_submitted_log': [report['identity_before']['matches_frozen'], report['identity_after']['matches_frozen']], 'identity_drift': report.get('identity_drift', []), 'results': results})

preview = json.loads((out / 'ocr-preview.json').read_text())
reviewed = {'src/env_rag_final/answer.py', 'src/env_rag_final/cli.py', 'openspec/changes/add-pg-scoped-retrieval/tasks.md', 'reports/pg-retrieval/phase-3-answer/answer-manifest.json', 'reports/pg-retrieval/phase-3-answer/answer-report.md'}
coverage = []
for entry in preview['reviewable_files']:
    checked = entry['path'] in reviewed
    coverage.append({'path': entry['path'], 'status': entry['status'], 'disposition': 'reviewed' if checked else 'skipped', 'reason': '5.5 changed code/owning caller and submission records.' if checked else 'Outside this bounded 5.5 checkpoint; previous phases retain their acceptance, no renewed full-workspace audit.'})
summary = {'reviewable_entries': len(coverage), 'reviewed_entries': sum(c['disposition'] == 'reviewed' for c in coverage), 'skipped_entries': sum(c['disposition'] == 'skipped' for c in coverage), 'all_preview_entries_accounted_for': True, 'manual_context': ['tests/test_answer.py (OCR default exclusion; read fixtures and all test cases)', 'tests/test_answer_review_r1.py (independent owning-entry acceptance)', 'openspec/changes/add-pg-scoped-retrieval/handoff-phase-3-5.5.md']}
summary['coverage_rate'] = summary['reviewed_entries'] / summary['reviewable_entries']
(out / 'coverage.json').write_text(json.dumps({'summary': summary, 'entries': coverage}, ensure_ascii=False, indent=2) + '\n')
(out / 'evidence-audit.json').write_text(json.dumps({'method': 'Offline raw grid and raw block slices; no database or model request by reviewer.', 'sha_checks': sha_checks, 'runs': runs, 'cache_limit': 'Equal row counts cannot demonstrate zero cache reads or updates; code path inspection is separate evidence.'}, ensure_ascii=False, indent=2) + '\n')
print('manifest matches', sum(x['match'] for x in sha_checks), '/', len(sha_checks))
print('independent answer citation checks', sum(c['valid'] for r in runs for x in r['results'] for c in x['raw_citation_checks']), '/', sum(len(x['raw_citation_checks']) for r in runs for x in r['results']))
print('OCR coverage', summary)
