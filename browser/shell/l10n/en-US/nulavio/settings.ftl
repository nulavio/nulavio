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
# profile of this window.
nulavio-profile-plain =
    .label = { $name }
    .description =
        { $here ->
            [yes] This profile. No password.
           *[no] No password.
        }
nulavio-profile-unlocked =
    .label = { $name }
    .description =
        { $here ->
            [yes] This profile. Protected and unlocked.
           *[no] Protected. Unlocked now.
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
    .label = Nulavio's engines
    .description = Search suggestions turned on per engine, and engines the browser does not bring.
nulavio-open-search =
    .label = Engines and per-engine suggestions

## Assistant and AI

nulavio-pane-assistant =
    .heading = Assistant and AI
nulavio-pane-assistant-nav = Assistant and AI
nulavio-assistant-group =
    .label = Assistant and agents
    .description = Nulavio's assistant and agents such as Claude Code or Codex use a separate profile (the AI Workspace), with only the permissions you set.
nulavio-open-assistant =
    .label = Assistant, agents and activity
    .description = Turn the assistant on, connect an agent, pause, revoke and see what was done.

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
