/* Flow D: this site looks like one where you keep a saved login. Going to the real site is the
   first choice; continuing is remembered for this pair of sites in this profile only, says so next
   to the button, and can be undone in Settings › Passwords.

   The page's address carries the site's address (`url`) and, when the password field was in a frame of
   the tab's page, that page's address (`page`): "continue" goes back to it, not to the frame's document.
   `page` is never shown. Which saved site `url` looks like is asked of the passwords module, which
   compares it with this profile's saved logins again: another extension can open this page with
   parameters of its own, and the page names no site the module did not. */

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
// Where "continue" goes: the tab's page when the field was in one of its frames, else the site itself. A `page`
// that is not a site's address (the tab's page had none) leaves no way on but the real site.
const onwardTo = params.has("page") ? webAddress(params.get("page")) : url;
const verdict = url ? await browser.nulavioPasswords.check(url.href).catch(() => null) : null;
const site = verdict?.suspicious ? String(verdict.site ?? "") : "";
const similar = verdict?.suspicious ? String(verdict.similar ?? "") : "";
if (url && HOST.test(similar) && site) {
  document.getElementById("explain").textContent = t("lookalikeBody", [site, similar]);
  document.getElementById("address").textContent = url.href;
  const real = document.getElementById("go-real");
  real.textContent = t("lookalikeGoReal", [similar]);
  real.addEventListener("click", () => location.replace(`https://${similar}/`));
  const onward = document.getElementById("continue");
  const note = document.getElementById("continue-note");
  note.textContent = t("lookalikeContinueNote", [site, similar]);
  onward.hidden = note.hidden = !onwardTo;
  onward.addEventListener("click", async () => {
    onward.disabled = true;
    try {
      await browser.nulavioPasswords.dismiss(url.href);
    } catch (e) {
      // Not remembered: do not open the site as if it were (the warning would silently differ next time).
      console.error("look-alike: could not remember the choice", e);
      onward.disabled = false;
      announce(t("lookalikeDismissFailed"), "error");
      return;
    }
    location.replace(onwardTo.href);
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
