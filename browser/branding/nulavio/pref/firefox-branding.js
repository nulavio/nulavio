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
