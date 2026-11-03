/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionCommon, ExtensionUtils, ChromeUtils */

/* Thin bridge: the logic lives in modules/NulavioAI.sys.mjs so it can be
   tested directly. Errors cross to the page as their stable code only. */

this.nulavioAI = class extends ExtensionAPI {
  module() {
    return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs").NulavioAI;
  }

  getAPI(context) {
    const ai = this.module();
    // The browser window around the calling page (the sidebar's or a tab's): its selected tab is "this page".
    // Gecko 158 renamed Node.ownerGlobal to documentGlobal (AI-01); older engines only have ownerGlobal.
    const windowOf = () => {
      const browser = context.xulBrowser;
      const global = browser?.documentGlobal ?? browser?.ownerGlobal;
      return global?.browsingContext?.topChromeWindow ?? null;
    };
    const call = fn => async (...args) => {
      try {
        return await fn(...args);
      } catch (e) {
        if (e?.code) {
          throw new ExtensionUtils.ExtensionError(e.code);
        }
        console.error(e);
        throw new ExtensionUtils.ExtensionError("unexpected");
      }
    };
    // An Ask started from this page stops when the page goes away (the side panel closed: Q18).
    context.callOnClose({ close: () => ai.assistantOwnerClosed(context) });
    return {
      nulavioAI: {
        workspaceAgent: call(() => ai.workspaceAgent()),
        workspaceTarget: call(async () => ai.workspaceTarget()),
        overview: call(() => ai.overview()),
        detect: call(() => ai.detect()),
        plan: call((agent, client) => ai.plan(agent, client)),
        install: call((agent, client, replace) => ai.install(agent, client, replace ?? false)),
        add: call(details => ai.add(details)),
        change: call((agent, op, details) => ai.change(agent, op, details ?? {})),
        setStopped: call(stopped => ai.setStopped(stopped)),
        activity: call((limit, agent) => ai.activity(limit ?? 100, agent ?? null)),
        clearActivity: call(() => ai.clearActivity()),
        request: call(id => ai.request(id)),
        answer: call((id, answer) => ai.answer(id, answer)),
        watch: call(() => ai.watch()),
        markWorkspace: call(texts => ai.markWorkspace(texts)),
        assistantState: call(() => ai.assistantState(windowOf())),
        assistantConfigure: call(details => ai.assistantConfigure(details)),
        assistantAllow: call(allowed => ai.assistantAllow(allowed)),
        assistantForget: call(() => ai.assistantForget()),
        assistantPage: call(async () => ai.assistantPage(windowOf())),
        assistantInclude: call(source => ai.assistantInclude(source, windowOf())),
        assistantRemove: call(async chipId => ai.assistantRemove(chipId, windowOf())),
        assistantChips: call(async () => ai.assistantChips(windowOf())),
        // `options.chips`: the items included in this message (AI-02, UX5-B); `options.expected`: what the panel showed.
        assistantAsk: call((question, options) => ai.assistantAsk(question, options ?? {}, windowOf())),
        assistantTask: call((task, expected) => ai.assistantTask(task, expected ?? null, windowOf())),
        assistantStart: call((kind, details) => ai.assistantStart(kind, details ?? {}, windowOf(), context)),
        assistantCancel: call(async runId => ai.assistantCancel(runId, windowOf())),
        assistantRuns: call(async () => ai.assistantRuns(windowOf())),
        assistantThread: call(async () => ai.assistantThread(windowOf())),
        assistantThreadClear: call(async () => ai.assistantThreadClear(windowOf())),
        assistantThreadLeavePage: call(async () => ai.assistantThreadLeavePage(windowOf())),
        assistantThreadCarry: call(async recipient => ai.assistantThreadCarry(recipient, windowOf())),
        // Only the events of runs in this page's own window reach it.
        onAssistantEvent: new ExtensionCommon.EventManager({
          context,
          name: "nulavioAI.onAssistantEvent",
          register: fire => ai.subscribeAssistant((win, event) => {
            if (win === windowOf()) {
              fire.async(event);
            }
          }),
        }).api(),
      },
    };
  }
};
