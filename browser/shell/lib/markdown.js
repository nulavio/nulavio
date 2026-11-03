/* The assistant's answers as a small, safe Markdown (UX5-E).

   Only these elements come out: p, br, strong, em, code, pre, ul, ol, li, blockquote, all made
   with h() and text nodes; nothing is parsed as HTML, so any HTML in an answer shows as text.
   Nothing here can make a request: no images, no clickable links, no styles. A link becomes its
   text and "(host)"; an image stays as its Markdown text. The model's headings become bold
   paragraphs, so they never enter the panel's own heading outline. */

import { h } from "./ui.js";

// Inline marks, in the order they are tried at each place: code first (its content is literal).
const INLINE = new RegExp(
  [
    /(`+)([\s\S]*?[^`])\1(?!`)/.source, // `code`
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

/** Inline Markdown in one line or paragraph, as nodes. */
function inline(text) {
  const out = [];
  let at = 0;
  for (const match of text.matchAll(INLINE)) {
    if (match.index > at) {
      out.push(text.slice(at, match.index));
    }
    const [whole, , code, linkText, linkTo, strong1, strong2, em1, em2] = match;
    if (code !== undefined) {
      out.push(h("code", { text: code.trim() || code }));
    } else if (whole.startsWith("!")) {
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
const HEADING = /^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$/;
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
    const heading = row.match(HEADING);
    if (heading) {
      out.push(h("p", {}, h("strong", {}, ...inline(heading[1]))));
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
    while (i < rows.length && rows[i].trim() && !FENCE.test(rows[i]) && !HEADING.test(rows[i]) && !QUOTE.test(rows[i]) && !LIST_ITEM.test(rows[i])) {
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
