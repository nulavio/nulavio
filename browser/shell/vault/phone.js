/* Connect a phone to a protected profile, or remove one (ADR 0005, S11). The phone runs Nulavio
   Companion; the computer shows a code, both screens show the same 6 digits, the user confirms on
   both. Pairing adds an unlock method, so the profile's current password or recovery code is asked
   first. States on <body data-state>: loading, idle, waiting, compare, paired, error, unavailable,
   not-yet (connecting a phone is not offered in this version, D10; a connected one can be removed). */

import { localize, t } from "../lib/i18n.js";
import { qrSvg } from "../lib/qr.js";
import { acceptField, announce, chip, errorText, h, refuseField } from "../lib/ui.js";

const vault = browser.nulavioVault;
const profileId = Number(new URLSearchParams(location.search).get("p"));
const byId = id => document.getElementById(id);
let session = null;
let timer = null;

function setState(state, message = "", level = "info") {
  document.body.dataset.state = state;
  announce(message, level);
}

/** A result, with the warning when the change was saved but not recorded inside the profile (#177). */
function settle(state, text, answer) {
  if (answer?.warning === "not-recorded") {
    setState(state, `${text} ${t("err_not_recorded")}`, "warn");
  } else {
    setState(state, text, "ok");
  }
}

/** The 6 digits as shown ("123 456") and, for screen readers, as six separate digits. */
function showDigits(sas) {
  const digits = String(sas).replace(/\D/g, "");
  byId("digits").replaceChildren(
    h("span", { "aria-hidden": "true", text: `${digits.slice(0, 3)} ${digits.slice(3)}` }),
    h("span", { class: "visually-hidden", text: t("phoneDigitsSpoken", [[...digits].join(" ")]) })
  );
}

const FAILURES = {
  "sas-mismatch": "phoneDigitsDifferent",
  expired: "phoneExpired",
  unreachable: "phoneUnreachable",
  "wrong-secret": "vaultWrongPassword",
  "needs-two-methods": "phoneNeedsTwoMethods",
};

function failure(code) {
  return FAILURES[code] ? t(FAILURES[code]) : errorText(new Error(code));
}

/* The secret was refused or is missing: the field is marked and the status line, which says why, is
   its description. Both go when the person types again (accessibility.md, as on the unlock page). */
function refuseCurrent() {
  refuseField(byId("current"), byId("status"), null, () => {
    if (["error", "idle"].includes(document.body.dataset.state)) {
      setState("idle"); // the message was about what was typed before
    }
  });
}

function stopPairing() {
  clearInterval(timer);
  timer = null;
  session = null;
  byId("pairing").hidden = true;
  byId("compare").hidden = true;
  byId("start-form").hidden = false;
}

async function poll() {
  if (!session) {
    return;
  }
  const status = await vault.phoneSession(session, "status");
  if (status.state === "compare" || status.state === "waiting-for-you") {
    if (byId("compare").hidden) {
      showDigits(status.sas);
      byId("compare").hidden = false;
      byId("qr").hidden = true;
      byId("pair-hint").hidden = true;
      // No status text: the focused digits and their question are read out, once.
      setState("compare");
      byId("digits").focus();
    }
  } else if (status.state === "paired") {
    stopPairing();
    await render(); // the list first, then the announcement
    settle("paired", t("phonePaired", [status.phone ?? ""]), status);
  } else if (status.state === "failed") {
    stopPairing();
    setState("error", failure(status.error), "error");
  } else if (status.state === "cancelled" || status.state === "gone") {
    stopPairing();
    setState("idle", t("phoneCancelled"));
  }
}

async function start(current) {
  acceptField(byId("current"));
  setState("waiting", t("phoneStarting"), "progress");
  try {
    const started = await vault.phoneStart(profileId, "pair", { current });
    session = started.session;
    byId("qr").replaceChildren(qrSvg(started.qr, t("phoneQrLabel"), started.code));
    byId("qr").hidden = false;
    byId("pair-hint").hidden = false;
    byId("pairing").hidden = false;
    byId("start-form").hidden = true;
    byId("current").value = "";
    setState("waiting", t("phoneScanStatus"), "progress");
    timer = setInterval(() => poll().catch(e => setState("error", errorText(e), "error")), 1000);
  } catch (e) {
    const code = String(e?.message ?? e);
    setState("error", failure(code), "error");
    if (code === "wrong-secret") {
      refuseCurrent();
    } else {
      byId("current").focus();
    }
  }
}

function phoneRow(method) {
  const remove = h("button", { class: "button button--quiet", type: "button", text: t("phoneRemove") });
  remove.addEventListener("click", async () => {
    const current = byId("current").value;
    acceptField(byId("current"));
    if (!current) {
      setState("idle", t("phoneRemoveNeedsSecret"), "error");
      refuseCurrent();
      return;
    }
    try {
      const result = await vault.change(profileId, "remove-method", { current, envelope: method.id });
      byId("current").value = "";
      await render();
      // After the list, on purpose: the result (and its warning) is the last word, and the page is idle again.
      settle("idle", t("phoneRemoved", [method.label]), result);
    } catch (e) {
      const code = String(e?.message ?? e);
      setState("error", failure(code), "error");
      if (code === "wrong-secret") {
        refuseCurrent();
      }
    }
  });
  return h("li", { class: "row" }, h("div", { class: "row__main" }, h("span", { class: "row__title", text: method.label })),
    h("div", { class: "row__end" }, remove));
}

async function render() {
  const capabilities = await vault.capabilities();
  const profile = await vault.status(profileId);
  byId("who").replaceChildren(chip(profile, "lg"), h("span", { class: "popup__name", text: profile.name }));
  if (!capabilities.phone) {
    setState("unavailable", t("phoneNoAvahi"), "error");
    return;
  }
  if (!profile.encrypted) {
    setState("unavailable", t("phoneNotProtected"), "error");
    return;
  }
  const phones = profile.methods.filter(m => m.method === "phone");
  byId("phones").replaceChildren(...(phones.length ? phones.map(phoneRow) : [h("li", { class: "hint", text: t("phoneNone") })]));
  if (!capabilities.phonePairing) {
    // Not offered yet: no way to start, and the page says so instead of how it would work. With a
    // phone connected, the field stays, because removing it is confirmed with a current secret.
    byId("explain").textContent = t("phoneNotYet");
    byId("start-form").hidden = !phones.length;
    byId("start-form").querySelector(".actions").hidden = true;
    byId("pair-hint-key").hidden = true;
    setState(phones.length ? "idle" : "not-yet");
    return;
  }
  byId("start-form").hidden = false;
  setState("idle");
}

byId("start-form").addEventListener("submit", event => {
  event.preventDefault();
  if (!byId("start-form").querySelector(".actions").hidden) {
    start(byId("current").value); // Enter in the field does nothing while connecting is not offered
  }
});
byId("match").addEventListener("click", () => {
  setState("waiting", t("phoneWaitingConfirm"), "progress");
  vault.phoneSession(session, "confirm", true).catch(e => setState("error", errorText(e), "error"));
});
byId("differ").addEventListener("click", () => vault.phoneSession(session, "confirm", false).catch(() => null));
byId("cancel").addEventListener("click", () => vault.phoneSession(session, "cancel").catch(() => null).finally(stopPairing));

localize();
render()
  .catch(e => setState("error", errorText(e), "error"))
  .finally(() => {
    document.documentElement.dataset.ready = "true";
  });
