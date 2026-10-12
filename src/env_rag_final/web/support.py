"""Conservative row-value audit; paraphrases remain visibly unreviewed.

This is not an open-ended semantic judge. It can prove source identity and
reject unsupported measurements in cited table rows without another LLM.
"""

import re
import unicodedata

_NUMBER = re.compile(r"(?<![\w.])[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?(?![\w.])")
_CITE = re.compile(r"\[(?:citation:)?(\d+)\]")


def _subject_form(text):
    text = unicodedata.normalize("NFKC", text).lower()
    text = text.replace(r"\alpha", "α").replace(r"\beta", "β")
    return re.sub(r"[\s$*()（）,，|]", "", text)


def table_summary_problems(text, items):
    by_id = {str(i): item for i, item in enumerate(items, 1)}
    problems = []
    for line_number, line in enumerate(text.splitlines(), 1):
        # Only actual table output rows: narrative totals/code/year are not
        # measurement rows, and cannot be falsely claimed as validated here.
        if not line.lstrip().startswith("|"):
            continue
        ids = _CITE.findall(line)
        cited = [by_id[x] for x in ids if x in by_id and by_id[x].get("cells")]
        if not cited:
            continue
        values = {
            float(n) for item in cited for cell in item["cells"] for n in _NUMBER.findall(cell)
        }
        cleaned = _CITE.sub("", line)
        normalized = _subject_form(cleaned)
        for item in cited:
            cells = item["cells"]
            subject = (
                cells[1] if re.fullmatch(r"\d+", cells[0].strip()) and len(cells) > 1 else cells[0]
            )
            if _subject_form(subject) not in normalized:
                problems.append(
                    {"line": line_number, "reference_ids": ids, "unsupported_subject": subject}
                )
        # Latin pollutant designators such as PM2.5 aren't standalone values.
        for number in _NUMBER.findall(cleaned):
            if float(number) not in values:
                problems.append(
                    {"line": line_number, "reference_ids": ids, "unsupported_number": number}
                )
    return problems
