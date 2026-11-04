/* The assistant's answers as a small, safe Markdown (UX5-E).

   Only these elements come out: p, br, strong, em, code, pre, ul, ol, li, blockquote, all made
   with h() and text nodes; nothing is parsed as HTML, so any HTML in an answer shows as text.
   Nothing here can make a request: no images, no clickable links, no styles. A link becomes its
   text and "(host)"; an image stays as its Markdown text. The model's headings become bold
   paragraphs, so they never enter the panel's own heading outline. */

import { h } from "./ui.js";

// Inline marks other than code (code spans are cut first, in one pass, and their content is literal).
// Text longer than INLINE_MAX is shown as it is: no pattern ever runs on a huge line (review UX5-E F4).
const INLINE_MAX = 4000;
const INLINE = new RegExp(
  [
    /!\[[^\]]*\]\((?:[^()]|\([^()]*\))*\)/.source, // ![image](address): kept as text
    /\[([^\]]+)\]\(((?:[^()\s]|\([^()\s]*\))*)(?:\s+"[^"]*")?\)/.source, // [text](address), one level of ( ) inside
    /\*\*(?=\S)([\s\S]*?\S)\*\*/.source, // **strong**
    /(?<![\w])__(?=\S)([\s\S]*?\S)__(?![\w])/.source, // __strong__
    /\*(?=[^\s*])([^*]*?[^\s*])\*/.source, // *em*
    /(?<![\w])_(?=[^\s_])([^_]*?[^\s_])_(?![\w])/.source, // _em_
  ].join("|"),
  "g"
);

/** The host a link names, for web addresses only (a javascript: or data: link shows its text alone). */
function host(address) {
  const url = URL.parse(address);
  return url && /^https?:$/.test(url.protocol) ? url.host : "";
}

/** `code` spans, found by scanning for a closing run of the same length (linear: no backtracking). */
function codeSpans(text) {
  const out = [];
  let at = 0;
  let from = 0;
  while (from < text.length) {
    const start = text.indexOf("`", from);
    if (start < 0) {
      break;
    }
    let run = start;
    while (text[run] === "`") {
      run++;
    }
    const ticks = text.slice(start, run);
    let close = text.indexOf(ticks, run);
    while (close >= 0 && text[close + ticks.length] === "`") {
      let next = close;
      while (text[next] === "`") {
        next++;
      }
      close = text.indexOf(ticks, next);
    }
    if (close < 0) {
      from = run; // no closing run of that length: the backticks stay as text
      continue;
    }
    out.push(text.slice(at, start), { code: text.slice(run, close) });
    at = from = close + ticks.length;
  }
  out.push(text.slice(at));
  return out;
}

/** Inline Markdown in one line or paragraph, as nodes. */
function inline(text) {
  if (text.length > INLINE_MAX) {
    return [text];
  }
  return codeSpans(text).flatMap(part =>
    typeof part === "string" ? marks(part) : [h("code", { text: part.code.trim() || part.code })]
  );
}

function marks(text) {
  const out = [];
  let at = 0;
  for (const match of text.matchAll(INLINE)) {
    if (match.index > at) {
      out.push(text.slice(at, match.index));
    }
    const [whole, linkText, linkTo, strong1, strong2, em1, em2] = match;
    if (whole.startsWith("!")) {
      out.push(whole);
    } else if (linkText !== undefined) {
      const where = host(linkTo);
      out.push(...inline(linkText), where ? ` (${where})` : "");
    } else if (strong1 !== undefined || strong2 !== undefined) {
      out.push(h("strong", {}, ...inline(strong1 ?? strong2)));
    } else {
      out.push(h("em", {}, ...inline(em1 ?? em2)));
    }
    at = match.index + whole.length;
  }
  if (at < text.length) {
    out.push(text.slice(at));
  }
  return out;
}

/** Lines joined with <br> (a single line break in Markdown is shown as one here). */
function lines(list) {
  return list.flatMap((line, i) => (i ? [h("br"), ...inline(line)] : inline(line)));
}

const LIST_ITEM = /^\s{0,3}(?:([-*+])|(\d{1,9})[.)])\s+(.*)$/;
/** A heading's text, or null, without a pattern (a crafted line cannot make it slow). */
function heading(row) {
  const stripped = row.replace(/^ {0,3}/, "");
  if (!stripped.startsWith("#")) {
    return null;
  }
  let level = 0;
  while (stripped[level] === "#") {
    level++;
  }
  if (level > 6 || !/^[ \t]/.test(stripped.slice(level))) {
    return null;
  }
  let text = stripped.slice(level).trim();
  while (text.endsWith("#")) {
    text = text.slice(0, -1);
  }
  return text.trim();
}
const FENCE = /^\s{0,3}(```+|~~~+)/;
const QUOTE = /^\s{0,3}>\s?(.*)$/;

/** Block Markdown (paragraphs, lists, quotes, fenced code, headings) as nodes. */
function blocks(source) {
  const rows = source.replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0;
  while (i < rows.length) {
    const row = rows[i];
    if (!row.trim()) {
      i++;
      continue;
    }
    const fence = row.match(FENCE);
    if (fence) {
      const body = [];
      i++;
      while (i < rows.length && !rows[i].trimStart().startsWith(fence[1])) {
        body.push(rows[i++]);
      }
      i++; // the closing fence (or the end)
      out.push(h("pre", {}, h("code", { text: body.join("\n") })));
      continue;
    }
    const title = heading(row);
    if (title !== null) {
      out.push(h("p", {}, h("strong", {}, ...inline(title))));
      i++;
      continue;
    }
    if (QUOTE.test(row)) {
      const body = [];
      while (i < rows.length && QUOTE.test(rows[i])) {
        body.push(rows[i++].match(QUOTE)[1]);
      }
      out.push(h("blockquote", {}, ...blocks(body.join("\n"))));
      continue;
    }
    const item = row.match(LIST_ITEM);
    if (item) {
      const ordered = item[2] !== undefined;
      const items = [];
      while (i < rows.length) {
        const next = rows[i].match(LIST_ITEM);
        if (next && (next[2] !== undefined) === ordered) {
          items.push([next[3]]);
          i++;
        } else if (items.length && rows[i].trim() && /^\s+/.test(rows[i]) && !LIST_ITEM.test(rows[i])) {
          items.at(-1).push(rows[i++].trim()); // a continuation line of the item
        } else {
          break;
        }
      }
      const start = ordered ? Number(item[2]) : 1;
      out.push(h(ordered ? "ol" : "ul", ordered && start !== 1 ? { start } : {}, ...items.map(body => h("li", {}, ...lines(body)))));
      continue;
    }
    const paragraph = [];
    while (i < rows.length && rows[i].trim() && !FENCE.test(rows[i]) && heading(rows[i]) === null && !QUOTE.test(rows[i]) && !LIST_ITEM.test(rows[i])) {
      paragraph.push(rows[i++]);
    }
    out.push(h("p", {}, ...lines(paragraph)));
  }
  return out;
}

/** Replace `container`'s content with `text` rendered as safe Markdown. */
export function renderMarkdown(container, text) {
  container.replaceChildren(...blocks(String(text ?? "")));
}
