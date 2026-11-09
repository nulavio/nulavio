// Nulavio baseline preferences (Track A preview, engine: upstream Firefox).
//
// Format: Firefox `user_pref(name, value);` lines. Each pref is preceded by
// annotations that the launcher and the tests read:
//
//   @mode      seed    -> written once into a *new* profile's prefs.js. The
//                         user can change it later in Settings and the change
//                         sticks (privacy by default, reversible by design).
//              enforce -> re-written to user.js on every launch. Reserved for
//                         settings the preview needs to function.
//   @category  privacy | tracking | https | network | ui | theme
//   @why       one-line rationale shown by `nulavio prefs explain`.
//   @tradeoff  what the user gives up, if anything.
//
// Rules for contributors (enforced by tests/unit/test_prefs.py):
//   * never weaken sandboxing, TLS, signature checks, Safe Browsing or updates;
//   * every pref must exist in the supported engine (integration test);
//   * no pref may send data to a Nulavio server (there is none).
// Values like "@STARTPAGE_URL@" are substituted by the launcher.

// --- Data collection: nothing leaves the machine unless the user opts in ---

// @mode seed
// @category privacy
// @why Do not upload Firefox health/usage telemetry; Nulavio is opt-in only.
// @tradeoff Mozilla loses usage signal from this install. Re-enable in Settings > Privacy.
user_pref("datareporting.healthreport.uploadEnabled", false);

// @mode seed
// @category privacy
// @why Master switch for data submission (same pref the DisableTelemetry policy sets).
// @tradeoff None for browsing.
user_pref("datareporting.policy.dataSubmissionEnabled", false);

// @mode seed
// @category privacy
// @why Disable the separate daily "usage" ping introduced in Firefox 135+.
// @tradeoff None for browsing.
user_pref("datareporting.usage.uploadEnabled", false);

// @mode seed
// @category privacy
// @why Do not keep a local archive of telemetry pings that are never sent.
// @tradeoff None.
user_pref("toolkit.telemetry.archive.enabled", false);

// @mode seed
// @category privacy
// @why No remote studies/experiments change this browser's behaviour silently.
// @tradeoff Mozilla experiments are not received. Security updates are unaffected (they ship via the engine package).
user_pref("app.shield.optoutstudies.enabled", false);

// @mode seed
// @category privacy
// @why Disable Normandy remote pref changes. Remote Settings (OneCRL, CRLite, add-on blocklist, Safe Browsing lists) stay ON.
// @tradeoff Mozilla cannot flip prefs remotely on this profile; fixes arrive with engine updates instead.
user_pref("app.normandy.enabled", false);

// @mode seed
// @category privacy
// @why No Nimbus rollouts switch features on remotely (Mozilla's AI features are one rollout away). Remote Settings (OneCRL, CRLite, add-on blocklist, Safe Browsing lists) stay ON.
// @tradeoff Features Mozilla rolls out gradually arrive with engine updates instead.
user_pref("nimbus.rollouts.enabled", false);

// @mode seed
// @category privacy
// @why No personalised extension recommendations based on browsing.
// @tradeoff None.
user_pref("browser.discovery.enabled", false);

// @mode seed
// @category privacy
// @why Crash reports are never submitted automatically; the user decides per crash.
// @tradeoff Upstream gets fewer crash reports.
user_pref("browser.crashReports.unsubmittedCheck.autoSubmit2", false);

// @mode seed
// @category privacy
// @why Send the Global Privacy Control signal (legally meaningful in several jurisdictions).
// @tradeoff None known; sites may treat it as an opt-out of sale/sharing.
user_pref("privacy.globalprivacycontrol.enabled", true);

// @mode seed
// @category privacy
// @why No sponsored shortcuts or stories if the user re-enables the Firefox new tab.
// @tradeoff None.
user_pref("browser.newtabpage.activity-stream.showSponsoredTopSites", false);

// @mode seed
// @category privacy
// @why No sponsored content in the Firefox new tab.
// @tradeoff None.
user_pref("browser.newtabpage.activity-stream.showSponsored", false);

// @mode seed
// @category privacy
// @why No sponsored suggestions in the address bar.
// @tradeoff None.
user_pref("browser.urlbar.suggest.quicksuggest.sponsored", false);

// --- Tracking & fingerprinting ---

// @mode seed
// @category tracking
// @why Enhanced Tracking Protection "Strict": blocks trackers, cross-site cookies, cryptominers and known/suspected fingerprinters in all windows.
// @tradeoff Some embeds/logins may break; the shield icon in the address bar disables it per site, and Mozilla's compatibility exceptions stay enabled.
user_pref("browser.contentblocking.category", "strict");

// --- HTTPS ---

// @mode seed
// @category https
// @why HTTPS-Only Mode: upgrade every connection; plain HTTP requires an explicit, per-site, revocable exception.
// @tradeoff An interstitial appears for HTTP-only sites; "Continue to HTTP site" adds a site exception.
user_pref("dom.security.https_only_mode", true);

// --- Network leaks ---

// @mode seed
// @category network
// @why Do not open speculative connections to hosts the user has not chosen to visit.
// @tradeoff Slightly slower first byte on some navigations.
user_pref("network.http.speculative-parallel-limit", 0);

// @mode seed
// @category network
// @why Do not pre-connect to address-bar suggestions while typing.
// @tradeoff Slightly slower navigation from suggestions.
user_pref("browser.urlbar.speculativeConnect.enabled", false);

// @mode seed
// @category network
// @why Do not pre-connect when hovering bookmarks/history entries.
// @tradeoff Slightly slower navigation from bookmarks.
user_pref("browser.places.speculativeConnect.enabled", false);

