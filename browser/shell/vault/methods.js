/* Unlock methods of a protected profile (UX4, audit SB-09, SB-16). Each method opens the profile
   on its own; the page lists them by kind and lets the person add a password or the computer
   login, replace the recovery code or remove a method. Every change is confirmed with a current
   password or recovery code, asked again each time, and the last method can never go. Below two
   methods the page says what losing one would mean (ADR 0006: no master key).
   A removal takes a method away from this key file only: the page says how old the profile's key is and
   whether a method went since, and offers a new key, which is what ends an old secret's power (ADR 0015). */

import { localize, t } from "../lib/i18n.js";
import { clearCode, guardLeaving, printCode, showCode } from "../lib/recovery.js";
import { acceptField, announce, chip, confirmDialog, errorText, h, profileStates, refuseField, stateBadge } from "../lib/ui.js";

const vault = browser.nulavioVault;
const profileId = Number(new URLSearchParams(location.search).get("p"));
const byId = id => document.getElementById(id);
const KINDS = { password: "methodPassword", "recovery-code": "methodRecovery", "os-keyring": "methodKeyring", phone: "methodPhone" };
let profile = null;
let capabilities = { keyring: false };

const kindName = method => t(KINDS[method.method] ?? "methodOther");

/** A change's result; one saved but not recorded inside the profile says so, as a warning (#177). */
function announceDone(text, result) {
  if (result?.warning === "not-recorded") {
    announce(`${text} ${t("err_not_recorded")}`, "warn");
  } else {
    announce(text, "ok");
  }
}

function setState(state) {
  document.body.dataset.state = state;
  for (const control of document.querySelectorAll("#add-actions button, #methods button, #key button")) {
    control.disabled = state === "busy" || control.dataset.keep === "disabled" || control.hasAttribute("data-no-confirmer");
  }
}

/** Run one change, confirmed with the secret typed now; the field is cleared after every attempt. */
async function change(op, extra = {}) {
  const field = byId("current");
  const error = byId("current-error");
  if (!field.value) {
    error.textContent = t("err_bad_secret");
    field.setAttribute("aria-invalid", "true");
    field.focus();
    return null;
  }
  error.textContent = "";
  field.removeAttribute("aria-invalid");
  setState("busy");
  announce(t("methodsWorking"), "progress");
  try {
    const result = await vault.change(profileId, op, { current: field.value, ...extra });
    announce("");
    return result;
  } catch (e) {
    announce("");
    if (String(e?.message) === "wrong-secret") {
      error.textContent = t("err_wrong_secret"); // a password or a recovery code: the field takes both
      field.setAttribute("aria-invalid", "true");
      field.focus();
    } else {
      announce(errorText(e), "error");
    }
    return null;
  } finally {
    field.value = "";
    setState(byId("code-step").hidden ? "idle" : "code");
  }
}

// Changes here are confirmed with a password or the recovery code (the tools accept nothing else),
// so the last of those two can never go: without it no change could be confirmed again (review F1).
const CONFIRMS = new Set(["password", "recovery-code"]);

function methodRow(method, count, confirmers) {
  const name = kindName(method);
  const last = count <= 1;
  const lastConfirmer = !last && CONFIRMS.has(method.method) && confirmers <= 1;
  const kept = last || lastConfirmer;
  const remove = h("button", {
    class: "button button--quiet",
    type: "button",
    text: t("methodRemove"),
    "aria-label": t("methodRemoveNamed", [name]),
    "aria-describedby": kept ? `keep-${method.id}` : null,
    dataset: { keep: kept ? "disabled" : "" },
  });
  remove.disabled = kept;
  remove.addEventListener("click", async () => {
    const ok = await confirmDialog({
      title: t("methodRemoveTitle", [name, profile.name]),
      body: t(count <= 2 ? "methodRemoveLeavesOne" : "methodRemoveBody", [name]),
      confirm: t("methodRemove"),
      danger: true,
    });
    const result = ok ? await change("remove-method", { envelope: method.id }) : null;
    if (result) {
      await render().catch(console.error); // the change was made: what it did is said even if the list is not redrawn
      announceDone(`${t("methodRemoved", [name])} ${t("methodRemovedKeeps")}`, result);
      byId("methods").querySelector("button:not(:disabled)")?.focus() ?? byId("headline").focus();
    }
  });
  return h(
    "li",
    { class: "row row--plain", dataset: { method: method.method, envelope: method.id } },
    h(
      "div",
      { class: "row__main" },
      h("p", { class: "row__title", text: name }),
      // Only a name the person or the device gave (a phone's); the tools' own labels are not shown.
      method.method === "phone" && method.label ? h("p", { class: "row__note", text: method.label }) : null,
      kept
        ? h("p", { class: "row__note", id: `keep-${method.id}`, text: t(last ? "err_last_method" : "methodsLastConfirmer") })
        : null
    ),
    h("div", { class: "row__end" }, remove)
  );
}

