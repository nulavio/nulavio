# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

## Nulavio's panes and groups inside the engine's settings page (ADR 0008).

nulavio-read-failed =
    .message = This option could not be read now. Reload the page to try again.

## Appearance

nulavio-layout-group =
    .label = Tabs and window layout
    .description = Where the tabs go in this profile's windows. The address bar and the security signs stay visible in every layout; only Immersive, below, takes them out of view.
nulavio-layout-lateral =
    .label = Lateral
    .description = Tabs down the side, always with their names.
nulavio-layout-top =
    .label = Tabs on top
    .description = Tabs across the top, as in most browsers.
nulavio-layout-focus =
    .label = Focus
    .description = A thin side strip that opens when the pointer reaches it.

nulavio-immersive =
    .label = Immersive
    .description = Takes the address bar and the tabs out of view; the band at the top keeps showing the profile and the site. They come back with the pointer at the edge of the window, with the keyboard, and by themselves whenever the browser has something to show.

nulavio-look-group =
    .label = Nulavio colours
    .description = Only how Nulavio's windows and pages look. Nothing here changes a protection.
nulavio-accent =
    .label = Accent colour
nulavio-accent-mint =
    .label = Mint (default)
nulavio-accent-blue =
    .label = Blue
nulavio-more-contrast =
    .label = More contrast
    .description = Stronger text and edges on Nulavio's windows and pages. For websites, use Contrast in Accessibility.
nulavio-newtab-ambience =
    .label = Soft background on the new tab
    .description = A coloured background behind the new tab's cards. Never in private windows.
nulavio-reduce-transparency =
    .label = Reduce transparency
    .description = Makes the new tab's cards solid.
# The same two switches when they cannot change anything, with the reason in place of the description.
nulavio-more-contrast-system =
    .label = More contrast
    .description = Your system already asks for high contrast, and Nulavio uses its colours.
nulavio-reduce-transparency-idle =
    .label = Reduce transparency
    .description = Nothing is transparent now: the soft background is off.
nulavio-reduce-transparency-system =
    .label = Reduce transparency
    .description = Your system already asks for less transparency, so the cards are solid.
nulavio-reduce-transparency-contrast =
    .label = Reduce transparency
    .description = “More contrast” already makes the cards solid.
nulavio-look-locked =
    .message = Some of these options are managed by your administrator.

## General (the engine's first pane, while accounts are turned off)

nulavio-pane-general =
    .heading = General
nulavio-pane-general-nav = General

## Profiles and protection

nulavio-pane-profiles =
    .heading = Profiles and protection
nulavio-pane-profiles-nav = Profiles and protection
nulavio-here-group =
    .label = You are in
    .description = This window's profile and how it is protected now.
# $name is the profile's name, chosen by the person.
nulavio-here-plain =
    .label = { $name }
    .description = No password. Nulavio does not encrypt this profile's data.
nulavio-here-protected =
    .label = { $name }
    .description = Protected and unlocked. It stays encrypted on disk while it is locked.
nulavio-here-temporary =
    .label = { $name }
    .description = Temporary. Erased when closed.
nulavio-here-unknown =
    .label = { $name }
    .description = This profile's protection could not be read.
nulavio-here-none =
    .label = Default profile
    .description = This window was opened outside Nulavio's profile group.
# One row per profile of the group. $name is the profile's name, chosen by the person; $here is "yes" for the
# profile of this window; $kind is "sensitive" for a profile made to clear itself every time it closes.
nulavio-profile-plain =
    .label = { $name }
    .description =
        { $here ->
            [yes] This profile. No password.
           *[no] No password.
        }{ $kind ->
            [sensitive] { " " }Sensitive sites: cookies, site data, history and cache are deleted every time it closes.
           *[other] { "" }
        }
nulavio-profile-unlocked =
    .label = { $name }
    .description =
        { $here ->
            [yes] This profile. Protected and unlocked: it locks again when you close its last window.
           *[no] Protected. Unlocked now: it locks again when you close its last window.
        }{ $kind ->
            [sensitive] { " " }Sensitive sites: cookies, site data, history and cache are deleted every time it closes.
           *[other] { "" }
        }
nulavio-profile-locked =
    .label = { $name }
    .description = Protected and locked: encrypted on disk.
nulavio-profile-temporary =
    .label = Temporary profile
    .description = Temporary. Erased when closed.
nulavio-profiles-group =
    .label = Your profiles
    .description = Each profile keeps its own logins, history and extensions. A protected profile stays encrypted on disk while it is locked.
