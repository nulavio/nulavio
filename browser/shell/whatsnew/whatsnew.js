/* What's new in this version (#198): the installed version's packed notes, shown as text
   (textContent only), and the switch for the bar after an update. Nothing is fetched: the
   link to every version's notes opens only when clicked. */

import { localize, t } from "../lib/i18n.js";

const LISTS = ["breaking", "action", "new", "fixed", "security"];

function fill(id, items) {
  const part = document.getElementById(`part-${id}`);
  const list = part.querySelector("ul");
  list.replaceChildren(
    ...items.map(text => {
      const li = document.createElement("li");
      li.textContent = text;
      return li;
    }),
  );
  part.hidden = items.length === 0;
}

async function render() {
  localize();
  const language = browser.i18n.getUILanguage();
  const portuguese = language.toLowerCase().startsWith("pt");
  document.getElementById("history").href = portuguese ? "https://nulavio.net/novidades/" : "https://nulavio.net/en/whats-new/";
  const notes = await browser.nulavioWhatsNew.notes(language).catch(() => ({ state: "unreadable" }));
  const article = document.querySelector(".whatsnew");
  if (notes.state === "ok") {
    document.getElementById("whatsnew-heading").textContent = t("whatsNewHeading", [notes.version]);
    const date = new Date(`${notes.date}T12:00:00Z`).toLocaleDateString(language, { dateStyle: "long", timeZone: "UTC" });
    const meta = document.getElementById("meta");
    meta.textContent = t("whatsNewMeta", [date, notes.firefox, notes.channel]);
    meta.hidden = false;
    const summary = document.getElementById("summary");
    summary.textContent = notes.summary;
    summary.hidden = false;
    for (const id of LISTS) {
      fill(id, notes[id] ?? []);
    }
  } else {
    document.getElementById("missing-text").textContent = t(notes.state === "none" ? "whatsNewNone" : "whatsNewUnreadable");
    document.getElementById("missing").hidden = false;
  }
  const notice = document.getElementById("notice");
  notice.checked = (await browser.nulavioWhatsNew.setting()).notice;
  notice.addEventListener("change", () => browser.nulavioWhatsNew.setNotice(notice.checked).catch(console.error));
  article.removeAttribute("aria-busy");
}

render().catch(console.error);