// @mode seed
// @category network
// @why Do not ask Mozilla's location service which country this computer is in (the request shows its address to Mozilla).
// @tradeoff The engine uses its region-neutral defaults instead of regional ones (search engine list, form autofill).
user_pref("browser.region.network.url", "");

// @mode seed
// @category network
// @why Do not repeat the region lookup on a timer.
// @tradeoff None beyond the lookup itself.
user_pref("browser.region.update.enabled", false);

// @mode seed
// @category network
// @why WebRTC only offers the default route's address, so local/VPN-side interfaces are not exposed to peers.
// @tradeoff Rare peer-to-peer setups on multi-homed hosts may need a TURN relay.
user_pref("media.peerconnection.ice.default_address_only", true);

// --- Search (docs/adr/0002-nulavio-search.md) ---

// @mode seed
// @category privacy
// @why Do not send what you type in the address bar to a search engine while you type. In the Nulavio build, suggestions are switched on per provider in Nulavio search settings.
// @tradeoff No remote search suggestions until you opt in. History, bookmark and open-tab suggestions still work; they stay on the device.
user_pref("browser.search.suggest.enabled", false);

// @mode seed
// @category privacy
// @why Do not ask the search engine for "trending searches" each time the address bar is focused.
// @tradeoff No trending list in an empty address bar.
user_pref("browser.urlbar.suggest.trending", false);

// @mode seed
// @category privacy
// @why Allow a separate default search engine for private windows (the engine's own feature, off by default upstream).
// @tradeoff None; both defaults start as the same engine.
user_pref("browser.search.separatePrivateDefault.featureGate", true);

// @mode seed
// @category privacy
// @why Private windows use their own default search engine, chosen independently in Settings.
// @tradeoff None.
user_pref("browser.search.separatePrivateDefault.enabled", true);

// --- Mozilla AI features (decision D-UX7; the Nulavio assistant follows ADR 0007) ---

// @mode seed
// @category privacy
// @why Mozilla's AI chatbot sends the selection or the page to a third-party chatbot site from the sidebar; off.
// @tradeoff No chatbot in the sidebar. Turn it on again in Settings > AI controls.
user_pref("browser.ml.chat.enabled", false);

// @mode seed
// @category privacy
// @why No "summarise this page" with the chatbot (it sends the page text to the chatbot site).
// @tradeoff None while the chatbot is off.
user_pref("browser.ml.chat.page", false);

// @mode seed
// @category privacy
// @why No "Ask an AI chatbot" item in the page context menu.
// @tradeoff None while the chatbot is off.
user_pref("browser.ml.chat.menu", false);

// @mode seed
// @category privacy
// @why No chatbot shortcut button over selected text.
// @tradeoff None while the chatbot is off.
user_pref("browser.ml.chat.shortcuts", false);

// @mode seed
// @category privacy
// @why Firefox's AI controls show the chatbot as blocked (the value its own "Blocked" choice writes).
// @tradeoff None; changeable in Settings > AI controls.
user_pref("browser.ai.control.sidebarChatbot", "blocked");

// @mode seed
// @category privacy
// @why Firefox's AI controls show smart tab groups (a downloaded model that names and fills groups) as blocked.
// @tradeoff Tab groups still work; names and suggestions are yours to choose.
user_pref("browser.ai.control.smartTabGroups", "blocked");

// @mode seed
// @category privacy
// @why Firefox's AI controls show Link Preview key points (a downloaded model summarising linked pages) as blocked.
// @tradeoff None while Link Preview is off.
user_pref("browser.ai.control.linkPreviewKeyPoints", "blocked");

// @mode seed
// @category privacy
// @why Firefox's AI controls show Smart Window (an AI window with an online assistant) as blocked.
// @tradeoff None; changeable in Settings > AI controls.
user_pref("browser.ai.control.smartWindow", "blocked");

// @mode seed
// @category privacy
// @why No smart tab grouping (suggested names and tabs from a downloaded model).
// @tradeoff Tab groups still work without suggestions.
user_pref("browser.tabs.groups.smart.enabled", false);

// @mode seed
// @category privacy
// @why No Link Preview: it fetches the linked page in the background with an identifying header before you open it.
// @tradeoff No preview card on long-press or shortcut; open the link to see the page.
user_pref("browser.ml.linkPreview.enabled", false);

// @mode seed
// @category privacy
// @why Extensions cannot run Mozilla's local AI models (browser.trial.ml), which are downloaded on demand.
// @tradeoff Extensions that need this API do not work.
user_pref("extensions.ml.enabled", false);

// --- Nulavio shell (preview) ---

// @mode seed
// @category ui
// @why Open the Nulavio start page on launch (generated per profile, local file, no network).
// @tradeoff None; changeable in Settings > Home.
user_pref("browser.startup.homepage", "@STARTPAGE_URL@");

// @mode seed
// @category ui
// @why Calm, empty new tab until the Nulavio built-in new tab ships (Track B).
// @tradeoff No shortcuts grid on new tabs.
user_pref("browser.newtabpage.enabled", false);

// @mode seed
// @category ui
// @why Nulavio provides its own onboarding; avoid two competing first-run flows.
// @tradeoff None.
user_pref("browser.aboutwelcome.enabled", false);

// @mode seed
// @category ui
// @why The preview must never ask to become the default browser (that would register the system Firefox).
// @tradeoff None.
user_pref("browser.shell.checkDefaultBrowser", false);

// @mode seed
// @category ui
// @why Skip the upstream "what's new" tab so the Nulavio start page is shown.
// @tradeoff Release notes are still reachable from Help > About.
user_pref("browser.startup.homepage_override.mstone", "ignore");
