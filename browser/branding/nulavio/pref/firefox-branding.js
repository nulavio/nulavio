/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

// Nulavio branding prefs. Privacy/security defaults live in
// browser/config/prefs/baseline.js (applied by the launcher / policies).

// No Mozilla "what's new" or welcome pages for a non-Mozilla build.
pref("startup.homepage_override_url", "");
pref("startup.homepage_welcome_url", "");
pref("startup.homepage_welcome_url.additional", "");

// Updates are delivered by the distribution package (built with
// --disable-updater); these only document where releases are announced.
pref("app.update.url.manual", "");
pref("app.update.url.details", "");

// Keep the Self-XSS paste protection of the web console ON (official
// branding uses 0; the "unofficial" branding relaxes it with 5).
pref("devtools.selfxss.count", 0);

// Nulavio is not a MOZILLA_OFFICIAL build, so the engine's defaults for
// "local developer builds" apply unless overridden. Restore the values
// Mozilla ships to users (modules/libpref/init/all.js, MOZILLA_OFFICIAL branch):
// no privileged Browser Console / Browser Toolbox and no remote-debugging
// connections by default (a "paste this into the console" scam vector), and no
// chrome console output on stdout.
pref("devtools.chrome.enabled", false, sticky);
pref("devtools.debugger.remote-enabled", false, sticky);
pref("browser.dom.window.dump.enabled", false, sticky);
pref("devtools.console.stdout.chrome", false, sticky);

// Google Safe Browsing with Nulavio's own API key (docs/architecture/build.md).
// Google serves the phishing, malware, unwanted-software and harmful-app lists
// to any Safe Browsing API key, but not the download-protection lists
// ("mwb-4b" and "csdda-32b" answer HTTP 404) nor the remote download check
// (HTTP 403: "Safe Browsing Download Protection API" is not publicly available).
// The engine asks for all lists of a provider in one request, so one
// unavailable list made every update fail and left NO list active.
// Request only the lists this key can get, and switch off the remote download
// check: it would send download details to Google and get an error back.
pref("browser.safebrowsing.provider.google5.lists", "goog-phish-proto,googpub-phish-proto,goog-malware-proto,goog-unwanted-proto,goog-harmful-proto,goog-globalcache-proto");
pref("browser.safebrowsing.provider.google4.lists", "goog-phish-proto,googpub-phish-proto,goog-malware-proto,goog-unwanted-proto,goog-harmful-proto");
pref("urlclassifier.downloadBlockTable", "");
pref("urlclassifier.downloadAllowTable", "");
pref("browser.safebrowsing.downloads.remote.enabled", false);

// Follow the desktop's language among the locales packaged in the build
// (en-US and pt-BR), as distribution Firefox does. An empty value means "use
// the OS locales" (intl/locale/LocaleService.cpp); users can still pick a
// language in Settings.
pref("intl.locale.requested", "");

// Nulavio Horizon window theme (content/theme/horizon.css). false restores
// the upstream look, including the GTK colours of the default theme on Linux.
pref("nulavio.horizon.enabled", true);

// Mozilla's AI features are off (decision D-UX7). The Nulavio assistant is the
// one AI path, governed by ADR 0007: per-profile consent, the recipient shown
// before Send, and the bridge's policy for tasks. Mozilla's chatbot would send
// the selection or the page to a third-party site from the sidebar, the page
// context menu and the selection shortcut, outside those rules. The same values
// are in browser/config/prefs/baseline.js for Track A (tests keep them equal).
// The browser.ai.control.* values are what Firefox's own AI controls write when
// a person picks "Blocked"; Settings can still turn a feature back on.
pref("browser.ml.chat.enabled", false);
pref("browser.ml.chat.page", false);
pref("browser.ml.chat.menu", false);
pref("browser.ml.chat.shortcuts", false);
pref("browser.ai.control.sidebarChatbot", "blocked");
pref("browser.ai.control.smartTabGroups", "blocked");
pref("browser.ai.control.linkPreviewKeyPoints", "blocked");
pref("browser.ai.control.smartWindow", "blocked");
pref("browser.tabs.groups.smart.enabled", false);
// Link Preview fetches the linked page in the background with an identifying
// header before the person opens it: off in 1.0, key points included.
pref("browser.ml.linkPreview.enabled", false);
// Local models for extensions (browser.trial.ml), downloaded on demand.
pref("extensions.ml.enabled", false);
// Nimbus rollouts can switch features on remotely (Smart Window is one rollout
// away). Security fixes arrive with engine updates; Remote Settings (OneCRL,
// CRLite, the add-on blocklist, Safe Browsing lists) are separate and stay on.
pref("nimbus.rollouts.enabled", false);

