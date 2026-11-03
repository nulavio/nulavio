/* New protected profile, in three decisions (S6): the profile, how it
   unlocks, and the recovery code. The profile is encrypted from the start;
   the recovery code is shown once and two of its groups are typed back to
   show it was kept. Steps are on <body data-step>: profile, protection,
   recovery, done. */

import { localize, t } from "../lib/i18n.js";
import { TEMPLATE_NAMES } from "../lib/names.js";
import { clearCode, guardLeaving, printCode, showCode } from "../lib/recovery.js";
import { announce, chip, errorText, h } from "../lib/ui.js";

const vault = browser.nulavioVault;
const profiles = browser.nulavioProfiles;
const byId = id => document.getElementById(id);

const state = { templateId: "banking", name: "", id: null, code: "", groups: [] };
let capabilities = { keyring: false };

function step(name) {
  document.body.dataset.step = name;
  for (const id of ["step-profile", "step-protection", "step-recovery", "step-done"]) {
    byId(id).hidden = id !== `step-${name}`;
  }
  const index = ["profile", "protection", "recovery"].indexOf(name);
  byId("progress").textContent = index >= 0 ? t("vaultStep", [String(index + 1), "3"]) : "";
  byId("headline").textContent = t(
    { profile: "vaultStepProfile", protection: "vaultStepProtection", recovery: "vaultStepRecovery", done: "vaultStepDone" }[name]
  );
  announce("");
  if (name === "recovery") {
    // The code comes first (SB-08): the heading takes the keyboard, then the numbered groups.
    byId("headline").tabIndex = -1;
    byId("headline").focus();
    return;
  }
  document.querySelector(`#step-${name} input, #step-${name} button`)?.focus();
}

// The profile exists once the code is shown: leaving before typing it back would lose the code.
guardLeaving(() => document.body.dataset.step === "recovery");

function chooseTemplate(id) {
  state.templateId = id;
  for (const button of byId("templates").querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.template === id));
  }
  const name = byId("name");
  if (!name.dataset.touched && id) {
    name.value = t(TEMPLATE_NAMES[id]);
  }
}

async function renderTemplates() {
  const options = await profiles.options();
  byId("templates").replaceChildren(
    ...options.templates.map(template => {
      const name = t(TEMPLATE_NAMES[template.id]);
      return h(
        "button",
        { class: "button button--secondary button--with-chip", type: "button", dataset: { template: template.id },
          onclick: () => chooseTemplate(template.id) },
        chip({ name, avatar: template.avatar, color: template.color }, "sm"),
        h("span", { text: name })
      );
    })
  );
  // From the profile menu's create sheet (UX4): the name, template, icon and colour chosen there.
  // The Vault module checks the icon and colour like any other; unknown values are dropped here.
  const asked = new URLSearchParams(location.search);
  const name = byId("name");
  if (asked.get("name") && !name.dataset.touched) {
    name.value = asked.get("name").slice(0, 60);
    name.dataset.touched = "1";
  }
  if (options.avatars.includes(asked.get("avatar"))) {
    state.avatar = asked.get("avatar");
  }
  if (options.colors.includes(asked.get("color"))) {
    state.color = asked.get("color");
  }
  const template = asked.get("template");
  chooseTemplate(options.templates.some(t => t.id === template) ? template : asked.has("name") ? null : state.templateId);
}

function method() {
  return document.querySelector("input[name=method]:checked").value;
}

function syncProtection() {
  const usePassword = method() === "password";
  byId("password-fields").hidden = !usePassword;
  byId("also-keyring-field").hidden = !usePassword || !capabilities.keyring;
}

async function create(event) {
  event.preventDefault();
  const error = byId("protection-error");
  error.textContent = "";
  const details = {
    name: state.name,
    ...(state.templateId ? { templateId: state.templateId } : {}),
    ...(state.avatar ? { avatar: state.avatar } : {}),
    ...(state.color ? { color: state.color } : {}),
  };
  if (method() === "password") {
    const password = byId("password").value;
    if (password.length < 8) {
      error.textContent = t("err_password_too_short");
      byId("password").focus();
      return;
    }
    if (password !== byId("password2").value) {
      error.textContent = t("vaultPasswordsDiffer");
      byId("password2").focus();
      return;
    }
    details.password = password;
    details.keyring = byId("also-keyring").checked;
  } else {
    details.keyring = true;
  }
  for (const control of document.querySelectorAll("#step-protection input, #step-protection button")) {
    control.disabled = true;
  }
  announce(t("vaultCreating"), "progress");
  try {
    const result = await vault.createProtected(details);
    state.id = result.id;
    state.code = result.recoveryCode;
    byId("password").value = "";
    byId("password2").value = "";
    showRecovery();
  } catch (e) {
    announce("");
    error.textContent = errorText(e);
  } finally {
    for (const control of document.querySelectorAll("#step-protection input, #step-protection button")) {
      control.disabled = false;
    }
  }
}

function showRecovery() {
  const groups = state.code.split("-");
  const a = 1 + Math.floor(Math.random() * 3);
  const b = 4 + Math.floor(Math.random() * 3);
  state.groups = [a, b];
  showCode(byId("code"), state.code);
  byId("group-a-label").textContent = t("vaultTypeGroup", [String(a + 1)]);
  byId("group-b-label").textContent = t("vaultTypeGroup", [String(b + 1)]);
  byId("group-a").dataset.expected = groups[a];
  byId("group-b").dataset.expected = groups[b];
  step("recovery");
}

function finish(event) {
  event.preventDefault();
  const normalise = v => v.trim().toUpperCase().replaceAll("O", "0").replace(/[IL]/g, "1");
  const ok = ["group-a", "group-b"].every(id => normalise(byId(id).value) === byId(id).dataset.expected);
  if (!ok) {
    byId("recovery-error").textContent = t("vaultGroupsDiffer");
    byId("group-a").focus();
    return;
  }
  state.code = "";
  clearCode(byId("code"));
  byId("done-text").textContent = t("vaultCreated", [state.name]);
  byId("done-actions").replaceChildren(
    h("button", { class: "button button--primary", type: "button", text: t("vaultOpenProfile", [state.name]),
      onclick: () => profiles.switchTo(state.id).catch(e => announce(errorText(e), "error")) }),
    h("a", { class: "button button--secondary", href: "../settings/settings.html#profiles", text: t("vaultToSettings") })
  );
  step("done");
}

byId("name").addEventListener("input", () => {
  byId("name").dataset.touched = "1";
});
byId("print-code").addEventListener("click", printCode);
byId("step-profile").addEventListener("submit", event => {
  event.preventDefault();
  state.name = byId("name").value.trim();
  if (state.name) {
    step("protection");
  }
});
byId("step-protection").addEventListener("change", syncProtection);
byId("step-protection").addEventListener("submit", create);
byId("protection-back").addEventListener("click", () => step("profile"));
byId("step-recovery").addEventListener("submit", finish);

localize();
Promise.all([renderTemplates(), vault.capabilities().then(c => (capabilities = c))])
  .then(() => {
    if (!capabilities.storage || !capabilities.sodium) {
      byId("step-profile").hidden = true;
      announce(t("vaultStorageMissing"), "error");
      document.body.dataset.step = "unavailable";
      return;
    }
    byId("keyring-choice").hidden = !capabilities.keyring;
    syncProtection();
    step("profile");
  })
  .catch(e => announce(errorText(e), "error"))
  .finally(() => {
    document.documentElement.dataset.ready = "true";
  });
