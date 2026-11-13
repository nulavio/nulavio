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
  // A failed delete leaves the file where it was: "Mostrar na pasta" and another try stay
  // (audit 2026-11 S-01). Only a file that is gone has nothing left to act on.
  document.getElementById("actions").hidden = level === "ok";
  document.documentElement.dataset.state = level === "ok" ? "deleted" : "error";
}

/* The download is gone from the list (audit 2026-11 WARN-01/02): say so plainly, and offer the folder
   and closing the tab. Nothing here can open a file. */
function missing() {
  document.title = t("warnMissingTitle");
  document.getElementById("warn-headline").textContent = t("warnMissingHeadline");
  document.querySelector("details.why").hidden = true;
  const callout = document.getElementById("callout");
  callout.classList.replace("callout--warning", "callout--info");
  callout.setAttribute("role", "status");
  document.getElementById("icon-warning").setAttribute("hidden", "");
  document.getElementById("icon-info").removeAttribute("hidden");
  document.getElementById("callout-text").textContent = t("warnMissing");
  const folder = document.getElementById("show");
  const close = document.getElementById("delete");
  folder.textContent = t("warnOpenFolder");
  close.textContent = t("warnCloseTab");
  folder.addEventListener("click", () => browser.downloads.showDefaultFolder());
  close.addEventListener("click", async () => {
    const tab = await browser.tabs.getCurrent();
    const siblings = await browser.tabs.query({ windowId: tab.windowId });
    return siblings.length > 1 ? browser.tabs.remove(tab.id) : browser.tabs.update(tab.id, { url: "about:newtab" });
  });
  document.getElementById("actions").hidden = false;
  folder.focus();
  document.documentElement.dataset.state = "missing";
}

async function render() {
  localize();
  const [item] = Number.isInteger(id) ? await browser.downloads.search({ id }) : [];
  if (!item) {
    missing();
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
    } catch {
      finish(t("warnDeleteFailed"), "error");
      return;
    }
    // The file is gone. Its entry in the downloads list is only a record: when that cannot be dropped, the file
    // is deleted all the same, and saying "could not delete" with the file's actions back would be untrue.
    await browser.downloads.erase({ id: item.id }).catch(() => {});
    finish(t("warnDeleted"), "ok");
  });
  document.documentElement.dataset.state = "ready";
}

render();
