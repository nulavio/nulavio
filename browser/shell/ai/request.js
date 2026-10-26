/* "Agent permission request" (S7): an agent asked for something its settings
   say to ask about. The page names the agent, what it wants and where; the
   answer applies once or for that agent's current session, or refuses. It is
   never shown in an AI Workspace, which the agent itself drives. States on
   <body data-state>: loading, asking, answered, expired, error. */

import { localize, t } from "../lib/i18n.js";
import { announce, errorText } from "../lib/ui.js";

const ai = browser.nulavioAI;
const id = new URLSearchParams(location.search).get("id") ?? "";
const byId = name => document.getElementById(name);

function setState(state, message = "", level = "ok") {
  document.body.dataset.state = state;
  announce(message, level);
}

async function closeSoon() {
  const tab = await browser.tabs.getCurrent();
  const siblings = await browser.tabs.query({ windowId: tab.windowId });
  setTimeout(() => (siblings.length > 1 ? browser.tabs.remove(tab.id) : browser.tabs.update(tab.id, { url: "about:newtab" })), 1200);
}

async function answer(value) {
  for (const button of document.querySelectorAll("#actions button")) {
    button.disabled = true;
  }
  try {
    await ai.answer(id, value);
    setState("answered", t(value === "deny" ? "aiAnsweredDeny" : value === "session" ? "aiAnsweredSession" : "aiAnsweredOnce"));
    await closeSoon();
  } catch (e) {
    setState(e?.message === "invalid" ? "expired" : "error", e?.message === "invalid" ? t("aiRequestExpired") : errorText(e), "error");
  }
}

async function render() {
  const request = await ai.request(id);
  byId("who").textContent = t("aiRequestFrom", [request.agent, t(`aiLevel_${request.autonomy}`)]);
  byId("headline").textContent = t("aiRequestWants", [request.agent, t(`aiCap_${request.capability}`)]);
  if (request.target) {
    byId("target").textContent = request.target;
    byId("target").hidden = false;
  }
  byId("once").addEventListener("click", () => answer("once"));
  byId("session").addEventListener("click", () => answer("session"));
  byId("deny").addEventListener("click", () => answer("deny"));
  setState("asking");
  byId("deny").focus(); // the safe answer is the default for the keyboard
}

localize();
render()
  .catch(e => {
    if (e?.message === "expired") {
      for (const button of document.querySelectorAll("#actions button")) {
        button.hidden = true;
      }
      byId("headline").textContent = t("aiRequestTitle");
      setState("expired", t("aiRequestExpired"), "error");
    } else {
      setState("error", errorText(e), "error");
    }
  })
  .finally(() => {
    document.documentElement.dataset.ready = "true";
  });
