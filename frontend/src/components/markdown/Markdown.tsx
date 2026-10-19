// Tiny, safe Markdown renderer (server component, no dependencies).
//
// Builds React elements only (never injects an HTML string), raw HTML in the source renders as text, and links
// keep only http(s) and relative targets (anything else, e.g. javascript:, data: or mailto:, renders as text).
// Supported: ATX headings (with id anchors), paragraphs, **bold**, *italic* / _italic_, `code`, [links](url),
// ordered and unordered lists (nesting by indentation), GFM tables, fenced code blocks, blockquotes and
// horizontal rules. Written for docs we own (the working paper), not for arbitrary user content.
import type { ReactNode } from "react";

import styles from "./Markdown.module.css";

export type Heading = { level: number; text: string; id: string };

type Inline = string;
type Block =
  | { type: "heading"; level: number; text: Inline; id: string }
  | { type: "paragraph"; text: Inline }
  | { type: "code"; lang: string; code: string }
  | { type: "hr" }
  | { type: "quote"; children: Block[] }
  | { type: "list"; ordered: boolean; start: number; items: Block[][] }
  | { type: "table"; align: ("left" | "right" | "center" | null)[]; head: Inline[]; rows: Inline[][] };

const FENCE = /^ {0,3}(`{3,}|~{3,})\s*([\w+-]*)\s*$/;
const HEADING = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
const HR = /^ {0,3}([-*_])(\s*\1){2,}\s*$/;
const QUOTE = /^ {0,3}>\s?/;
const LIST_ITEM = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
const TABLE_SEP = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

/** Plain text of inline markdown (for ids, the table of contents and metadata). */
export function plainText(text: string): string {
  return text
    .replace(/`([^`]*)`/g, "$1")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/(\*\*|__)(.+?)\1/g, "$2")
    .replace(/(^|\W)[*_](\S(?:.*?\S)?)[*_](?=\W|$)/g, "$1$2")
    .replace(/\\([\\`*_{}[\]()#+\-.!|>~])/g, "$1")
    .trim();
}

export function slugify(text: string): string {
  return (
    plainText(text)
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9\s-]/g, "")
      .trim()
      .replace(/\s+/g, "-")
      .replace(/-+/g, "-") || "section"
  );
}

function splitRow(line: string): string[] {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
  const cells: string[] = [];
  let cur = "";
  for (let i = 0; i < s.length; i++) {
    if (s[i] === "\\" && s[i + 1] === "|") {
      cur += "|";
      i++;
    } else if (s[i] === "|") {
      cells.push(cur.trim());
      cur = "";
    } else {
      cur += s[i];
    }
  }
  cells.push(cur.trim());
  return cells;
}

function isBlockStart(line: string, next: string | undefined): boolean {
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    HR.test(line) ||
    QUOTE.test(line) ||
    LIST_ITEM.test(line) ||
    (line.trim().startsWith("|") && next !== undefined && TABLE_SEP.test(next))
  );
}

function parseBlocks(lines: string[], ids: Map<string, number>): Block[] {
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }

    const fence = FENCE.exec(line);
    if (fence) {
      const marker = fence[1];
      const code: string[] = [];
      i++;
      while (i < lines.length && !(lines[i].trim().startsWith(marker[0].repeat(marker.length)) && FENCE.test(lines[i]))) {
        code.push(lines[i]);
        i++;
      }
      i++; // closing fence (or end of input)
      blocks.push({ type: "code", lang: fence[2], code: code.join("\n") });
      continue;
    }

    const heading = HEADING.exec(line);
    if (heading) {
      const text = heading[2];
      const base = slugify(text);
      const seen = ids.get(base) ?? 0;
      ids.set(base, seen + 1);
      blocks.push({ type: "heading", level: heading[1].length, text, id: seen ? `${base}-${seen}` : base });
      i++;
      continue;
    }

    if (HR.test(line)) {
      blocks.push({ type: "hr" });
      i++;
      continue;
    }

    if (QUOTE.test(line)) {
      const inner: string[] = [];
      while (i < lines.length && lines[i].trim() && QUOTE.test(lines[i])) {
        inner.push(lines[i].replace(QUOTE, ""));
        i++;
      }
      blocks.push({ type: "quote", children: parseBlocks(inner, ids) });
      continue;
    }

    if (line.trim().startsWith("|") && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      const head = splitRow(line);
      const align = splitRow(lines[i + 1]).map((c) =>
        c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : c.startsWith(":") ? "left" : null,
      );
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = splitRow(lines[i]);
        rows.push(head.map((_, k) => cells[k] ?? ""));
        i++;
      }
      blocks.push({ type: "table", align, head, rows });
      continue;
    }

    const item = LIST_ITEM.exec(line);
    if (item) {
      const indent = item[1].length;
      const ordered = /\d/.test(item[2]);
      const start = ordered ? parseInt(item[2], 10) : 1;
      const items: Block[][] = [];
      while (i < lines.length) {
        const m = LIST_ITEM.exec(lines[i]);
        if (!m || m[1].length !== indent || /\d/.test(m[2]) !== ordered) break;
        const body = [m[3]];
        i++;
        // Continuation: indented deeper than the marker (nested lists included) or lazy paragraph lines.
        while (i < lines.length) {
          const l = lines[i];
          if (!l.trim()) {
            const nextLine = lines[i + 1];
            if (nextLine !== undefined && nextLine.trim() && nextLine.length - nextLine.trimStart().length > indent) {
              body.push("");
              i++;
              continue;
            }
            break;
          }
          const lead = l.length - l.trimStart().length;
          if (lead > indent) {
            body.push(l.slice(Math.min(lead, indent + 2)));
            i++;
            continue;
          }
          if (isBlockStart(l, lines[i + 1])) break;
          body.push(l.trim());
          i++;
        }
        items.push(parseBlocks(body, ids));
      }
      blocks.push({ type: "list", ordered, start, items });
      continue;
    }

    const para: string[] = [line.trim()];
    i++;
    while (i < lines.length && lines[i].trim() && !isBlockStart(lines[i], lines[i + 1])) {
      para.push(lines[i].trim());
      i++;
    }
    blocks.push({ type: "paragraph", text: para.join(" ") });
  }
  return blocks;
}

export function parseMarkdown(source: string): Block[] {
  return parseBlocks(source.replace(/\r\n?/g, "\n").split("\n"), new Map());
}

/** Headings of the document (same ids as the rendered anchors), e.g. for a table of contents. */
export function headings(source: string, levels: number[] = [2]): Heading[] {
  const out: Heading[] = [];
  const walk = (blocks: Block[]) => {
    for (const b of blocks) {
      if (b.type === "heading" && levels.includes(b.level)) out.push({ level: b.level, text: plainText(b.text), id: b.id });
      else if (b.type === "quote") walk(b.children);
      else if (b.type === "list") b.items.forEach(walk);
    }
  };
  walk(parseMarkdown(source));
  return out;
}

/** Only http(s) URLs and relative links (path, ?query or #fragment) are allowed; null means "render as text". */
export function safeHref(raw: string): { href: string; external: boolean } | null {
  // Browsers ignore control characters and whitespace inside a scheme ("java\tscript:"), so strip them first.
  const url = raw.replace(/[\u0000- \u007f]/g, "");
  if (!url) return null;
  if (/^https?:\/\/[^/]/i.test(url)) return { href: url, external: true };
  if (url.startsWith("//") || url.startsWith("\\")) return null; // protocol-relative: leave the site
  // Any scheme before the first / ? # is rejected (javascript:, data:, vbscript:, mailto:, file:, ...).
  const head = url.split(/[/?#]/, 1)[0];
  if (head.includes(":")) return null;
  return { href: url, external: false };
}

const ESCAPABLE = "\\`*_{}[]()#+-.!|>~";

function findClosing(text: string, from: number, delim: string): number {
  let j = text.indexOf(delim, from);
  while (j !== -1) {
    if (text[j - 1] !== "\\" && j > from && text[j - 1] !== " ") {
      // A single * must not be the first char of a ** pair.
      if (delim.length === 1 && delim !== "_" && text[j + 1] === delim) {
        j = text.indexOf(delim, j + 2);
        continue;
      }
      return j;
    }
    j = text.indexOf(delim, j + 1);
  }
  return -1;
}

/** Index of the ")" that closes a link target starting at `from` (balanced parentheses), or -1. */
function closingParen(text: string, from: number): number {
  let depth = 0;
  for (let j = from; j < text.length; j++) {
    if (text[j] === "\\") j++;
    else if (text[j] === "(") depth++;
    else if (text[j] === ")") {
      if (depth === 0) return j;
      depth--;
    }
  }
  return -1;
}

function renderInline(text: string, key = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let buf = "";
  let n = 0;
  const flush = () => {
    if (buf) out.push(buf);
    buf = "";
  };
  const k = () => `${key}-${n++}`;
  const isWord = (c: string | undefined) => !!c && /[\p{L}\p{N}]/u.test(c);

  for (let i = 0; i < text.length; i++) {
    const c = text[i];

    if (c === "\\" && i + 1 < text.length && ESCAPABLE.includes(text[i + 1])) {
      buf += text[i + 1];
      i++;
      continue;
    }

    if (c === "`") {
      let ticks = 1;
      while (text[i + ticks] === "`") ticks++;
      const fence = "`".repeat(ticks);
      const end = text.indexOf(fence, i + ticks);
      if (end !== -1) {
        flush();
        out.push(<code key={k()}>{text.slice(i + ticks, end).trim() || text.slice(i + ticks, end)}</code>);
        i = end + ticks - 1;
        continue;
      }
      buf += fence;
      i += ticks - 1;
      continue;
    }

    if ((c === "*" || c === "_") && text[i + 1] === c && text[i + 2] && text[i + 2] !== " ") {
      const delim = c + c;
      if (c === "*" || !isWord(text[i - 1])) {
        const end = findClosing(text, i + 2, delim);
        if (end !== -1 && (c === "*" || !isWord(text[end + 2]))) {
          flush();
          out.push(<strong key={k()}>{renderInline(text.slice(i + 2, end), k())}</strong>);
          i = end + 1;
          continue;
        }
      }
    }

    if ((c === "*" || c === "_") && text[i + 1] && text[i + 1] !== " " && text[i + 1] !== c) {
      if (c === "*" || !isWord(text[i - 1])) {
        const end = findClosing(text, i + 1, c);
        if (end !== -1 && (c === "*" || !isWord(text[end + 1]))) {
          flush();
          out.push(<em key={k()}>{renderInline(text.slice(i + 1, end), k())}</em>);
          i = end;
          continue;
        }
      }
    }

    if (c === "[") {
      const close = text.indexOf("](", i + 1);
      const end = close === -1 ? -1 : closingParen(text, close + 2);
      if (close !== -1 && end !== -1 && !text.slice(i + 1, close).includes("[")) {
        const label = text.slice(i + 1, close);
        const target = text.slice(close + 2, end).trim().split(/\s+/, 1)[0] ?? "";
        const safe = safeHref(target);
        flush();
        if (safe) {
          out.push(
            <a key={k()} href={safe.href} {...(safe.external ? { target: "_blank", rel: "noopener noreferrer" } : {})}>
              {renderInline(label, k())}
            </a>,
          );
        } else {
          // Unsafe or unsupported scheme: show the label and the raw target as plain text.
          out.push(<span key={k()}>{`${label} (${target})`}</span>);
        }
        i = end;
        continue;
      }
    }

    buf += c;
  }
  flush();
  return out;
}

function renderBlocks(blocks: Block[], key = "b"): ReactNode[] {
  return blocks.map((b, idx) => {
    const k = `${key}-${idx}`;
    switch (b.type) {
      case "heading": {
        const Tag = `h${b.level}` as "h1" | "h2" | "h3" | "h4" | "h5" | "h6";
        return (
          <Tag key={k} id={b.id}>
            {renderInline(b.text, k)}
          </Tag>
        );
      }
      case "paragraph":
        return <p key={k}>{renderInline(b.text, k)}</p>;
      case "code":
        return (
          <pre key={k} className={styles.pre} tabIndex={0}>
            <code data-lang={b.lang || undefined}>{b.code}</code>
          </pre>
        );
      case "hr":
        return <hr key={k} />;
      case "quote":
        return <blockquote key={k}>{renderBlocks(b.children, k)}</blockquote>;
      case "list": {
        const items = b.items.map((item, j) => {
          // A one-paragraph item renders inline (tight list).
          const only = item.length === 1 && item[0].type === "paragraph" ? item[0] : null;
          return <li key={`${k}-${j}`}>{only ? renderInline(only.text, `${k}-${j}`) : renderBlocks(item, `${k}-${j}`)}</li>;
        });
        return b.ordered ? (
          <ol key={k} start={b.start !== 1 ? b.start : undefined}>
            {items}
          </ol>
        ) : (
          <ul key={k}>{items}</ul>
        );
      }
      case "table":
        return (
          <div key={k} className={styles.tableWrap} role="region" aria-label="Table (scrolls horizontally)" tabIndex={0}>
            <table>
              <thead>
                <tr>
                  {b.head.map((cell, j) => (
                    <th key={j} scope="col" style={b.align[j] ? { textAlign: b.align[j]! } : undefined}>
                      {renderInline(cell, `${k}-h${j}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, j) => (
                      <td key={j} style={b.align[j] ? { textAlign: b.align[j]! } : undefined}>
                        {renderInline(cell, `${k}-${r}-${j}`)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
    }
  });
}

export default function Markdown({ source, className }: { source: string; className?: string }) {
  return <div className={className ? `${styles.md} ${className}` : styles.md}>{renderBlocks(parseMarkdown(source))}</div>;
}
