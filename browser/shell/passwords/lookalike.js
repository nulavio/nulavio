/* Flow D: this site looks like one where you keep a saved login. Going to the real site is the
   first choice; continuing is remembered for this pair of sites in this profile only, says so next
   to the button, and can be undone in Settings › Passwords. In a private window it is remembered for
   private windows only, in memory, until the last one closes, and the note says so.

   The page's address carries the site's address (`url`) and, when the password field was in a frame of
   the tab's page, a flag with no address (`in=frame`): "continue" then goes back to the tab's page in the
   tab's history, not to the frame's document; with no page to go back to, it is not offered. Which saved
   site `url` looks like is asked of the passwords module, which compares its origin (the module needs
   only the host) with this profile's saved logins again: another extension can open this page with
   parameters of its own, and the page names no site the module did not and goes to no address but
   `url`, or back. "Continue" passes the pair it shows, and the module remembers it only if it still finds
   that same pair for `url`; otherwise nothing is remembered and the page stays, saying so. */

import { localize, t } from "../lib/i18n.js";
import { closeOwnTab } from "../lib/tabs.js";
import { announce } from "../lib/ui.js";

const params = new URLSearchParams(location.search);
const HOST = /^[a-z0-9.-]+$/i;

function webAddress(value) {
  try {
    const url = new URL(value);
    return /^https?:$/.test(url.protocol) ? url : null;
  } catch {
    return null;
  }
}

localize();
const url = webAddress(params.get("url"));
// "continue" goes back to the tab's page when the field was in one of its frames (the warning is the entry after
// it), else to the site itself. With no entry before this one in the tab's history (the engine's, which the module
// reads), there is no way on but the real site, and the module remembers nothing without one.
const back = params.has("in");
const onward = !back || (await browser.nulavioPasswords.canGoBack().catch(() => false));
const origin = url ? `${url.origin}/` : "";
const verdict = url ? await browser.nulavioPasswords.check(origin).catch(() => null) : null;
const site = verdict?.suspicious ? String(verdict.site ?? "") : "";
const similar = verdict?.suspicious ? String(verdict.similar ?? "") : "";
if (url && HOST.test(similar) && site) {
  document.getElementById("explain").textContent = t("lookalikeBody", [site, similar]);
  document.getElementById("address").textContent = url.href;
  const real = document.getElementById("go-real");
  real.textContent = t("lookalikeGoReal", [similar]);
  real.addEventListener("click", () => location.replace(`https://${similar}/`));
  const button = document.getElementById("continue");
  const note = document.getElementById("continue-note");
  // In a private window (the module says so, from the engine), "continue" is kept in memory for private windows
  // only, until the last one closes, and nothing is written to the profile: the note and the reason say that instead.
  // The reason has no text until this answer, so it never says the other one while the page waits for it.
  const inPrivate = verdict.inPrivate === true;
  note.textContent = t(inPrivate ? "lookalikeContinueNotePrivate" : "lookalikeContinueNote", [site, similar]);
  document.getElementById("why-continue").textContent = t(inPrivate ? "lookalikeWhy3Private" : "lookalikeWhy3");
  button.hidden = note.hidden = !onward;
  button.addEventListener("click", async () => {
    button.disabled = true;
    let answer;
    try {
      // The pair this page shows: the module remembers it only if it still finds that same pair for the address.
      answer = await browser.nulavioPasswords.dismiss(origin, site, similar, back);
    } catch (e) {
      // Not remembered: do not open the site as if it were (the warning would silently differ next time). With no
      // page to go back to any more, only the real site is left.
      console.error("look-alike: could not remember the choice", e);
      button.disabled = false;
      button.hidden = note.hidden = e?.message === "no-way-back";
      announce(t("lookalikeDismissFailed"), "error");
      return;
    }
    if (answer?.dismissed !== true) {
      // Nothing remembered: the module no longer finds the pair shown (the saved logins changed meanwhile).
      button.disabled = false;
      announce(t("lookalikeDismissFailed"), "error");
      return;
    }
    if (back) {
      history.back();
    } else {
      location.replace(url.href);
    }
  });
  document.body.dataset.state = "ready";
  real.focus();
} else {
  // Opened without a site to compare (a hand-made or damaged address, or one the module finds nothing
  // for): say so, and leave only a way out. No warning, no empty address and no button that would do
  // nothing (audit 2026-11 S-01). The tab keeps the page's one title: another extension can read a tab's
  // title, and a different one here would tell it whether this profile keeps a login the address imitates.
  document.getElementById("headline").textContent = t("lookalikeInvalidHeadline");
  const callout = document.querySelector(".callout");
  callout.classList.replace("callout--warning", "callout--info");
  callout.setAttribute("role", "status");
  callout.querySelector("svg").setAttribute("hidden", ""); // <svg> has no .hidden property
  document.getElementById("explain").textContent = t("lookalikeInvalid");
  for (const selector of ["#address", "#continue", "#continue-note", "details.why"]) {
    document.querySelector(selector).hidden = true;
  }
  const close = document.getElementById("go-real");
  close.textContent = t("warnCloseTab");
  close.addEventListener("click", () => closeOwnTab());
  document.body.dataset.state = "invalid";
  close.focus();
}
document.documentElement.dataset.ready = "true";
