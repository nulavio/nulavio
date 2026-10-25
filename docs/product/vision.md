# Product vision

**Nulavio** — *Your web. Your rules.* · *A web é sua. Seus dados também.*

## Problem

People who care about privacy on Linux assemble their own browser: they harden Firefox by hand, add a content blocker, wire up a password manager, and hope none of it silently regresses after an update. The result is fragile and hard to audit. Most "private browsers" either overpromise (~~"unhackable"~~, ~~"100% blocked"~~) or hide their trade-offs.

## Vision

A Linux-first desktop browser that is **private by default, honest about its limits, and calm to use**. It is built on a mature engine (Gecko), works with the password manager you already trust, and blocks ads and trackers from the first launch. Every protective setting is explained and reversible.

## Principles

1. **Security by design, privacy by default.** Least privilege, deny by default, conservative failure.
2. **Honesty over marketing.** We separate implemented, prototype and planned. We never claim immunity against malware on the host.
3. **Upstream first.** Keep the engine's sandbox, isolation, TLS, Safe Browsing and updates. Patch as little as possible.
4. **Your tools, not ours.** Integrate with Proton Pass, KeePassXC and Bitwarden through official interfaces. Never build a second vault.
5. **Nothing phones home.** There is no Nulavio server and no telemetry.
6. **Calm UX.** No fear-driven banners. Every warning carries an action and a way back.
7. **Linux-native.** Wayland, KDE and GNOME conventions, portals, accessibility and scaling.
8. **Sustainable for a small team.** Automation, pinned inputs and a minimal patch stack.

## Who it is for

- **Primary:** privacy-conscious Linux users (developers, SREs, journalists, researchers) who want strong defaults without maintaining a hardening guide.
- **Secondary:** small teams that want auditable, consistent browser profiles on Linux workstations.

## Non-goals (for now)

- Writing an engine, a password manager or our own blocklists.
- Windows/macOS before Linux is stable.
- Anonymity against global adversaries (that is Tor Browser's job).
- Protection against malware already running on the host (see [residual risks](../security/residual-risks.md)).

## What success looks like (MVP)

A user on Fedora KDE installs Nulavio and signs in to Proton Pass or pairs KeePassXC. They browse with ads and trackers blocked, can undo any breakage per site in two clicks, and can read in one place exactly what Nulavio changed and why. No step needs a terminal, except during the preview.
