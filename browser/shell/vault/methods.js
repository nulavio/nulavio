/* Unlock methods of a protected profile (UX4, audit SB-09, SB-16). Each method opens the profile
   on its own; the page lists them by kind and lets the person add a password or the computer
   login, replace the recovery code or remove a method. Every change is confirmed with a current
   password or recovery code, asked again each time, and the last method can never go. Below two
   methods the page says what losing one would mean (ADR 0006: no master key). */

import { localize, t } from "../lib/i18n.js";
import { clearCode, guardLeaving, printCode, showCode } from "../lib/recovery.js";
import { announce, chip, confirmDialog, errorText, h, profileStates, stateBadge } from "../lib/ui.js";

const vault = browser.nulavioVault;
const profileId = Number(new URLSearchParams(location.search).get("p"));
const byId = id => document.getElementById(id);
const KINDS = { password: "methodPassword", "recovery-code": "methodRecovery", "os-keyring": "methodKeyring", phone: "methodPhone" };
let profile = null;
let capabilities = { keyring: false };

const kindName = method => t(KINDS[method.method] ?? "methodOther");

function setState(state) {
  document.body.dataset.state = state;
  for (const control of document.querySelectorAll("#add-actions button, #methods button")) {
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
    if (ok && (await change("remove-method", { envelope: method.id }))) {
      await render();
      announce(t("methodRemoved", [name]), "ok");
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

async function render() {
  profile = await vault.status(profileId);
  if (!profile.encrypted) {
    byId("explain").textContent = t("methodsNotProtected", [profile.name]);
    for (const id of ["few", "methods", "add-actions"]) {
      byId(id).hidden = true;
    }
    setState("unavailable");
    return;
  }
  byId("who").replaceChildren(chip(profile, "lg"), h("span", { class: "popup__name", text: profile.name }), ...profileStates(profile).map(stateBadge));
  const methods = profile.methods;
  const confirmers = methods.filter(m => CONFIRMS.has(m.method)).length;
  byId("methods").replaceChildren(...methods.map(method => methodRow(method, methods.length, confirmers)));
  // Below two methods, say what that means; with nothing left that can confirm a change (a profile
  // made that way before this page existed), say that instead of offering what cannot work.
  byId("few").hidden = methods.length >= 2 && confirmers > 0;
  byId("few").querySelector("p").textContent = t(confirmers ? "methodsFew" : "methodsNoConfirmer");
  for (const control of document.querySelectorAll("#add-actions button, #current")) {
    control.toggleAttribute("data-no-confirmer", !confirmers);
  }
  byId("current").disabled = !confirmers;
  byId("add-keyring").hidden = !capabilities.keyring || methods.some(m => m.method === "os-keyring");
  // Connecting a phone is not offered yet (D10); the link stays while one is connected, to remove it.
  byId("phones").href = `phone.html?p=${profileId}`;
  byId("phones").hidden = !capabilities.phonePairing && !methods.some(m => m.method === "phone");
  byId("not-yet").textContent = t(capabilities.phonePairing ? "methodsNotYetKey" : "methodsNotYet");
  setState(byId("code-step").hidden ? "idle" : "code");
}

// -- a new recovery code: shown once, two groups typed back ------------------------------------

function showNewCode(code) {
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

byId("code-step").addEventListener("submit", event => {
  event.preventDefault();
  const normalise = v => v.trim().toUpperCase().replaceAll("O", "0").replace(/[IL]/g, "1");
  if (!["group-a", "group-b"].every(id => normalise(byId(id).value) === byId(id).dataset.expected)) {
    byId("code-error").textContent = t("vaultGroupsDiffer");
    byId("group-a").focus();
    return;
  }
  clearCode(byId("code"));
  for (const id of ["group-a", "group-b"]) {
    byId(id).value = "";
    delete byId(id).dataset.expected;
  }
  byId("code-error").textContent = "";
  byId("code-step").hidden = true;
  making = false;
  setState("idle");
  announce(t("methodsCodeReplaced"), "ok");
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
  const result = await change("new-recovery-code");
  if (result?.recoveryCode) {
    showNewCode(result.recoveryCode);
    render().catch(e => announce(errorText(e), "error"));
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
  if (password.length < 8) {
    error.textContent = t("err_password_too_short");
    byId("new-password").focus();
    return;
  }
  if (password !== byId("new-password2").value) {
    error.textContent = t("vaultPasswordsDiffer");
    byId("new-password2").focus();
    return;
  }
  const done = await change("add-password", { password });
  byId("password-form").reset();
  if (done) {
    byId("password-form").hidden = true;
    await render();
    announce(t("methodsPasswordAdded"), "ok");
    byId("add-password").focus();
  }
});
byId("add-keyring").addEventListener("click", async () => {
  if (await change("add-keyring")) {
    await render();
    announce(t("methodsKeyringAdded"), "ok");
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
    setState("unavailable");
    announce(errorText(e), "error");
  })
  .finally(() => {
    document.documentElement.dataset.ready = "true";
  });
