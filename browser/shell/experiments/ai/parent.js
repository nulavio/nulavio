/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

"use strict";

/* global ExtensionAPI, ExtensionUtils, ChromeUtils */

/* Thin bridge: the logic lives in modules/NulavioAI.sys.mjs so it can be
   tested directly. Errors cross to the page as their stable code only. */

this.nulavioAI = class extends ExtensionAPI {
  module() {
    return ChromeUtils.importESModule("resource://builtin-addons/nulavio-shell/modules/NulavioAI.sys.mjs").NulavioAI;
  }

  getAPI(context) {
    const ai = this.module();
    // The browser window around the calling page (the sidebar's or a tab's): its selected tab is "this page".
    const windowOf = () => context.xulBrowser?.ownerGlobal?.browsingContext?.topChromeWindow ?? null;
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
    return {
      nulavioAI: {
        workspaceAgent: call(() => ai.workspaceAgent()),
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
        markWorkspace: call(text => ai.markWorkspace(text)),
        assistantState: call(() => ai.assistantState()),
        assistantConfigure: call(details => ai.assistantConfigure(details)),
        assistantAllow: call(allowed => ai.assistantAllow(allowed)),
        assistantForget: call(() => ai.assistantForget()),
        assistantPage: call(async () => ai.assistantPage(windowOf())),
        assistantAsk: call((question, includePage) => ai.assistantAsk(question, includePage, windowOf())),
        assistantTask: call(task => ai.assistantTask(task)),
      },
    };
  }
};
