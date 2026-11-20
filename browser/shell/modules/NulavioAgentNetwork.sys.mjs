/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

/* This computer and the local network, in an engine an agent drives (#243, R29).

   The AI Bridge decides on its own DNS lookup of a name, and the engine connects
   to its own answer: a name can answer the Bridge with a public address and the
   engine with a local one (rebinding). The engine's Local Network Access decides
   on the address it connects to, but it lets through what its driver opens (the
   agent's own navigation runs as the system principal) and a redirect on the way
   there. So, in an engine the Bridge started (its environment says so, which
   nothing in the browser can change), this module checks every top-level page
   on the address the engine got it from: a response from an address the engine
   reads as this computer or the local network is cancelled before the tab shows
   it, unless the agent may reach that place now, as the Bridge's file says
   (launcher/nulavio_launcher/ai/tools.py, Bridge._write_local). The request has
   been sent by then: what is held back is the page. A load through a proxy is
   not checked (the proxy connects, not the engine), as Local Network Access
   does not check one either. A page from the HTTP cache carries no address
   when the check runs, so in these engines every top-level page is fetched,
   never taken from the cache: each one is asked to skip it, and one that comes
   from the cache all the same (a redirect hop can) is cancelled.

   In the same engines it sets the engine's Local Network Access to refuse a
   public page's requests to local addresses with no prompt, a pop-up's
   included, on the default branch and locked: nothing reaches the profile's
   prefs.js, which matters in the user's own profiles opened for an agent. The
   engine reads a site's own saved permission before that default: in these
   engines, keyed on the same variable, engine patch 0014 gives a saved allow no
   effect and refuses what Local Network Access would ask about (#570). Both
   are on before the Shell writes READY_FILE in the profile, and the Bridge uses
   the engine only once it is there (workspace.py, GUARD_READY). */

const WORKSPACE_ENV = "NULAVIO_AI_WORKSPACE"; // launcher/nulavio_launcher/ai/workspace.py WORKSPACE_ENV
const LOCAL_ENV = "NULAVIO_AI_LOCAL"; // workspace.py LOCAL_ENV
const READY_FILE = "nulavio-ai-guard"; // workspace.py GUARD_READY
// Both come before the cache is looked at; a redirect hop gets only the second.
const BEFORE_CACHE = Object.freeze(["http-on-opening-request", "http-on-modify-request"]);
const FROM_CACHE = Object.freeze(["http-on-examine-cached-response", "http-on-examine-merged-response"]);
const TOPICS = Object.freeze([...BEFORE_CACHE, "http-on-examine-response", ...FROM_CACHE]);
// What the AI Workspace also has in its user.js (workspace.py WORKSPACE_PREFS).
export const LOCAL_NETWORK_PREFS = Object.freeze([
  ["network.lna.enabled", true],
  ["network.lna.blocking", true],
  ["network.lna.allow_top_level_navigation", false],
  ["permissions.default.local-network", 2],
  ["permissions.default.loopback-network", 2],
]);
const MAX_FILE_BYTES = 65536;
const MAX_PLACES = 1024;

/** {all, places} from the Bridge's file, or null for anything else (then no local place is allowed). */
export function parseAllowed(text) {
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    return null;
  }
  if (!data || typeof data !== "object" || Array.isArray(data) || data.v !== 1 || typeof data.all !== "boolean"
      || !Array.isArray(data.places) || data.places.length > MAX_PLACES) {
    return null;
  }
  const places = new Set();
  for (const place of data.places) {
    if (!Array.isArray(place) || place.length !== 2) {
      return null;
    }
    const [host, port] = place;
    if (typeof host !== "string" || !host || host.length > 255 || !Number.isInteger(port) || port < 1 || port > 65535) {
      return null;
    }
    places.add(`${host} ${port}`);
  }
  return { all: data.all, places };
}

/** The place a page comes from, as the Bridge writes it (policy.canonical_host, Bridge._request_place): host in
    lower case without brackets or a final dot, and the port, the scheme's when the address has none. */
export function placeOf(uri) {
  if (uri.scheme !== "http" && uri.scheme !== "https") {
    return null;
  }
  const host = uri.asciiHost.toLowerCase().replace(/^\[(.*)\]$/, "$1").replace(/\.$/, "");
  return host ? [host, uri.port === -1 ? (uri.scheme === "https" ? 443 : 80) : uri.port] : null;
}

/** Whether the agent may reach this place now: Bridge._request_allowed for a local one (an http place allowed
    by asking covers the engine's upgrade of it to https). */
export function placeAllowed(allowed, place) {
  if (!allowed || !place) {
    return false;
  }
  const [host, port] = place;
  return allowed.all || allowed.places.has(`${host} ${port}`) || (port === 443 && allowed.places.has(`${host} 80`));
}

/** The type of a channel's proxy information ("direct", "http", …), or "" when it has none. */
function proxyType(channel) {
  try {
    return channel.QueryInterface(Ci.nsIProxiedChannel).proxyInfo?.type ?? "";
  } catch (e) {
    return "";
  }
}

/** The engine's address-space override for an address and port (network.lna.address_space.*.override, which tests
    use to make a loopback server count as public): true (private or local), false (public), or null (none). */
function overridden(address, port) {
  if (!Services.prefs.getBoolPref("network.lna.enabled", true)) {
    return null;
  }
  const key = address.includes(":") ? `[${address}]:${port}` : `${address}:${port}`;
  for (const [space, local] of [["public", false], ["private", true], ["local", true]]) {
    const listed = Services.prefs.getStringPref(`network.lna.address_space.${space}.override`, "");
    if (listed.split(",").some(entry => entry.replace(/\s/g, "") === key)) {
      return local;
    }
  }
  return null;
}