nulavio-routing-group =
    .label = Which site opens in which profile
    .description = Links from other apps and typed addresses follow these rules and open straight in the right profile, before anything loads. Rules stay on this computer and only you create them.

## Privacy and security

nulavio-protections-group =
    .label = Nulavio's protections
    .description = What Nulavio adds to the browser's protections.
nulavio-filter-lists =
    .label = What uBlock Origin blocks
    .description = Ads, trackers and cookie notices: what disappears from each site depends on the lists switched on there. Open it to see or change them.
nulavio-filter-lists-cookies-hidden =
    .label = What uBlock Origin blocks
    .description = Cookie notices: hidden, by a list switched on in uBlock Origin. Ads and trackers depend on its other lists. Open it to see or change them.
nulavio-filter-lists-cookies-shown =
    .label = What uBlock Origin blocks
    .description = Cookie notices: shown. No cookie-notice list is switched on in uBlock Origin; open its lists to switch one on.
nulavio-filter-lists-off =
    .label = uBlock Origin is not on in this profile
    .description = Without it, ads and cookie notices are not blocked. Open Extensions and themes to turn it on.
nulavio-exceptions-group =
    .label = Site exceptions
    .description = Sites where a protection is off or relaxed, by you or by the browser itself. Remove an exception and the protection applies to that site again.
# $count is the number of changes waiting for a decision.
nulavio-guard-review =
    .label = Changes made outside Nulavio
    .description =
        { $count ->
            [0] Nothing to review.
            [one] 1 change to review.
           *[other] { $count } changes to review.
        }
nulavio-guard-review-unwatched =
    .label = Changes made outside Nulavio
    .description = The Guard does not watch this profile: it is temporary or an agent's AI Workspace.

## Privacy and security: DNS (inside the engine's own DNS group)

nulavio-dns-group =
    .label = DNS: who answers when you look up a site
    .description = To open a site, the browser asks a name service (DNS) for its address. Whoever answers sees which sites you look up. Nulavio receives nothing either way.

## Passwords

nulavio-passwords-group =
    .label = Who keeps your passwords
    .description = One manager per profile. Nulavio never reads your vault. With an extension, the browser's own save and fill prompts turn off, so only one manager offers to fill.
nulavio-passwords-now-none =
    .label = The browser's own manager is off
    .description = None of the managers Nulavio knows is on. Another extension may be handling passwords.
nulavio-confirmed-group =
    .label = Look-alike sites you confirmed
    .description = You chose to continue on these sites although they look like a site where you keep a saved login, so Nulavio does not warn about them in this profile. Remove one to get the warning back.

## Search

nulavio-search-group =
    .label = Suggestions: who receives what you type
    .description = With suggestions on, what you type in the address bar goes to the engine before you search. In Nulavio, only the engines switched on here receive it.
nulavio-search-add-group =
    .label = Engines Nulavio knows how to add
    .description = Known providers in one click, a SearXNG instance of yours, or a site's OpenSearch description. To build an engine by hand, use the add button of the list above.

## Assistant and AI

nulavio-pane-assistant =
    .heading = Assistant and AI
nulavio-pane-assistant-nav = Assistant and AI
nulavio-assistant-group =
    .label = Assistant and agents
    .description = Nulavio's assistant and agents such as Claude Code or Codex use a separate profile (the AI Workspace), with only the permissions you set.
nulavio-open-assistant =
    .label = Agents, permissions and activity
    .description = Connect an agent such as Claude Code or Codex, give or take permissions, pause, revoke, and see what was done.

## Tabs and browsing

nulavio-layout-moved-group =
    .label = Tab layout
nulavio-layout-moved =
    .label = Tabs on the side, on top or in Focus
    .description = The choice is in Appearance.
nulavio-shortcuts-group =
    .label = Nulavio's shortcuts
    .description = Keys for Nulavio's actions. You can change each one.
nulavio-key-none =
    .description = No key
nulavio-keys-change =
    .label = Change Nulavio's shortcuts
    .description = In the browser's own view, which checks each key against the system's and other extensions'.
nulavio-keys-reset =
    .label = Restore the default shortcuts

## Integrations

nulavio-pane-integrations =
    .heading = Integrations
nulavio-pane-integrations-nav = Integrations
nulavio-integrations-group =
    .label = Your desktop
    .description = What your desktop offers Nulavio, checked on this computer. The check changes nothing and sends nothing anywhere.
nulavio-open-integrations =
    .label = See the integrations
