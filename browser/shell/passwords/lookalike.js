/* Flow D: this site looks like one where you keep a saved login. Going to the real site is the
   first choice; continuing is remembered for this pair of sites in this profile only, says so next
   to the button, and can be undone in Settings › Passwords. */

import { localize, t } from "../lib/i18n.js";
import { announce } from "../lib/ui.js";

const params = new URLSearchParams(location.search);
const HOST = /^[a-z0-9.-]+$/i;

function target() {
  try {
    const url = new URL(params.get("url"));
    return /^https?:$/.test(url.protocol) ? url : null;
  } catch {
    return null;
  }
}

localize();
const url = target();
const site = params.get("site") ?? "";
const similar = params.get("similar") ?? "";
if (url && HOST.test(similar) && site) {
  document.getElementById("explain").textContent = t("lookalikeBody", [site, similar]);
  document.getElementById("address").textContent = url.href;
  const real = document.getElementById("go-real");
  real.textContent = t("lookalikeGoReal", [similar]);
  real.addEventListener("click", () => location.replace(`https://${similar}/`));
  const onward = document.getElementById("continue");
  document.getElementById("continue-note").textContent = t("lookalikeContinueNote", [site, similar]);
  onward.addEventListener("click", async () => {
    onward.disabled = true;
    try {
      await browser.nulavioPasswords.dismiss(site, similar);
    } catch (e) {
      // Not remembered: do not open the site as if it were (the warning would silently differ next time).
      console.error("look-alike: could not remember the choice", e);
      onward.disabled = false;
      announce(t("lookalikeDismissFailed"), "error");
      return;
    }
    location.replace(url.href);
  });
  document.body.dataset.state = "ready";
  real.focus();
} else {
  document.body.dataset.state = "invalid";
}
document.documentElement.dataset.ready = "true";