/* Nothing can be changed here (not a protected profile, a profile that no longer exists, a failed
   read): the page says why and shows no method, no action and no field for a secret
   (audit 2026-11 S-01). */
function unavailable(text) {
  byId("explain").textContent = text;
  byId("explain").hidden = !text;
  for (const id of ["few", "methods", "add-actions", "not-yet", "current-error", "password-form", "code-step", "key"]) {
    byId(id).hidden = true;
  }
  byId("current").closest(".field").hidden = true;
  document.querySelector("details.why").hidden = true;
  document.body.dataset.secret = "none"; // no field left: pages.css takes the "look at the band first" line away
  setState("unavailable");
}

async function render() {
  profile = await vault.status(profileId);
  if (!profile.encrypted) {
    unavailable(t("methodsNotProtected", [profile.name]));
    return;
  }
  byId("who").replaceChildren(chip(profile, "lg"), h("span", { class: "popup__name", text: profile.name }), ...profileStates(profile).map(stateBadge));
  // A new recovery code not typed back yet is not a method to list or count (#187): the old one still is.
  const methods = profile.methods.filter(m => !m.unconfirmed);
  const confirmers = methods.filter(m => CONFIRMS.has(m.method)).length;
  byId("methods").replaceChildren(...methods.map(method => methodRow(method, methods.length, confirmers)));
  // Below two methods, say what that means; with nothing left that can confirm a change (a profile
  // made that way before this page existed), say that instead of offering what cannot work.
  byId("few").hidden = methods.length >= 2 && confirmers > 0;
  byId("few").querySelector("p").textContent = t(confirmers ? "methodsFew" : "methodsNoConfirmer");
  for (const control of document.querySelectorAll("#add-actions button, #key button, #current")) {
    control.toggleAttribute("data-no-confirmer", !confirmers);
  }
  renderKey();
  byId("current").disabled = !confirmers;
  byId("add-keyring").hidden = !capabilities.keyring || methods.some(m => m.method === "os-keyring");
  // Connecting a phone is not offered yet (D10); the link stays while one is connected, to remove it.
  byId("phones").href = `phone.html?p=${profileId}`;
  byId("phones").hidden = !capabilities.phonePairing && !methods.some(m => m.method === "phone");
  byId("not-yet").textContent = t(capabilities.phonePairing ? "methodsNotYetKey" : "methodsNotYet");
  setState(byId("code-step").hidden ? "idle" : "code");
}

// -- the profile's key, and a new one (ADR 0015) ---------------------------------------------------

const day = iso => new Date(iso).toLocaleDateString(undefined, { dateStyle: "long" });

function size(bytes) {
  const [value, unit] = bytes >= 1024 ** 3 ? [bytes / 1024 ** 3, "gigabyte"] : [Math.max(1, bytes / 1024 ** 2), "megabyte"];
  return new Intl.NumberFormat(undefined, { style: "unit", unit, maximumFractionDigits: value < 10 ? 1 : 0 }).format(value);
}

/** What the key file says of its key: when it was made, and whether a method went since. */
function renderKey() {
  const key = profile.key ?? {};
  const text = !key.tracked || !key.created ? t("methodsKeyUnknown") : key.lastRemoval ? t("methodsKeyStale", [day(key.lastRemoval)]) : t("methodsKeyFresh", [day(key.created)]);
  byId("key-state").textContent = text;
  // The profile shown in this very window is open: its files cannot be copied from under it.
  byId("rekey").dataset.keep = profile.isCurrent ? "disabled" : "";
  byId("rekey-note").hidden = !profile.isCurrent;
}

