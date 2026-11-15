/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* Meeting links, per profile (#221): "open in the app" (the default: the service's page and the engine's own
   prompt for its app, as always) or "join in the browser". In the browser, a meeting link is sent to the
   address where the service itself documents joining from a browser, before any request leaves; a service
   that documents none keeps its page and the engine's prompt (decision 1: no rewriting of undocumented
   addresses, which break without notice). Documented today:

   - Zoom: https://<host>.zoom.us/j/<meeting id> -> https://<host>.zoom.us/wc/join/<meeting id> ("Joining a
     meeting from a web browser", Zoom support), with its pwd and nothing else.

   Microsoft Teams documents no such address: its own page offers "Continue on this browser". */

export const PREF = "nulavio.meetings.join"; // shared/options.json: "app" (cleared) or "browser"

const ZOOM_HOST = /^(?:[a-z0-9-]+\.)*zoom\.us$/;
const ZOOM_JOIN = /^\/j\/(\d{9,11})$/;

/** Where a meeting link joins in the browser, or null when it is not one this knows. Pure: tested directly. */
export function browserJoinURL(spec) {
  const url = URL.parse(String(spec ?? ""));
  if (!url || url.protocol !== "https:" || url.port || url.username || url.password || !ZOOM_HOST.test(url.hostname)) {
    return null;
  }
  const id = ZOOM_JOIN.exec(url.pathname)?.[1];
  if (!id) {
    return null;
  }
  const join = new URL(`https://${url.hostname}/wc/join/${id}`);
  const pwd = url.searchParams.get("pwd");
  if (pwd && /^[\w.-]{1,128}$/.test(pwd)) {
    join.searchParams.set("pwd", pwd);
  }
  return join.href;
}

let observer = null;

export const NulavioMeetings = {
  /** From the Shell's start: top-level page loads of a meeting link go to the browser-join address when the
      profile asks for it. Nothing else is looked at, and nothing is read from the page. */
  watch() {
    if (observer) {
      return;
    }
    observer = {
      observe(subject) {
        if (Services.prefs.getStringPref(PREF, "") !== "browser") {
          return;
        }
        let channel;
        try {
          channel = subject.QueryInterface(Ci.nsIHttpChannel);
        } catch {
          return;
        }
        if (channel.loadInfo?.externalContentPolicyType !== Ci.nsIContentPolicy.TYPE_DOCUMENT) {
          return; // only what a tab shows, never a request a page makes
        }
        const target = browserJoinURL(channel.URI.spec);
        if (target) {
          try {
            channel.redirectTo(Services.io.newURI(target));
          } catch (e) {
            console.error("Nulavio meetings", e); // the link opens as it is: the service's page
          }
        }
      },
    };
    Services.obs.addObserver(observer, "http-on-modify-request");
  },

  unwatch() {
    if (observer) {
      Services.obs.removeObserver(observer, "http-on-modify-request");
      observer = null;
    }
  },
};
