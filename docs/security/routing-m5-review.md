# Security review: routing links clicked in pages (M5)

- **Date:** 2026-10-27
- **Scope:** [ADR 0003](../adr/0003-nulavio-profiles-and-routing.md), stage M5: applying Smart Profile Routing rules to navigations that a web page starts, which M4a (links from other apps) and M4b (typed addresses, "Open link in profile") leave alone.
- **Engine:** Gecko 158.0.1 (Nulavio build). Every engine fact below was read in that source tree.
- **Outcome:** M5 is **allowed with limits**, as an opt-in ("Also for links clicked in pages", off by default). Everything outside the limits stays in the current profile, as in any browser. Each refused case has a test.

## What changes

Without M5, a web page in profile A can only load things in A. With M5, a click in a page of A can make another profile B load one address, when one of the user's own rules sends that site to B. That is what M4a already allows any local app to do, but the source is now a web page, which is untrusted. The review asks what a hostile page can do with it.

## Where the decision runs

In the parent process, on `http-on-opening-request` for top-level document channels. The engine creates top-level document channels in the parent (`DocumentLoadListener`), and notifies this topic once per load, before the request is sent, and never for redirects (`nsHttpChannel::AsyncOpen` skips it when `LOAD_REPLACE` is set). When routing takes a load, the channel is cancelled there (`NS_BINDING_ABORTED`): no request reaches the site in profile A, and no cookie, header or body moves. Only the address is handed to B, the M4a way (remote service or a new instance, an argument list, with the routed flag).

The signals used are the engine's load info: `hasValidUserGestureActivation`, `isFormSubmission`, `isMetaRefresh`, `triggeringPrincipal`, `triggeringWindowId`, the origin attributes and the target browsing context. They are filled in by the content process (`nsDocShell`, `BrowsingContext::Navigate`), see T10.

## Threats and decisions

| # | Case | Decision | Why |
|---|---|---|---|
| T1 | Navigation without a user gesture: `location = ...` from a timer or on load, meta refresh | **Never routed** (loads here) | A page could otherwise send the user's other profiles to any address on a routed site, unseen and repeatedly |
| T2 | `POST` and every form submission, `GET` forms included | **Never routed** | A body cannot move between profiles without being sent again; a form carries what the user typed for this page's context |
| T3 | Redirects (`3xx`, and HTTPS upgrades) | **Never routed**; only the address the page asked for is decided | The first request was already made in A with A's cookies; the server controls the chain and could bounce the user into any profile; moving mid-flight sends the request twice. Consequence: links through a shortener or a tracking redirect stay here ([R45](residual-risks.md)) |
| T4 | Frames: navigations inside frames, and frames navigating the top page (`target=_top`) | **Never routed** | Only the top-level page the user sees decides; an embedded third party (an ad) cannot move the user |
| T5 | Pop-ups that keep an opener (`window.open` without `noopener`, sign-in pop-ups) | **Never routed** | The opener expects to script the pop-up (OAuth and payment flows); moving it breaks the flow and tells the opener what happened |
| T6 | Same-site navigation (source page and target on the same registrable domain) | **Never routed** | Keeps a site's own flows in one profile; a page opened here on purpose ("open here anyway") does not bounce every click |
| T7 | Private windows | **Never routed** | As M4a and M4b |
| T8 | Sources other than web pages (`moz-extension:`, `file:`, `about:` pages, the browser itself) | **Not M5** | Browser-initiated loads are M4a/M4b or explicit choices; extensions cannot use routing to reach other profiles |
| T9 | One click, many navigations (a page navigates again within the 5-second user-gesture window) | **One routed navigation per page and gesture window** (the engine's `dom.user_activation.transient.timeout`, 5 s); later ones load here | A single click must not open a burst of addresses in other profiles or start several instances |
| T10 | A compromised content process forges the gesture, form or frame flags | **Accepted residual** ([R45](residual-risks.md)) | The parent still requires `http(s)`, `GET`, a top-level target, a matching rule and the rate limit; the result is one address opened in the rule's profile, what any local app can already do (M4a) |
| T11 | Cross-profile request forgery: a page makes profile B request a URL on a routed site with B's cookies | **Accepted, bounded** | Needs a click; `GET` only (unsafe methods never move); the same request is what a page in B could already make with a link (`SameSite=Lax` cookies go with top-level `GET` navigations). The user's rule says that site belongs in B |
| T12 | Linking identities across profiles through the address (a page puts its own identifier in the link) | **Accepted residual** ([R45](residual-risks.md)) | The address moves by design. No `Referer`, cookie or storage moves. Same exposure as M4a and as container extensions |
| T13 | Probing which sites have rules (the page stays alive after a click that was routed, so it can tell) | **Accepted residual** ([R45](residual-risks.md)) | One bit per click, and the user sees the site open in the other profile; hiding it would mean unloading the user's page |
| T14 | Loops (A sends to B, B's rule sends back) | **Cannot happen** | B receives a command line with the routed flag (M4a); loads from command lines are browser-initiated (T8) |
| T15 | Single sign-on (a work site sends the user to an identity provider whose site a rule sends elsewhere) | **Mitigated by opt-in and T5/T6** | Pop-up sign-ins keep their opener (T5); redirect-based sign-ins are not re-decided (T3); a user who routes an identity provider's site and turns M5 on can add a "never switch" rule for it |
| T16a | Middle-click and Ctrl+click (the browser opens these itself, in a new tab) | **Not routed** (a new tab here) | The engine starts these loads from the parent with a gesture flag but without the page or frame they came from, so T4 cannot be checked; the link menu's "Open link in profile" does it explicitly |
| T16 | Speculative connections (DNS prefetch, preconnect on hover) to a routed site from A | **Unchanged** | They are connections without a request, cookies or a path; the engine's own behaviour, as in every profile |

`ask` rules show the same local question page as M4a and M4b, without loading the site. "Never switch" rules and sites without a rule load here.

## Why opt-in

M4a and M4b move only what the user sent to the browser. M5 moves what the user clicked in a page, and the page chooses the address (T11–T13), and sign-in flows that cross sites can change profile (T15). The default stays the behaviour of every browser; the setting says what it does: "Links you click in pages also follow your rules (not pop-ups, forms or redirects)".

## Verification

`tests/integration/test_routing.py` 15–22 (Nulavio build, two running profiles; 22/22 on 2026-10-27): with the setting off (the default) a clicked link stays; with it on, a clicked link and a `target=_blank` link with a rule open once, only in the rule's profile, the page stays and the empty tab closes; each refused case (no gesture, `GET` and `POST` forms, a redirect onto a routed site, a link inside a frame, a frame navigating the page, a pop-up with an opener, same-site, a private window, a second navigation after one click) loads only here; an `ask` rule shows the question and loads nothing; the Settings switch turns it off and the observer goes with it. The fixture server counts requests, so "only there" means the wrong profile never asked for the address.

## Implementation

- `NulavioRouter.sys.mjs`: `pageNavigationRefusal(facts)` (the table above as one pure function) and `siteOf()`.
- `NulavioRouting.sys.mjs`: `watchPages()` from the Shell's start (`nulavioRouting` experiment, `startup` event). The request observer is installed only while the opt-in, routing and a profile group are all on, and removed when any goes off, so nothing runs per request otherwise. A failure inside it is logged and the page loads here.
- Pref `nulavio.routing.inPage` (default off), shared by the group like the rules; Settings → Profiles → Smart routing → "Also for links clicked in pages".
