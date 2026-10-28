/* Flow E warning page: details of one completed download, with
   "Show in folder" and "Delete". There is deliberately no "Open". */

import { localize, t } from "../lib/i18n.js";

const id = Number(new URLSearchParams(location.search).get("id"));
const SAFE_DANGER = new Set(["safe", "accepted", undefined]);

function size(bytes) {
  if (!(bytes > 0)) return "";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const formatted = new Intl.NumberFormat(browser.i18n.getUILanguage(), {
    maximumFractionDigits: unit ? 1 : 0,
  }).format(value);
  return `${formatted} ${units[unit]}`;
}

function host(url) {
  try {
    return new URL(url).host;
  } catch {
    return "";
  }
}

function finish(message, level) {
  const result = document.getElementById("result");
  result.textContent = message;
  result.dataset.level = level;
  result.hidden = false;
  document.getElementById("actions").hidden = true;
  document.documentElement.dataset.state = level === "ok" ? "deleted" : "error";
}

async function render() {
  localize();
  const [item] = Number.isInteger(id) ? await browser.downloads.search({ id }) : [];
  if (!item) {
    finish(t("warnMissing"), "error");
    document.getElementById("callout").hidden = true;
    return;
  }
  document.getElementById("file").hidden = false;
  document.getElementById("file-name").textContent = item.filename.split("/").pop();
  const source = host(item.finalUrl || item.url);
  document.getElementById("file-meta").textContent = [
    size(item.fileSize || item.totalBytes),
    source ? t("warnFrom", [source]) : "",
    t("warnDone"),
  ].filter(Boolean).join(" · ");
  const show = document.getElementById("show");
  const remove = document.getElementById("delete");
  let primary = show; // a program: look at it in its folder first; deleting is the second choice
  if (!SAFE_DANGER.has(item.danger)) {
    // A verdict says it is dangerous: deleting is the safe action, with the critical icon and words.
    document.documentElement.dataset.severity = "critical";
    document.title = t("warnTitleDanger");
    document.getElementById("warn-headline").textContent = t("warnHeadlineDanger");
    document.getElementById("callout-text").textContent = t("warnDanger");
    document.getElementById("callout").classList.replace("callout--warning", "callout--critical");
    // <svg> has no .hidden property: toggle the attribute itself.
    document.getElementById("icon-warning").setAttribute("hidden", "");
    document.getElementById("icon-critical").removeAttribute("hidden");
    remove.textContent = t("warnDeleteFile");
    remove.className = "button button--primary";
    show.className = "button button--secondary";
    remove.after(show); // the primary comes first
    primary = remove;
  } else {
    document.documentElement.dataset.severity = "warning";
  }
  document.getElementById("actions").hidden = false;
  primary.focus();

  document.getElementById("show").addEventListener("click", () => browser.downloads.show(item.id));
  document.getElementById("delete").addEventListener("click", async () => {
    try {
      await browser.downloads.removeFile(item.id);
      await browser.downloads.erase({ id: item.id });
      finish(t("warnDeleted"), "ok");
    } catch {
      finish(t("warnDeleteFailed"), "error");
    }
  });
  document.documentElement.dataset.state = "ready";
}

render();
