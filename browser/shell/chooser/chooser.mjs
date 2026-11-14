/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* The engine's profile chooser (about:profilemanager, #43): the window a plain start shows when the
   chooser is on, and the one "Gerenciar perfis" opens from a running profile. It runs before any
   profile has started, so nothing of the Shell is running there: the engine's patch 0011 imports
   this module into the chooser's own document (system principal) and asks it before every launch.

   - lockStates(profiles): which profiles are protected and locked, for the cards (a lock and the word).
   - beforeLaunch(document, profile): true when the profile may be launched now; for a locked protected
     profile, after it was unlocked here with one of its methods (password, this computer's login,
     recovery code). false when the person went back, and the chooser stays as it was.

   Whether a profile is protected, and locked, is read from its files and the mount table (lockState
   below), not asked of the Vault's tools: they are optional (gocryptfs, FUSE, libsodium), and a profile
   without a password opens the same with or without them.

   It talks to the same Vault helper as the unlock page (NulavioVault.helper: `status`, `unlock`), and
   its words are the unlock page's, in Fluent (l10n/<locale>/nulavio/chooser.ftl). The phone is not
   offered here: its session needs the Shell. A secret goes from the field to the helper's stdin and
   the field is emptied; nothing else keeps it. */

const { helper } = ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioVault.sys.mjs");
const { profileLockState, PLAIN, LOCKED, UNLOCKED } = ChromeUtils.importESModule(
  "resource://builtin-addons/nulavio-shell/modules/NulavioVaultState.sys.mjs"
);

const BASE = "resource://builtin-addons/nulavio-shell/";
const METHODS = ["password", "os-keyring", "recovery-code"];
const SETTLED = { finished: "recovery-finished", undone: "recovery-undone", unsettled: "recovery-unsettled", unknown: "recovery-unknown" };
const UNAVAILABLE = new Set(["tools-missing", "storage-unavailable", "helper-failed"]);

// -- words ----------------------------------------------------------------------------------------

/* The words are Fluent messages inside the Shell (l10n/<locale>/nulavio/chooser.ftl), the same as the
   unlock page's. Before any profile has started the Shell has not registered its files: the chooser
   does it here, under its own name, when they are not there yet. */
const L10N = `${BASE}l10n/{locale}/`;
const IDS = [
  "locked", "headline", "password", "recovery", "unlock", "unlock-recovery", "use-keyring", "use-recovery", "cancel", "back",
  "unlocking", "no-master-key", "wrong-password", "wrong-recovery", "recovery-malformed", "recovery-required",
  "keyring-unavailable", "unavailable-headline", "storage-missing", "gone-headline", "gone", "unread-headline", "unexpected",
  "recovery-finished", "recovery-undone", "recovery-unsettled", "recovery-unknown", "not-recorded", "locked-again",
];
let l10n = null;
const words = new Map();

async function loadWords() {
  if (l10n) {
    return;
  }
  const registry = L10nRegistry.getInstance();
  if (!registry.hasSource("nulavio-shell") && !registry.hasSource("nulavio-chooser")) {
    registry.registerSources([new L10nFileSource("nulavio-chooser", "app", ["en-US", "pt-BR"], L10N)]);
  }
  l10n = new Localization(["nulavio/chooser.ftl"]);
  const values = await l10n.formatValues(IDS.map(id => ({ id: `nulavio-chooser-${id}` })));
  IDS.forEach((id, i) => words.set(id, values[i] ?? id));
}

const t = id => words.get(id) ?? id;
/** A message with the profile's name in it. */
const named = (id, profile) => l10n.formatValue(`nulavio-chooser-${id}`, { profile: profile.name });

// -- is it protected, and locked? --------------------------------------------------------------------

/** The path as the mount table has it: symbolic links followed. */
function real(path) {
  const file = Cc["@mozilla.org/file/local;1"].createInstance(Ci.nsIFile);
  file.initWithPath(path);
  try {
    file.normalize();
  } catch {
    // as given
  }
  return file.path;
}

/** Whether a volume is mounted at `path` (/proc/self/mountinfo, whose paths escape spaces and the like). */
async function mounted(path) {
  const unescape = field => field.replace(/\\([0-7]{3})/g, (_m, octal) => String.fromCharCode(parseInt(octal, 8)));
  const wanted = real(path);
  return (await IOUtils.readUTF8("/proc/self/mountinfo")).split("\n").some(line => unescape(line.split(" ")[4] ?? "") === wanted);
}

