| 题号 | 类别 | 反例 | pg | local | fusion |
|---|---|---|---|---|---|
| fact-001 | fact |  | complete 1项 | partial 0项 | complete 1项 rerank✓ |
| fact-002 | fact |  | partial 1项 | partial 1项 | partial 1项 rerank✓ |
| fact-003 | fact |  | complete 5项 | partial 0项 | complete 5项 rerank✓ |
| fact-004 | fact |  | complete 1项 | partial 0项 | complete 1项 rerank✓ |
| fact-005 | fact |  | complete 1项 | partial 0项 | complete 1项 rerank✓ |
| fact-006 | fact |  | complete 3项 | partial 0项 | complete 3项 rerank✓ |
| fact-007 | fact |  | complete 1项 | partial 0项 | complete 1项 rerank✓ |
| file-enum-001 | file_enum |  | complete 2项 | complete 2项 | complete 2项 rerank✓ |
| file-enum-002 | file_enum |  | complete 5项 | complete 5项 | complete 5项 rerank✓ |
| file-enum-003 | file_enum |  | complete 5项 | complete 5项 | complete 5项 rerank✓ |
| file-enum-004 | file_enum |  | complete 7项 | complete 7项 | complete 7项 rerank✓ |
| file-enum-005 | file_enum |  | complete 3项 | complete 1项 | complete 3项 rerank✓ |
| file-enum-006 | file_enum |  | complete 1项 | complete 1项 | complete 1项 rerank✓ |
| prose-enum-001 | prose_enum |  | complete 4项 | complete 17项 | complete 4项 rerank✓ |
| prose-enum-002 | prose_enum |  | complete 2项 | partial 3项 | complete 2项 rerank✓ |
| prose-enum-003 | prose_enum |  | complete 4项 | complete 4项 | complete 4项 rerank✓ |
| prose-enum-004 | prose_enum |  | complete 5项 | partial 0项 | complete 5项 rerank✓ |
| prose-enum-005 | prose_enum |  | partial 0项 | partial 0项 | partial 0项 rerank✓ |
| prose-enum-006 | prose_enum |  | complete 1项 | complete 13项 | complete 1项 rerank✓ |
| table-enum-001 | table_enum |  | complete 13项 | complete 13项 | complete 13项 rerank✓ |
| table-enum-002 | table_enum |  | complete 14项 | complete 31项 | complete 14项 rerank✓ |
| table-enum-003 | table_enum |  | ambiguous 72项 | ambiguous 77项 | ambiguous 72项 rerank✓ |
| table-enum-004 | table_enum |  | complete 24项 | ambiguous 24项 | complete 24项 rerank✓ |
| table-enum-005 | table_enum |  | complete 30项 | ambiguous 62项 | complete 30项 rerank✓ |
| table-enum-006 | table_enum |  | complete 14项 | ambiguous 124项 | complete 14项 rerank✓ |
| syn-001 | synthesis |  | partial 0项 incomplete_condition | partial 0项 incomplete_condition | partial 0项 incomplete_condition rerank✓ |
| syn-002 | synthesis |  | partial 4项 HTTP×1 model_failure | partial 0项 incomplete_condition | partial 0项 HTTP×1 model_failure rerank✓ |
| syn-003 | synthesis |  | partial 0项 HTTP×1 model_failure | partial 0项 incomplete_condition | partial 5项 HTTP×1 incomplete_answer_co rerank✓ |
| syn-004 | synthesis |  | partial 0项 HTTP×1 model_failure | partial 0项 incomplete_condition | partial 0项 HTTP×1 model_failure rerank✓ |
| syn-005 | synthesis |  | partial 0项 HTTP×1 model_failure | ambiguous 0项 HTTP×1 model_failure | partial 0项 HTTP×1 model_failure rerank✓ |
| syn-006 | synthesis |  | partial 0项 incomplete_condition | partial 0项 incomplete_condition | partial 0项 incomplete_condition rerank✓ |
| neg-001 | fact | 是 | missing 0项 | partial 0项 | missing 0项 |
| neg-002 | fact | 是 | partial 0项 | partial 0项 | partial 0项 rerank✓ |
| neg-003 | file_enum | 是 | complete 1项 | complete 1项 | complete 1项 rerank✓ |
| neg-004 | table_enum | 是 | complete 13项 | complete 44项 | complete 13项 rerank✓ |
| neg-005 | table_enum | 是 | complete 38项 | ambiguous 77项 | complete 38项 rerank✓ |
| neg-006 | fact | 是 | missing 0项 | partial 0项 | missing 0项 |
| neg-007 | table_enum | 是 | partial 0项 | partial 0项 | partial 0项 rerank✓ |
| neg-008 | prose_enum | 是 | BF:swallowed-refusal | BF:budget | BF:swallowed-refusal |
| neg-009 | file_enum | 是 | partial 0项 | partial 0项 | partial 0项 rerank✓ |
| neg-010 | synthesis | 是 | partial 0项 HTTP×1 model_failure | partial 0项 incomplete_condition | partial 4项 HTTP×1 model_failure rerank✓ |
