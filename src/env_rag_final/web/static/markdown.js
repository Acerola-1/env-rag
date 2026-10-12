(() => {
  "use strict";

  const CITATION_PATTERN = /\[(?:citation:)?([A-Za-z0-9_.:-]+)\](?!\()/g;
  const FENCE_PATTERN = /^ {0,3}(`{3,}|~{3,})(.*)$/;
  const HEADING_PATTERN = /^ {0,3}(#{1,6})(?:[ \t]+|$)(.*)$/;
  const UNORDERED_PATTERN = /^ {0,3}[-+*][ \t]+(.*)$/;
  const ORDERED_PATTERN = /^ {0,3}(\d+)[.)][ \t]+(.*)$/;

  function appendInlineText(parent, text, citationFactory, allowBold = true) {
    const source = String(text ?? "");
    let cursor = 0;

    while (cursor < source.length) {
      let next = null;
      const consider = (candidate) => {
        if (!candidate) return;
        if (!next || candidate.start < next.start ||
            (candidate.start === next.start && candidate.priority < next.priority)) {
          next = candidate;
        }
      };

      if (allowBold) {
        const start = source.indexOf("**", cursor);
        const end = start < 0 ? -1 : source.indexOf("**", start + 2);
        if (end > start + 2) {
          consider({ start, end, type: "bold", priority: 0 });
        }
      }

      let codeStart = source.indexOf("`", cursor);
      while (codeStart >= 0) {
        const codeEnd = source.indexOf("`", codeStart + 1);
        if (codeEnd > codeStart + 1 && !source.slice(codeStart + 1, codeEnd).includes("\n")) {
          consider({ start: codeStart, end: codeEnd, type: "code", priority: 1 });
          break;
        }
        codeStart = source.indexOf("`", codeStart + 1);
      }

      CITATION_PATTERN.lastIndex = cursor;
      const citation = CITATION_PATTERN.exec(source);
      if (citation) {
        consider({
          start: citation.index,
          end: citation.index + citation[0].length,
          type: "citation",
          match: citation,
          priority: 2,
        });
      }

      if (!next) {
        parent.appendChild(document.createTextNode(source.slice(cursor)));
        break;
      }
      if (next.start > cursor) {
        parent.appendChild(document.createTextNode(source.slice(cursor, next.start)));
      }

      if (next.type === "bold") {
        const strong = document.createElement("strong");
        appendInlineText(strong, source.slice(next.start + 2, next.end), citationFactory, false);
        parent.appendChild(strong);
        cursor = next.end + 2;
        continue;
      }
      if (next.type === "code") {
        const code = document.createElement("code");
        code.textContent = source.slice(next.start + 1, next.end);
        parent.appendChild(code);
        cursor = next.end + 1;
        continue;
      }

      let replacement = null;
      if (typeof citationFactory === "function") {
        try {
          replacement = citationFactory(next.match[1]);
        } catch (_error) {
          replacement = null;
        }
      }
      if (replacement && typeof replacement.nodeType === "number") {
        parent.appendChild(replacement);
      } else {
        parent.appendChild(document.createTextNode(next.match[0]));
      }
      cursor = next.end;
    }
  }

  function splitTableRow(line) {
    const trimmed = line.trim();
    if (!trimmed.includes("|")) return null;

    let body = trimmed;
    if (body.startsWith("|")) body = body.slice(1);
    if (body.endsWith("|") && !body.endsWith("\\|")) body = body.slice(0, -1);

    const cells = [];
    let cell = "";
    let escaped = false;
    for (const character of body) {
      if (escaped) {
        cell += character === "|" ? "|" : `\\${character}`;
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === "|") {
        cells.push(cell.trim());
        cell = "";
      } else {
        cell += character;
      }
    }
    if (escaped) cell += "\\";
    cells.push(cell.trim());
    return cells;
  }

  function isTableSeparator(cells) {
    return Array.isArray(cells) && cells.length > 0 &&
      cells.every((cell) => /^:?-{3,}:?$/.test(cell));
  }

  function tableAt(lines, index) {
    if (index + 1 >= lines.length) return null;
    const header = splitTableRow(lines[index]);
    const separator = splitTableRow(lines[index + 1]);
    if (!header || !separator || !isTableSeparator(separator)) return null;

    const rows = [];
    let next = index + 2;
    while (next < lines.length) {
      const row = splitTableRow(lines[next]);
      if (!row || !lines[next].trim()) break;
      rows.push(row);
      next += 1;
    }

    const columnCount = Math.max(header.length, ...rows.map((row) => row.length));
    return { header, rows, columnCount, next };
  }

  function appendTableCell(row, tagName, value, citationFactory) {
    const cell = document.createElement(tagName);
    cell.style.whiteSpace = "normal";
    cell.style.overflowWrap = "anywhere";
    if (tagName === "th") cell.scope = "col";
    appendInlineText(cell, value, citationFactory);
    row.appendChild(cell);
  }

  function appendTable(parent, table, citationFactory) {
    const element = document.createElement("table");
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (let column = 0; column < table.columnCount; column += 1) {
      appendTableCell(headRow, "th", table.header[column] || "", citationFactory);
    }
    head.appendChild(headRow);
    element.appendChild(head);

    const body = document.createElement("tbody");
    for (const values of table.rows) {
      const row = document.createElement("tr");
      for (let column = 0; column < table.columnCount; column += 1) {
        appendTableCell(row, "td", values[column] || "", citationFactory);
      }
      body.appendChild(row);
    }
    element.appendChild(body);
    parent.appendChild(element);
  }

  function appendList(parent, lines, start, ordered, citationFactory) {
    const list = document.createElement(ordered ? "ol" : "ul");
    if (ordered) {
      const first = ORDERED_PATTERN.exec(lines[start]);
      const startNumber = first ? Number.parseInt(first[1], 10) : 1;
      if (Number.isFinite(startNumber) && startNumber !== 1) list.start = startNumber;
    }

    let next = start;
    while (next < lines.length) {
      const match = ordered
        ? ORDERED_PATTERN.exec(lines[next])
        : UNORDERED_PATTERN.exec(lines[next]);
      if (!match) break;
      const item = document.createElement("li");
      appendInlineText(item, ordered ? match[2] : match[1], citationFactory);
      list.appendChild(item);
      next += 1;
    }
    parent.appendChild(list);
    return next;
  }

  function isBlockStart(lines, index) {
    return FENCE_PATTERN.test(lines[index]) || HEADING_PATTERN.test(lines[index]) ||
      UNORDERED_PATTERN.test(lines[index]) || ORDERED_PATTERN.test(lines[index]) ||
      tableAt(lines, index) !== null;
  }

  function render(markdownText, citationFactory) {
    const fragment = document.createDocumentFragment();
    const source = String(markdownText ?? "").replace(/\r\n?/g, "\n");
    const lines = source.split("\n");
    let index = 0;

    while (index < lines.length) {
      if (!lines[index].trim()) {
        index += 1;
        continue;
      }

      const fence = FENCE_PATTERN.exec(lines[index]);
      if (fence) {
        const marker = fence[1];
        const markerCharacter = marker[0];
        const markerLength = marker.length;
        const codeLines = [];
        index += 1;
        while (index < lines.length) {
          const closing = /^ {0,3}(`+|~+)\s*$/.exec(lines[index]);
          if (closing && closing[1][0] === markerCharacter && closing[1].length >= markerLength) {
            index += 1;
            break;
          }
          codeLines.push(lines[index]);
          index += 1;
        }
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.textContent = codeLines.join("\n");
        pre.appendChild(code);
        fragment.appendChild(pre);
        continue;
      }

      const heading = HEADING_PATTERN.exec(lines[index]);
      if (heading) {
        const element = document.createElement(`h${heading[1].length}`);
        appendInlineText(element, heading[2], citationFactory);
        fragment.appendChild(element);
        index += 1;
        continue;
      }

      const table = tableAt(lines, index);
      if (table) {
        appendTable(fragment, table, citationFactory);
        index = table.next;
        continue;
      }

      const unordered = UNORDERED_PATTERN.test(lines[index]);
      const ordered = ORDERED_PATTERN.test(lines[index]);
      if (unordered || ordered) {
        index = appendList(fragment, lines, index, ordered, citationFactory);
        continue;
      }

      const paragraphLines = [lines[index]];
      index += 1;
      while (index < lines.length && lines[index].trim() && !isBlockStart(lines, index)) {
        paragraphLines.push(lines[index]);
        index += 1;
      }
      const paragraph = document.createElement("p");
      appendInlineText(paragraph, paragraphLines.join("\n"), citationFactory);
      fragment.appendChild(paragraph);
    }

    return fragment;
  }

  Object.defineProperty(window, "RAGMarkdown", {
    configurable: true,
    value: Object.freeze({ render }),
  });
})();