/**
 * PLAIN, LOCKED or UNLOCKED, from the profile's files (NulavioVaultState) and then checked: "unlocked" only
 * when a volume is really mounted there (a record lying in the bare folder is not one), and "plain" only
 * when nothing of a container is beside it (a container without its key file is a protected profile that
 * cannot be read, and this throws). Whatever cannot be established throws: the caller does not start it.
 */
async function lockState(path) {
  const state = await profileLockState(path);
  if (state === PLAIN) {
    if (await IOUtils.exists(PathUtils.join(PathUtils.parent(path), `${PathUtils.filename(path)}.vault`))) {
      throw new Error("a container without its key file");
    }
    return PLAIN;
  }
  return state === UNLOCKED && !(await mounted(path)) ? LOCKED : state;
}

// -- the helper -------------------------------------------------------------------------------------

async function status(profile) {
  return helper({ op: "status", path: profile.path });
}

/** id -> { protected, locked, label }, from each profile's files; one that could not be read is left out. */
export async function lockStates(profiles) {
  await loadWords().catch(e => console.error("Nulavio chooser: words", e)); // the cards are drawn either way
  const states = new Map();
  await Promise.all(
    profiles.map(async profile => {
      try {
        const state = await lockState(profile.path);
        states.set(profile.id, { protected: state !== PLAIN, locked: state === LOCKED, label: state === LOCKED ? t("locked") : null });
      } catch (e) {
        console.error("Nulavio chooser: lock state", e);
      }
    })
  );
  return states;
}

// -- the unlock step ------------------------------------------------------------------------------

function el(document, tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(props)) {
    if (name === "text") {
      node.textContent = value;
    } else if (name.startsWith("on")) {
      node.addEventListener(name.slice(2), value);
    } else if (value === true) {
      node.setAttribute(name, "");
    } else if (value !== false && value !== null && value !== undefined) {
      node.setAttribute(name, value);
    }
  }
  node.append(...children);
  return node;
}

function stylesheet(document) {
  if (!document.getElementById("nulavio-chooser-style")) {
    document.head.append(el(document, "link", { id: "nulavio-chooser-style", rel: "stylesheet", href: `${BASE}chooser/chooser.css` }));
  }
}