/** Whether an address is this computer or the local network, as the engine reads one (NetAddr::GetIpAddressSpace:
    its address-space overrides first; then loopback and "any" are local; RFC 1918, 0/8, link-local, unique-local and
    100.64/10 are private). Throws for text that is not an address. */
export function localAddress(text, port = -1) {
  const literal = String(text);
  const uri = Services.io.newURI(`http://${literal.includes(":") ? `[${literal}]` : literal}/`);
  const host = uri.asciiHost.toLowerCase().replace(/^\[(.*)\]$/, "$1");
  if (!/^[0-9a-f.:]+$/.test(host)) {
    throw new Error("not an address");
  }
  const forced = overridden(literal, port);
  if (forced !== null) {
    return forced;
  }
  // Loopback, also written as an IPv4-mapped IPv6 address (dotted, or as the URL parser writes it, in hex).
  if (/^(::ffff:)?127\./.test(literal.toLowerCase()) || /^::ffff:7f[0-9a-f]{2}:/.test(host) || host === "::1") {
    return true;
  }
  return Services.io.hostnameIsLocalIPAddress(uri) || Services.io.hostnameIsSharedIPAddress(uri);
}

class AgentNetwork {
  #armed = false;
  #file = "";

  /** An engine the Bridge started: its environment names the agent (the same check as NulavioAI.workspaceAgent). */
  driven() {
    return Boolean(Services.env.get(WORKSPACE_ENV));
  }

  /** At the Shell's start. Elsewhere than in an engine the Bridge started, nothing. */
  async arm() {
    if (this.#armed || !this.driven()) {
      return false;
    }
    this.#armed = true;
    this.#file = Services.env.get(LOCAL_ENV) || "";
    const defaults = Services.prefs.getDefaultBranch("");
    for (const [name, value] of LOCAL_NETWORK_PREFS) {
      const current = typeof value === "boolean" ? Services.prefs.getBoolPref(name) : Services.prefs.getIntPref(name);
      if (Services.prefs.prefIsLocked(name)) {
        // An enterprise policy decided it: not this module's to change. One that weakens it means this engine is not
        // used for an agent at all: READY_FILE is never written, and the Bridge does not start.
        if (current !== value) {
          throw new Error(`${name} is locked to another value`);
        }
        continue;
      }
      if (Services.prefs.prefHasUserValue(name) && current === value) {
        // The person's own value is already this one. A default equal to it would keep it out of prefs.js when the
        // profile is saved (the engine writes only values that differ from the default): it stays as it is.
        continue;
      }
      if (typeof value === "boolean") {
        defaults.setBoolPref(name, value);
      } else {
        defaults.setIntPref(name, value);
      }
      Services.prefs.lockPref(name); // the default wins over a value of the user's, and the lock is never saved
    }
    for (const topic of TOPICS) {
      Services.obs.addObserver(this, topic);
    }
    await IOUtils.writeUTF8(PathUtils.join(PathUtils.profileDir, READY_FILE), String(Services.appinfo.processID));
    return true;
  }

  observe(subject, topic) {
    let channel;
    try {
      channel = subject.QueryInterface(Ci.nsIHttpChannel);
    } catch (e) {
      return;
    }
    const loadInfo = channel.loadInfo;
    if (loadInfo.externalContentPolicyType !== Ci.nsIContentPolicy.TYPE_DOCUMENT) {
      return; // frames and a page's own requests: the engine's Local Network Access, set above
    }
    if (BEFORE_CACHE.includes(topic)) {
      // Whatever the method: a page from the cache would come with no address to check. One that comes from it
      // all the same is cancelled below.
      channel.loadFlags |= Ci.nsIRequest.LOAD_BYPASS_CACHE;
      return;
    }
    if (FROM_CACHE.includes(topic)) {
      channel.cancel(Cr.NS_ERROR_BLOCKED_BY_POLICY); // a top-level page is never taken from the cache here
      return;
    }
    // The engine's reading of the address it got the page from (its address-space overrides included), set once it
    // has connected. A proxied load has none: the proxy connected.
    const space = loadInfo.ipAddressSpace;
    const proxy = proxyType(channel);
    if (proxy === "direct" || (space === Ci.nsILoadInfo.Unknown && !proxy)) {
      // The engine records no address when the channel has proxy information, also when that says "direct" (a PAC
      // answer like "DIRECT; PROXY …", or a failover to a direct connection), and a redirect hop then keeps the one
      // of the hop before it. So the address it connected to is read here; one that cannot be read is not shown.
      let local;
      try {
        const internal = channel.QueryInterface(Ci.nsIHttpChannelInternal);
        local = localAddress(internal.remoteAddress, internal.remotePort);
      } catch (e) {
        channel.cancel(Cr.NS_ERROR_BLOCKED_BY_POLICY);
        return;
      }
      if (!local) {
        return;
      }
    } else if (space !== Ci.nsILoadInfo.Local && space !== Ci.nsILoadInfo.Private) {
      return;
    }
    const place = placeOf(channel.URI);
    channel.suspend();
    this.#allowed(place).then(
      ok => ok || channel.cancel(Cr.NS_ERROR_BLOCKED_BY_POLICY),
      () => channel.cancel(Cr.NS_ERROR_BLOCKED_BY_POLICY),
    ).finally(() => channel.resume());
  }

  async #allowed(place) {
    if (!this.#file || !place) {
      return false;
    }
    const bytes = await IOUtils.read(this.#file, { maxBytes: MAX_FILE_BYTES });
    return placeAllowed(parseAllowed(new TextDecoder().decode(bytes)), place);
  }
}

export const NulavioAgentNetwork = new AgentNetwork();