byId("rekey").addEventListener("click", async () => {
  const field = byId("current");
  const error = byId("current-error");
  let check;
  try {
    check = await vault.rekeyCheck(profileId);
  } catch (e) {
    announce(errorText(e), "error");
    return;
  }
  if (!check.closed || !check.enough) {
    announce(t(check.closed ? "err_no_space" : "err_unlocked"), "error"); // before anything is asked
    return;
  }
  const ok = await confirmDialog({
    title: t("methodsRekeyTitle", [profile.name]),
    body: t("methodsRekeyBody", [size(check.size)]),
    confirm: t("methodsRekeyConfirm"),
    danger: true,
  });
  if (!ok) {
    return;
  }
  const secret = field.value;
  if (!secret) {
    error.textContent = t("err_bad_secret");
    field.setAttribute("aria-invalid", "true");
    field.focus();
    return;
  }
  error.textContent = "";
  field.removeAttribute("aria-invalid");
  field.value = "";
  setState("busy");
  making = true; // leaving now would stop the copy: the page asks first
  announce(t("methodsRekeyWorking"), "progress");
  let result;
  try {
    result = await vault.rekey(profileId, { current: secret });
  } catch (e) {
    making = false;
    setState("idle");
    if (String(e?.message) === "wrong-secret") {
      announce("");
      error.textContent = t("err_wrong_secret");
      field.setAttribute("aria-invalid", "true");
      field.focus();
    } else {
      announce(errorText(e), "error"); // nothing was changed: the copy is undone
    }
    return;
  }
  await render().catch(console.error);
  const gone = result.dropped.map(kindName);
  const done = [t("methodsRekeyDone", [profile.name]), gone.length ? t("methodsRekeyDropped", [gone.join(", ")]) : ""];
  if (result.carried.some(m => m.method === "recovery-code")) {
    making = false;
    announce(done.filter(Boolean).join(" "), "ok");
    byId("rekey").focus();
    return;
  }
  // The recovery code went with the old key: a new one right away, with the secret that was just typed
  // (it was carried over), shown and typed back like any new code.
  try {
    const made = await vault.change(profileId, "new-recovery-code", { current: secret });
    await render().catch(console.error);
    announce([...done, t("methodsRekeyNewCode")].filter(Boolean).join(" "), "ok"); // said before the code takes the focus
    showNewCode(made.recoveryCode, true);
  } catch (e) {
    making = false;
    setState("idle");
    announce([...done, errorText(e)].filter(Boolean).join(" "), "error"); // the new key stands; the code is still to make
  }
});

// -- a new recovery code: shown once, two groups typed back ------------------------------------

/* `first`: the profile had no recovery code that this one replaces (it never had one, or a new key dropped
   it): nothing else opens the profile "until it is typed back", so the page does not say so. */
function showNewCode(code, first = false) {
  byId("code-intro").textContent = t(first ? "methodsCodeIntroFirst" : "methodsCodeIntro");
  const groups = code.split("-");
  const a = Math.floor(Math.random() * 3);
  const b = 3 + Math.floor(Math.random() * 4);
  showCode(byId("code"), code);
  byId("group-a-label").textContent = t("vaultTypeGroup", [String(a + 1)]);
  byId("group-b-label").textContent = t("vaultTypeGroup", [String(b + 1)]);
  byId("group-a").dataset.expected = groups[a];
  byId("group-b").dataset.expected = groups[b];
  byId("code-step").hidden = false;
  setState("code");
  byId("code-heading").focus();
}