/** The dialog for one locked profile; resolves true once it is unlocked, false when the person goes back. */
function unlockDialog(document, profile, state, texts) {
  stylesheet(document);
  const kinds = new Set((state.methods ?? []).map(m => m.method).filter(m => METHODS.includes(m)));
  const statusLine = el(document, "p", { class: "nulavio-unlock__status", id: "nulavio-unlock-status", role: "status", "aria-live": "polite" });
  const say = (text, level = "info") => {
    statusLine.textContent = text;
    statusLine.dataset.level = level;
  };
  const field = (id, label, attrs) =>
    el(document, "label", { class: "nulavio-unlock__field" }, [
      el(document, "span", { text: label }),
      el(document, "input", { id, required: true, maxlength: attrs.maxlength, "aria-describedby": "nulavio-unlock-status", ...attrs }),
    ]);

  const password = field("nulavio-unlock-password", t("password"), { type: "password", autocomplete: "current-password", maxlength: 1024 });
  const recovery = field("nulavio-unlock-recovery", t("recovery"), {
    type: "text",
    class: "nulavio-unlock__code",
    autocomplete: "off",
    autocapitalize: "characters",
    spellcheck: "false",
    maxlength: 64,
  });
  const passwordForm = el(document, "form", { id: "nulavio-unlock-password-form" }, [password]);
  const recoveryForm = el(document, "form", { id: "nulavio-unlock-recovery-form", hidden: true }, [recovery]);
  const avatar = el(document, "div", { class: "nulavio-unlock__avatar", "aria-hidden": "true" });
  profile
    .getAvatarURL(48)
    .then(url => {
      avatar.style.backgroundImage = `url(${url})`;
      avatar.style.fill = profile.theme.themeBg;
      avatar.style.stroke = profile.theme.themeFg;
    })
    .catch(() => null);

  const back = el(document, "button", { type: "button", id: "nulavio-unlock-cancel", text: t("cancel") });
  const submit = el(document, "button", { type: "submit", class: "primary", id: "nulavio-unlock-submit", text: t("unlock") });
  const alternatives = el(document, "div", { class: "nulavio-unlock__alternatives" });
  const dialog = el(document, "dialog", { class: "nulavio-unlock", id: "nulavio-unlock", "aria-labelledby": "nulavio-unlock-headline" }, [
    el(document, "div", { class: "nulavio-unlock__who" }, [avatar, el(document, "span", { class: "nulavio-unlock__name", text: profile.name })]),
    el(document, "h2", { id: "nulavio-unlock-headline", text: t("headline") }),
    el(document, "p", { class: "nulavio-unlock__explain", text: texts.explain }),
    passwordForm,
    recoveryForm,
    statusLine, // under the field it is about (the field's description)
    alternatives,
    el(document, "p", { class: "nulavio-unlock__hint", text: t("no-master-key") }),
    el(document, "div", { class: "nulavio-unlock__actions" }, [back, submit]),
  ]);
  submit.setAttribute("form", passwordForm.id);

  return new Promise(resolve => {
    let done = false;
    const finish = value => {
      if (done) {
        return;
      }
      done = true;
      for (const input of dialog.querySelectorAll("input")) {
        input.value = "";
      }
      dialog.close();
      dialog.remove();
      resolve(value);
    };
    const busy = on => {
      for (const control of dialog.querySelectorAll("input, button")) {
        control.disabled = on;
      }
    };
    const refused = input => {
      input.value = "";
      input.setAttribute("aria-invalid", "true");
      input.focus();
    };
    const showRecovery = show => {
      for (const input of dialog.querySelectorAll("input")) {
        input.removeAttribute("aria-invalid");
      }
      say("");
      recoveryForm.hidden = !show;
      passwordForm.hidden = show || !kinds.has("password");
      alternatives.hidden = show;
      submit.setAttribute("form", show ? recoveryForm.id : passwordForm.id);
      submit.textContent = t(show ? "unlock-recovery" : "unlock");
      submit.hidden = !show && !kinds.has("password");
      back.textContent = t(show && (kinds.has("password") || kinds.has("os-keyring")) ? "back" : "cancel");
      dialog.querySelector(show ? "#nulavio-unlock-recovery" : "#nulavio-unlock-password")?.focus();
    };
    // The step as it opens: the password, or this computer's login when there is no password, or the
    // recovery code when it is all that is left.
    const firstStep = () => {
      if (!kinds.has("password") && !kinds.has("os-keyring")) {
        showRecovery(true);
        say(t("recovery-required"), "warn");
        return;
      }
      showRecovery(false);
      if (!kinds.has("password")) {
        dialog.querySelector("#nulavio-unlock-keyring")?.focus();
      }
    };
    // Unlocked: open it, unless the unlock settled a recovery code replacement (#187), which is said first.
    const opened = answer => {
      const note = SETTLED[answer?.recovery_code];
      if (!note) {
        finish(true);
        return;
      }
      const unrecorded = answer.warning === "not-recorded" ? ` ${t("not-recorded")}` : "";
      for (const node of [passwordForm, recoveryForm, alternatives, back]) {
        node.hidden = true;
      }
      busy(false);
      submit.hidden = false;
      submit.removeAttribute("form");
      submit.type = "button";
      submit.textContent = texts.open;
      // The note can be read for as long as it takes, and the profile locks itself again when nothing opens
      // it for two minutes: it is opened only if it is still unlocked, and unlocked again otherwise.
      const open = async () => {
        if ((await lockState(profile.path).catch(() => LOCKED)) === UNLOCKED) {
          finish(true);
          return;
        }
        submit.removeEventListener("click", open);
        submit.type = "submit";
        back.hidden = false;
        firstStep();
        say(t("locked-again"), "warn");
      };
      submit.addEventListener("click", open);
      say(`${t(note)}${unrecorded}`, "warn");
      submit.focus();
    };
    const attempt = async (method, input = null) => {
      say(t("unlocking"), "progress");
      const request = { op: "unlock", path: profile.path, method };
      if (input) {
        request.secret = input.value;
      }
      busy(true);
      try {
        const answer = await helper(request);
        if (input) {
          input.value = "";
        }
        opened(answer);
      } catch (e) {
        busy(false);
        const code = e?.code ?? String(e?.message ?? e);
        if (code === "keyring-missing" || code === "keyring-unavailable") {
          say(t("keyring-unavailable"), "error");
          dialog.querySelector(kinds.has("password") ? "#nulavio-unlock-password" : "#nulavio-unlock-recovery")?.focus();
        } else if (code === "wrong-secret" || code === "wrong-key") {
          say(t(method === "recovery-code" ? "wrong-recovery" : "wrong-password"), "error");
          refused(input);
        } else if (code === "recovery-code-malformed") {
          say(t("recovery-malformed"), "error");
          input.setAttribute("aria-invalid", "true");
          input.focus();
        } else if (UNAVAILABLE.has(code)) {
          say(t("storage-missing"), "error");
        } else {
          console.error("Nulavio chooser: unlock", e);
          say(t("unexpected"), "error");
        }
      }
    };

    passwordForm.addEventListener("submit", event => {
      event.preventDefault();
      attempt("password", dialog.querySelector("#nulavio-unlock-password"));
    });
    recoveryForm.addEventListener("submit", event => {
      event.preventDefault();
      attempt("recovery-code", dialog.querySelector("#nulavio-unlock-recovery"));
    });
    for (const input of dialog.querySelectorAll("input")) {
      input.addEventListener("input", () => {
        input.removeAttribute("aria-invalid");
        if (statusLine.dataset.level === "error") {
          say("");
        }
      });
    }
    back.addEventListener("click", () => {
      if (!recoveryForm.hidden && (kinds.has("password") || kinds.has("os-keyring"))) {
        showRecovery(false);
      } else {
        finish(false);
      }
    });
    dialog.addEventListener("cancel", event => {
      event.preventDefault(); // Escape: the same as the button, never in the middle of an unlock
      if (!back.disabled) {
        finish(false);
      }
    });
    if (kinds.has("os-keyring")) {
      alternatives.append(el(document, "button", { type: "button", id: "nulavio-unlock-keyring", text: t("use-keyring"), onclick: () => attempt("os-keyring") }));
    }
    if (kinds.has("recovery-code") && (kinds.has("password") || kinds.has("os-keyring"))) {
      alternatives.append(el(document, "button", { type: "button", id: "nulavio-unlock-use-recovery", class: "ghost-button text-link", text: t("use-recovery"), onclick: () => showRecovery(true) }));
    }

    document.body.append(dialog);
    dialog.showModal();
    firstStep();
  });
}

