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

let gone = false;

function setState(state, message = "", level = "info") {
  document.body.dataset.state = gone ? "unavailable" : state; // a profile that is gone does not come back
  announce(message, level);
}

const isGone = e => String(e?.message ?? e) === "not-found";

/** The page of a profile that no longer exists: what it loads with, and what any action finds (#547). */
function showGone() {
  gone = true;
  clearInterval(timer);
  timer = null;
  session = null;
  byId("headline").textContent = t("vaultGoneHeadline");
  for (const id of ["explain", "phones", "start-form", "pairing"]) {
    byId(id).hidden = true;
  }
  document.querySelector("details.why").hidden = true;
  setState("unavailable", t("vaultGone"), "error");
}

/** Why the list could not be read again. For a read, `not-found` is the profile: it no longer exists. */
function readText(e) {
  if (isGone(e)) {
    showGone();
    return t("vaultGone");
  }
  return errorText(e);
}

/** A result, with the warning when the change was saved but not recorded inside the profile (#177). The
    list is read again first; when that read fails, the result and its warning are still said, with the
    failure after them (#258): the change went through all the same. */
async function settle(state, text, answer) {
  let readFailed = null;
  await render().catch(e => {
    readFailed = e;
  });
  const unrecorded = answer?.warning === "not-recorded" ? t("err_not_recorded") : "";
  if (readFailed) {
    setState(state, [text, unrecorded, readText(readFailed)].filter(Boolean).join(" "), "error");
  } else if (unrecorded) {
    setState(state, `${text} ${unrecorded}`, "warn");
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

/** The words for a failure, by its code. `not-found` is the profile or one of its phones, and the code does not say
    which: the list is read again, and what it finds says (#547). */
async function failure(code) {
  if (FAILURES[code]) {
    return t(FAILURES[code]);
  }
  if (code !== "not-found") {
    return errorText(new Error(code));
  }
  try {
    await render();
  } catch (again) {
    return readText(again);
  }
  return t("phoneMethodGone");
}

async function fail(e) {
  setState("error", await failure(String(e?.message ?? e)), "error");
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
  byId("start-form").hidden = gone; // a profile that is gone has nothing to start
}

let polling = false;

async function poll() {
  if (!session || polling) {
    return; // one look at a time: two ticks that both saw "paired" would settle it twice
  }
  polling = true;
  try {
    await look();
  } finally {
    polling = false;
  }
}

async function look() {
  const asked = session;
  const status = await vault.phoneSession(asked, "status");
  if (session !== asked) {
    return; // stopped or cancelled while the answer was on its way
  }
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
    await settle("paired", t("phonePaired", [status.phone ?? ""]), status); // the list first, then the announcement
  } else if (status.state === "failed") {
    stopPairing();
    setState("error", await failure(status.error), "error");
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
    timer = setInterval(() => poll().catch(fail), 1000);
  } catch (e) {
    const code = String(e?.message ?? e);
    await fail(e);
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
      // After the list, on purpose: the result (and its warning) is the last word, and the page is idle again.
      await settle("idle", t("phoneRemoved", [method.label]), result);
    } catch (e) {
      const code = String(e?.message ?? e);
      await fail(e);
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
  vault.phoneSession(session, "confirm", true).catch(fail);
});
byId("differ").addEventListener("click", () => vault.phoneSession(session, "confirm", false).catch(() => null));
byId("cancel").addEventListener("click", () => vault.phoneSession(session, "cancel").catch(() => null).finally(stopPairing));

localize();
render()
  .catch(e => setState("error", readText(e), "error"))
  .finally(() => {
    document.documentElement.dataset.ready = "true";
  });