// No Mozilla account or Sync in Nulavio 1.0 (decision D-UX8): no account
// button or sign-in promo in the toolbar and app menu, no Sync, Send Tab or
// Relay suggestions that need an account.
pref("identity.fxaccounts.enabled", false);
// Sidebar launcher tools for new profiles: the engine's list
// (browser/components/sidebar/SidebarManager.sys.mjs) without the chatbot and
// without "tabs from other devices", which needs a Mozilla account. The
// Nulavio assistant adds itself; the person can add or remove tools.
pref("sidebar.main.tools", "opentabs,bookmarks,history,passwords");

// No Mozilla theme picker in the add-ons manager (Mozilla artwork).
pref("browser.aboutaddons.novaThemesPickerEnabled", false);

// No default shortcuts on the engine's home page (about:home): the list comes
// from Remote Settings and starts with "Add-ons for Firefox". Sites the person
// visits still appear there.
pref("browser.topsites.useRemoteSetting", false);
pref("browser.newtabpage.activity-stream.default.sites", "");

// UX3F (QA A5/M4): the sidebar launcher moves on Nulavio's standard motion
// curve and narrows faster than it widens (browser/patches/0008). Reduced
// motion still turns the animation off.
pref("sidebar.animation.duration-ms", 220);
pref("sidebar.animation.collapse-duration-ms", 160);
pref("sidebar.animation.easing", "cubic-bezier(0.2, 0, 0, 1)");
// UX7: the Foco preset opens the launcher on hover (expand-on-hover) with the same expand token
// (motion.duration.expand), not the engine's 400 ms; its 200 ms intent delay stays.
pref("sidebar.animation.expand-on-hover.duration-ms", 220);

// UX3F (QA A3): no empty bookmarks toolbar sliding in under a new tab and
// pushing it down. The toolbar stays one shortcut away (Ctrl+Shift+B), and the
// person's choice in the toolbar menu is kept.
pref("browser.toolbars.bookmarks.visibility", "never");

// UX3F (QA A2): no Mozilla product names in Nulavio's own UI. Address-bar
// results are not grouped under a "Firefox Suggest" heading (the results
// and their order are unchanged), and the "Firefox Labs" Settings pane, which
// lists Mozilla's remote experiments, starts hidden (Nimbus rollouts are off).
pref("browser.urlbar.groupLabels.enabled", false);
pref("browser.preferences.experimental.hidden", true);

// UX3G N2: about:addons opens on the person's own extensions, without the
// "Recommendations" pane (AMO picks that Firefox recommends, "by Firefox"
// themes) and without its per-extension recommendation cards. Add-ons are still
// one search away on the same page. Settings drops "More from Mozilla"
// (Mozilla's product promotions).
pref("extensions.getAddons.showPane", false);
pref("extensions.htmlaboutaddons.recommendations.enabled", false);
pref("browser.preferences.moreFromMozilla", false);

// UX3H M-1: no Mozilla privacy-notice tab (mozilla.org) on the first launch.
// The engine opens it to tell people that data is sent to Mozilla; Nulavio
// sends none unless the person opts in (browser/config/prefs/baseline.js sets
// the same master switch for profiles the launcher seeds). Off here too, so a
// plain package and a profile created without the launcher behave the same:
// no data submission, no notice and no request to mozilla.org at startup.
pref("datareporting.policy.dataSubmissionEnabled", false);
pref("datareporting.policy.firstRunURL", "");
// No "Suggest Firefox Relay email masks" offer: Relay needs a Mozilla account,
// which Nulavio 1.0 does not offer (D-UX8). An empty value hides the option in
// Settings and every Relay prompt; saved logins are unaffected.
pref("signon.firefoxRelay.feature", "");

// Performance and privacy: about:home (still the start page of profiles that
// came from earlier builds) does not fetch the weather or stories in the
// background. Defaults only: a person who turns them on keeps that choice.
pref("browser.newtabpage.activity-stream.showWeather", false);
pref("browser.newtabpage.activity-stream.widgets.weather.enabled", false);
pref("browser.newtabpage.activity-stream.feeds.section.topstories", false);

// Unlocking with a phone is not part of 1.0 (decision D10, 2026-11-04): the
// Companion app is not published, so connecting a phone is not offered and
// the pages say "not available yet". A phone that is already connected keeps
// unlocking and can be removed. Developers testing the Companion turn this on.
pref("nulavio.vault.phone.pairing", false);