/** A step that only says something (the Vault is missing, the profile is gone) and goes back. */
function noticeDialog(document, headline, text) {
  stylesheet(document);
  const close = el(document, "button", { type: "button", class: "primary", id: "nulavio-unlock-cancel", text: t("back") });
  const dialog = el(document, "dialog", { class: "nulavio-unlock", id: "nulavio-unlock", "aria-labelledby": "nulavio-unlock-headline" }, [
    el(document, "h2", { id: "nulavio-unlock-headline", text: headline }),
    el(document, "p", { class: "nulavio-unlock__status", role: "status", "data-level": "error", text }),
    el(document, "div", { class: "nulavio-unlock__actions" }, [close]),
  ]);
  return new Promise(resolve => {
    const finish = () => {
      dialog.close();
      dialog.remove();
      resolve(false);
    };
    close.addEventListener("click", finish);
    dialog.addEventListener("cancel", event => {
      event.preventDefault();
      finish();
    });
    document.body.append(dialog);
    dialog.showModal();
    close.focus();
  });
}

// One launch is asked about at a time in a chooser window: a second activation while the first is still
// reading the profile's state, or while its unlock step is up, does nothing.
const asking = new WeakSet();

/** Whether `profile` may be launched now: asks for its secret first when it is a locked protected profile. */
export async function beforeLaunch(document, profile) {
  if (asking.has(document)) {
    return false;
  }
  asking.add(document);
  try {
    let state;
    try {
      state = await lockState(profile.path); // now, not as it was when the window opened
    } catch (e) {
      // Whether it is protected could not be read: not started, since it may be a locked one.
      console.error("Nulavio chooser: lock state", e);
      await loadWords();
      return await noticeDialog(document, t("unread-headline"), t("unexpected"));
    }
    if (state !== LOCKED) {
      return true; // no password, or already unlocked: nothing to ask, and nothing needed from the Vault's tools
    }
    await loadWords();
    let answer;
    try {
      answer = await status(profile);
    } catch (e) {
      // A protected profile cannot be opened without the tools, or without its key file being read: said,
      // never started on its locked folder.
      const code = e?.code ?? "";
      if (UNAVAILABLE.has(code)) {
        return await noticeDialog(document, t("unavailable-headline"), t("storage-missing"));
      }
      return await noticeDialog(document, t(code === "not-found" ? "gone-headline" : "unread-headline"), t(code === "not-found" ? "gone" : "unexpected"));
    }
    if (!answer.encrypted || !answer.locked) {
      // The tools see it otherwise than its files did a moment ago (it was unlocked meanwhile, or asking
      // them undid an interrupted protection): read again, and start it only if it is not locked now.
      if ((await lockState(profile.path).catch(() => LOCKED)) !== LOCKED) {
        return true;
      }
      return await noticeDialog(document, t("unread-headline"), t("unexpected"));
    }
    const { methods } = answer;
    const texts = { explain: await named("explain", profile), open: await named("open", profile) };
    return await unlockDialog(document, profile, { methods }, texts);
  } finally {
    asking.delete(document);
  }
}
