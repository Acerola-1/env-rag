"""Final I1 spot checks: JSON scalar types at owner and segment boundaries."""

import copy
import json
from pathlib import Path

from env_rag_final.enumerate_.prose_enum import UnitText, bind_citations, verify_citations

text = "引用原文完整存在，限值99。"
unit = UnitText("u", text, ["c"], {}, 0, len(text), False, "parsed_block")
base = bind_citations(
    [
        {
            "citation_verified": True,
            "citation": {"quote": text, "char_start": 0, "char_end": len(text)},
        }
    ],
    "default",
    "d",
    "s",
    [unit],
)
checks = []
for part in ("owner", "segment"):
    for edge in ("start", "end"):
        for invalid in (True, "invalid", None, 1.5):
            items = copy.deepcopy(base)
            cit = items[0]["citation"]
            if part == "owner":
                cit["unit_rel_" + edge] = invalid
            else:
                seg = {"unit_id": "u", "rel_start": 0, "rel_end": len(text)}
                seg["rel_" + edge] = invalid
                cit["unit_segments"] = [seg]
            result = verify_citations(items, text, [unit])
            passed = result[0]["citation_verified"] is False
            checks.append(
                {
                    "part": part,
                    "edge": edge,
                    "type": type(invalid).__name__,
                    "safely_rejected": passed,
                }
            )
assert all(c["safely_rejected"] for c in checks)
Path(__file__).with_name("guard-probes.json").write_text(
    json.dumps({"checks": checks, "passed": len(checks)}, indent=2) + "\n"
)
print("safe rejections", len(checks))