byId("code-step").addEventListener("submit", async event => {
  event.preventDefault();
  const normalise = v => v.trim().toUpperCase().replaceAll("O", "0").replace(/[IL]/g, "1");
  const wrong = ["group-a", "group-b"].find(id => normalise(byId(id).value) !== byId(id).dataset.expected);
  if (wrong) {
    refuseField(byId(wrong), byId("code-error"), t("vaultGroupsDiffer")); // the group that differs
    return;
  }
  // Only now does the old code go: until the new one is confirmed, both open the profile (#187).
  const submit = event.submitter ?? byId("code-step").querySelector("button[type=submit]");
  submit.disabled = true;
  announce(t("methodsWorking"), "progress");
  let result;
  try {
    result = await vault.change(profileId, "confirm-recovery-code", { current: byId("code").dataset.code });
  } catch (e) {
    announce(errorText(e), "error"); // the code stays on screen; the old one still opens the profile
    return;
  } finally {
    submit.disabled = false;
  }
  clearCode(byId("code"));
  for (const id of ["group-a", "group-b"]) {
    byId(id).value = "";
    delete byId(id).dataset.expected;
  }
  byId("code-error").textContent = "";
  byId("code-step").hidden = true;
  making = false;
  // The list first (render() sets the state once it is drawn), then the announcement.
  await render().catch(e => {
    setState("idle");
    announce(errorText(e), "error");
  });
  announceDone(t("methodsCodeReplaced"), result);
  byId("new-code").focus();
});
byId("print-code").addEventListener("click", printCode);
let making = false;
guardLeaving(() => making || document.body.dataset.state === "code");

byId("new-code").addEventListener("click", async () => {
  const ok = await confirmDialog({ title: t("methodsNewCodeTitle", [profile.name]), body: t("methodsNewCodeBody"), confirm: t("methodsNewCode") });
  if (!ok) {
    return;
  }
  // From the moment it is asked for, the old code may already be gone: leaving asks first until the
  // new one has been typed back, and the code is shown before anything else can fail (review F12).
  making = true;
  const first = !profile.methods.some(m => m.method === "recovery-code" && !m.unconfirmed);
  const result = await change("new-recovery-code");
  if (result?.recoveryCode) {
    showNewCode(result.recoveryCode, first); // shown whether or not the change was recorded: it is the only copy
    render().then(
      () => result.warning && announce(t("err_not_recorded"), "warn"),
      // The list could not be read again: said, and the warning with it, never instead of it.
      e => announce([errorText(e), result.warning ? t("err_not_recorded") : ""].filter(Boolean).join(" "), "error")
    );
  } else {
    making = false;
  }
});

// -- a password, or the computer login ---------------------------------------------------------

byId("add-password").addEventListener("click", () => {
  byId("password-form").hidden = false;
  byId("new-password").focus();
});
byId("password-cancel").addEventListener("click", () => {
  byId("password-form").reset();
  byId("password-form").hidden = true;
  byId("add-password").focus();
});
byId("password-form").addEventListener("submit", async event => {
  event.preventDefault();
  const error = byId("password-error");
  const password = byId("new-password").value;
  error.textContent = "";
  for (const id of ["new-password", "new-password2"]) {
    acceptField(byId(id));
  }
  if (password.length < 8) {
    refuseField(byId("new-password"), error, t("err_password_too_short"));
    return;
  }
  if (password !== byId("new-password2").value) {
    refuseField(byId("new-password2"), error, t("vaultPasswordsDiffer"));
    return;
  }
  const result = await change("add-password", { password });
  byId("password-form").reset();
  if (result) {
    byId("password-form").hidden = true;
    await render().catch(console.error);
    announceDone(t("methodsPasswordAdded"), result);
    byId("add-password").focus();
  }
});
byId("add-keyring").addEventListener("click", async () => {
  const result = await change("add-keyring");
  if (result) {
    await render().catch(console.error);
    announceDone(t("methodsKeyringAdded"), result);
  }
});

localize();
vault
  .capabilities()
  .then(found => {
    capabilities = found;
  })
  .then(render)
  .catch(e => {
    const gone = String(e?.message) === "not-found";
    byId("headline").textContent = t(gone ? "vaultGoneHeadline" : "vaultUnreadHeadline");
    unavailable("");
    announce(gone ? t("vaultGone") : errorText(e), "error");
  })
  .finally(() => {
    document.documentElement.dataset.ready = "true";
  });
