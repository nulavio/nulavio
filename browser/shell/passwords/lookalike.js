/* Flow D: this site looks like one where you keep a saved login. Going to the real site is the
   first choice; continuing is remembered for this pair of sites in this profile only. */

import { localize, t } from "../lib/i18n.js";

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
  onward.textContent = t("lookalikeContinue", [site]);
  onward.addEventListener("click", async () => {
    await browser.nulavioPasswords.dismiss(site, similar);
    location.replace(url.href);
  });
  document.body.dataset.state = "ready";
  real.focus();
} else {
  document.body.dataset.state = "invalid";
}
document.documentElement.dataset.ready = "true";
