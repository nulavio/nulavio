# nulavio.net redesign: specification

Status: phase 1, 2026-11-27 ([#173](https://github.com/nulavio/nulavio/issues/173)). This document and the recording pipeline are done; the pages are not changed yet. Phase 2 rebuilds the pages on the brand chosen in [#175](https://github.com/nulavio/nulavio/issues/175) (proposal A) once that lands, and adds `media-src 'self'` to the site's policy. The maintainer's decision of 2026-11-27: start now, in parallel, without waiting for the Orion features ([#172](https://github.com/nulavio/nulavio/issues/172)); show what exists today with real recordings, and leave room for #172's features as they ship.

Still open, and the maintainer's: the moodboard and the two or three visual directions of #173's plan (steps 1 and 2), and the choice between them. This document fixes what holds whatever direction is chosen: the structure, the motion rules, the media rules, the budgets and the recording pipeline. It does not choose a look.

## What stays

These come from the current site and its tests (`tests/unit/test_site.py`, `site/_headers`). The redesign keeps them; changing one is the maintainer's decision, recorded with its reason.

| Rule | Where it is checked today |
|---|---|
| No scripts: no `<script>`, no `script-src` in the policy, no inline handlers. Motion is CSS only, and a page is complete without it | `test_site.py` |
| No third parties: no font, image, video, embed or analytics from another origin. No YouTube or Vimeo | `site/_headers` (`default-src 'none'`), `test_site.py` |
| No cookie, no tracking; the waitlist worker keeps only what [site/AGENTS.md](../../site/AGENTS.md) lists | `test_site.py` (the worker under Node) |
| Honest copy: no invented testimonials, user counts or audits; one trade-off under every feature ("Sem letra miúda" / "No fine print"); what the alpha lacks is marked as coming; "not affiliated with Mozilla" | `test_copy_is_honest` |
| Both languages with the same ids and the same structure | `test_site.py` |
| Real captures: screenshots from the real build by `scripts/site/capture_site.py`, hashed in a manifest, with a transcript on the page. Recordings follow the same rule (below) | `site/assets/shots/manifest.json` |
| Neutral about third parties: no search engine, translator, password manager or AI provider shown as part of Nulavio or as the recommended choice; when one is shown, its alternatives are shown with it | review; [provider neutrality](https://github.com/nulavio/nulavio/issues/172) |
| The waitlist, the download pages and the deploy through `.github/workflows/site.yml` keep working; `scripts/site/verify_live.py` checks the deployed headers | `site.yml` |

## Information architecture

### Landing (`/`, `/en/`)

The landing presents Nulavio as it is meant to ship, and keeps its present order and ids. Each feature gains one media slot; nothing else moves.

| Section (id) | Today | Phase 2 | Media |
|---|---|---|---|
| Hero (`hero-h`, `hero-email`) | Headline, the waitlist form, a drawn window | The same, with the drawn window replaced by a still of the real window (`capture_site.py` fig-1), or the short loop of a scene once a direction is chosen | Still; a loop only if the direction asks for it |
| Protection from the first click (`protect-h`) | Text and a drawn panel (HTML and CSS): a page's blocked counts | Text and the first-launch scene | Loop + video (scene planned: first launch) |
| Profiles (`profiles-h`) | Text and a drawn panel: the routing rules | Text and two scenes: a profile opening, a link routed to the right profile | Loops + videos: `profile-opens`, `link-routed` (recorded) |
| Encrypted profiles (`vault-h`) | Text and a drawn panel: a locked profile and its ways to unlock | Text and the unlock scene | Loop + video: `protected-unlocks` (recorded) |
| Guard (`guard-h`) | Text and a drawn panel: changes to review | Text and the Guard review (still today: fig-5) | Still; a scene planned |
| AI (`ai-h`) | Text and a drawn panel: an agent's permissions (it names one agent, with no alternative beside it) | Text and the AI Bridge scene, its provider choice shown with its alternatives | Planned |
| Also built in (`more-h`) | List | List; search provider choice and Copy Link to Highlight as short loops | Planned |
| Comparison (`compare`, `compare-h`) | Table | Unchanged in structure; rows change in both languages with the date | None |
| Questions (`faq`, `faq-*`) | `<details>` | Unchanged | None |
| Waitlist (`join`, `join-email`, `join-os`) | Form | Unchanged | None |

A drawn panel is replaced by the real thing only where a recording or a capture of the build shows the same moment; until then it stays, as it is today. Every feature section keeps exactly one `.fine` line ("Sem letra miúda:" / "No fine print:"), as `test_copy_is_honest` reads it. A media slot never carries a claim the text does not: what the clip shows is in its transcript, and the transcript is read from the browser's own interface at capture time.

### Engineering pages (`/engenharia/`, `/en/engineering/`)

The document that says what is ready today stays text first. Where a section describes something a scene shows, the scene's video goes there with `controls`, its captions and its transcript, as evidence for the text, not as decoration. No loops here. The fingerprinting comparison is generated (`privacytests_pages.py`) and does not change.

### Waitlist (`/lista/`, `/en/waitlist/`, and the link pages)

No media and no motion beyond the states of the form (focus, the button pressed). The forms, their `action`-less link page and the worker do not change. The link page is a static file the worker serves; it must stay light and work with no styles.

### Download pages and later pages

The download pages (`/baixar/`, `/en/download/`) are generated from `packaging/release.json` and change only in shared styles. #173's plan adds, later: one page per main feature, a press kit (logo, screenshots, clips, a fact sheet) and social exports (16:9, 1:1, 9:16). Each reuses the recordings of this pipeline; none is in phase 2 unless the maintainer asks.

### How the Orion features (#172) slot in

A feature of #172 gets a place on the site only when it ships in a published release, or marked "Em breve" / "Coming soon" with the existing rule for what the alpha lacks. For each one:

1. its scene is added to `scripts/site/record_site.py` (`SCENES`, a method, captions in both languages), recorded from a build that has it;
2. it goes in the section of the landing it belongs to (`more-h`, or a new feature section with its own `.fine` line and ids in both languages);
3. the comparison gains its row in both languages, with the date;
4. the engineering pages say whether it is ready, a prototype or planned (I11).

A feature never appears in a recording before it is in the build the recording comes from.

## Motion system (CSS only)

Motion on the site has one job, as in the window ([motion map](motion-map.md)): to show where something comes from, never to decorate. It uses the brand's motion tokens (`docs/brand/tokens.json`: `motion.duration.fast` 120 ms, `base` 180 ms, `slow` 280 ms; the `standard`, `enter` and `exit` curves) through the generated custom properties (`--nv-motion-duration-*`, `--nv-motion-easing-*`), which the landing already uses.

**Allowed**

- **Transitions** of colour, background, border and opacity on hover, focus and press, at `fast` or `base`. A colour change may stay under reduced motion (it is not movement).
- **Entrance**: a section's media or a card arriving as it scrolls into view, by opacity and a small `translate` (at most 16 px), as a scroll-driven animation (`animation-timeline: view()`), and only as progressive enhancement:

  ```css
  @media (prefers-reduced-motion: no-preference) {
    @supports ((animation-timeline: view()) and (animation-range: entry)) {
      .feature .media { animation: arrive linear both; animation-timeline: view(); animation-range: entry 0% entry 60%; }
    }
  }
  @keyframes arrive { from { opacity: 0; translate: 0 16px; } }
  ```

  With no support, or with reduced motion, the rule never applies and the element is simply there. The `animation-range: entry` test is part of the condition so that partial implementations are left out. Support, per the project's [Modern Web Guidance](../../.agents/skills/modern-web-guidance/SKILL.md) (`scroll-entry-exit-effects`, read 2026-11-27): Baseline since 2026-10-27, Firefox from 159, so Nulavio 160 runs it; to check again on the build in phase 2.
- **`@keyframes` that run once** on load, as the landing's drawn window does today (`rise`, `settle`): under `prefers-reduced-motion: no-preference`, with no animation of layout properties.

**Not allowed**

- Parallax, scroll hijacking, pinned scrolling sections, anything that moves text while it is read.
- Animating `width`, `height`, `top`, `left`, margins or anything else that lays the page out again.
- Motion on a claim, a warning or the comparison: a claim that is still arriving cannot be read yet.
- Looping decoration. The only things that move by themselves are the short loops below, and they stop.
- Flashing: nothing flashes more than three times in a second, whatever the motion preference (WCAG 2.3.1).
- `animation-duration: 0.01ms` blanket overrides: reduced motion is handled where each animation is declared (opt in under `no-preference`).

**Reduced motion: nothing moves.** Every movement above lives inside `@media (prefers-reduced-motion: no-preference)`. The loops are behind `<source media="(prefers-reduced-motion: no-preference)">`, so a person who asked for less motion gets the poster. Phase 2 tests it: the built pages have no `animation`, `transition` of a spatial property or animated image outside those conditions (`test_site.py`).

## Media policy

### Formats and markup

| Use | Format | Markup |
|---|---|---|
| A still (poster, screenshot) | WebP (lossy for posters, lossless for screenshots), PNG master in `docs/design/` | `<img width height alt>`, or `<picture>` with light and dark sources |
| A short loop (at most 5 s) | Animated WebP, 10 frames a second at most, played once (it stops by itself) | `<picture><source media="(prefers-reduced-motion: no-preference)" srcset="…-loop.webp" type="image/webp"><img src="…-poster.webp" width height alt="…"></picture>` |
| A scene (the whole recording) | VP9 WebM first, H.264 MP4 as the fallback; muted, with no audio track at all | `<video controls preload="none" playsinline poster="…-poster.webp" width height>` with both sources, `<track kind="captions" srclang default>` and the transcript next to it |

- **Never autoplay.** A `<video>` that plays by itself cannot honour reduced motion without a script, and downloads before the person asks. Videos start when the person presses play; `preload="none"` downloads nothing before.
- **Loops stop within 5 seconds.** Without a script there is no pause button, so what moves by itself must stop by itself within five seconds (WCAG 2.2.2). The loop is the 5 s of the scene the script marks as its highlight, played once; the full scene is the video. When a scene cuts to a window that opens, the loop shows at least a second of that window: if it opened late (an unlock can take long), the loop starts later. Compose reads each loop back from its file and refuses it unless it plays once and lasts 5 s at most.
- **The alt text** of a loop's `<img>` says what the scene shows; the transcript has the details. No information is given by motion alone: the text of the section says what the clip shows.
- **Captions** are WebVTT, one file per recording, in that recording's language; each language's page uses its own recording (the interface itself is in that language). A caption stays long enough to be read: at most 20 characters a second, by the times its WebVTT file gives, or the scene is not saved and compose refuses it. The last one lasts to the end of the encoded video.
- **AV1** (SVT-AV1 is in the host's ffmpeg) is left for later: it would be a third copy of each scene, worth it only if it measures much smaller.

### Hosting and the policy

- Same origin only: the files go in `site/assets/clips/` in phase 2. `img-src 'self'` already covers the stills and the loops; videos need `media-src 'self'`, the only change to `site/_headers` (and to the worker's copy of the headers for the link page, and to `verify_live.py`). No `blob:`, no `data:`, no other origin.
- The served types (`video/webm`, `video/mp4`, `text/vtt`, `image/webp`) are checked on the deployed site in phase 2 (`verify_live.py`).
- Until phase 2 the sample recordings live in `docs/design/recordings/` and are not deployed.

### Sizes

| What | Budget |
|---|---|
| Any one media file | under 2 MB (`record_site.py compose` fails above it) |
| A poster | under 150 KB |
| The first view of a page (HTML, CSS, fonts, images above the fold, posters) | under 1.5 MB |
| Video bytes before the person presses play | none |
| Video width and rate | 1280 px (captured at 1.5× of a 1280×800 window, scaled down), 30 frames a second |
| Loop width and rate | 800 px, every third frame of the video: 10 a second |

Repository budget: media in the history counts against ADR 0013's 250 MB ([point 3](../adr/0013-repository-layout.md)). Frames are never committed; only the files the site serves (or, in phase 1, the samples) are. Each re-recording replaces files and adds its size to the history, so a scene is re-recorded when the interface it shows changes, not on every release.

## Performance and accessibility budgets

These are #173's done criteria, with how phase 2 checks them.

| Budget | Check |
|---|---|
| LCP under 2.5 s on a throttled mobile profile | In CI, with a tool still to choose: it needs a browser in the site workflow, which is a new dependency and the maintainer's call ([below](#open-decisions)) |
| First view under 1.5 MB | Static: `test_site.py` sums what each built page loads before any scroll (HTML, CSS, fonts, `<img>` and posters above the fold); no browser needed |
| No layout shift from media (CLS under 0.1) | Static: every `<img>`, `<video>` and `<picture>` carries `width` and `height` (or the CSS gives it an `aspect-ratio`) |
| No video downloaded before play | Static: every `<video>` has `preload="none"`, a `poster`, `controls`, no `autoplay`, no `loop` |
| Reduced motion: no animation, no moving image | Static: animations and loops only inside `prefers-reduced-motion: no-preference`; on a build of the site in Nulavio, with `ui.prefersReducedMotion` set, no running animation and the posters shown (an integration test, through the queue) |
| AA contrast from the tokens | `scripts/brand/contrast.py`, as today, for every new pair the direction uses |
| Keyboard and visible focus | Every control reachable, focus ring from the tokens; the media's controls are the browser's own |
| Captions and transcripts | Static: every `<video>` has a captions track in the page's language, and a transcript in the page |
| Nothing moves by itself for more than 5 s | Static: each loop's duration, read from the file, is at most 5 s and it plays once |

## The recording pipeline

Shared with the promotion pieces of [#176](https://github.com/nulavio/nulavio/issues/176): one pipeline, not two.

### How it works

`scripts/site/record_site.sh <install-dir>` records every scene and composes it, in one command. `<install-dir>` is the directory that holds the `nulavio` executable: a release package unpacked, or a development package of this tree. It is the only argument. The scenes, the two languages, the frame rate, the sizes and the output directory (`docs/design/recordings/2026-11`) are fixed in the script; there is nothing else to choose. It has two steps because the release test container has the engine's libraries but no image tools, and the host has the image tools but must not run the engine outside the shared test slot:

1. **Capture** (`tests/integration/record_site_scenes.py`, which calls the scenes in `scripts/site/record_site.py`). It runs where the integration tests run: in the release test container (`ci/containers/fedora-release-itest.Containerfile`), with FUSE for the Vault, started by name: `NULAVIO_INTEGRATION_IMAGE=fedora-release-itest NULAVIO_TEST_ARTIFACTS=<dir> scripts/release/run_integration.sh <install-dir> record_site_scenes.py`. Its name does not match `test*.py`, so the suite, CI and the release never run it. Each scene runs on `tests/lib/harness.GeckoProfileSession`: a throwaway home, registered engine profiles, headless, never a user profile; fixture pages with original text on loopback; an artificial password on a throwaway volume. The scene acts through the interface (Settings › Profiles, the address bar, the unlock page) the way the integration tests do, and checks what it shows (the window's interface in the recording's language, the band's words, the tab in the right instance, the page requested once); a scene that cannot reach its state fails, it is never staged. A window is not recorded while the bundled content blocker's button says a tab loaded before the blocker was ready, which can happen when a script opens a page in the first seconds of a profile's first start: its tabs are reloaded first. It writes the window's own pixels as PNG frames and a `timeline.json`: when each frame shows, the scripted cursor's path, the clicks, the cuts between windows, the captions and a transcript read from the DOM. A scene gets its `timeline.json` only after it passed and its session, its mounts and its fixture server were taken down, each step whatever the others did; until then the file is `timeline.json.part`, which compose does not read. Every run empties `<dir>/recordings/` first, so a scene that fails this time leaves no timeline of an earlier run to compose.
2. **Compose** (`python3 -I scripts/site/record_site.py compose <dir>/recordings`, on the host, no engine): draws the cursor (eased paths, a ripple on each click) on the frames, then writes for each scene and language a VP9 WebM, an H.264 MP4, the 5 s loop as animated WebP, a poster, the WebVTT captions, and `manifest.json` (hashes, sizes, transcript, captions, every edit; the length is the encoded video's). It makes the whole set or nothing: it needs the timeline of every scene in both languages, builds everything in a private temporary directory (`TMPDIR`), and replaces the output directory with it only when every scene encoded and every check passed. No recording of an earlier run is kept beside new ones. The checks: each file within the size budget; each loop's length and play count, read from its file, and the window it shows; captions that can be read; each timeline the one of its scene and language, its frames regular files with the names this script writes (the captures come out of the container); and no personal value in the manifest (the home directory anywhere; the user and host names as whole words in the transcripts, which is what was read from the screen). It needs Pillow and ffmpeg (Fedora's `python3-pillow` and `ffmpeg-free`), which `capture_site.py` and the media fixtures already use; nothing is added to a lockfile or a container.

On a machine whose test slot is shared, the capture is queued like an integration module and compose is run on its artifacts. When a step of `record_site.sh` fails, it keeps that run's files and prints their directory; when the step is compose, it prints the command that composes the same captures again.

Each recording in the manifest says what made it, in two parts. `capture` is what the capture knows about itself: when it ran, the engine's build id and version, and `script_blob`, git's id of `record_site.py` as it ran (`git log --find-object=<id>` finds the commits that have it). The capture runs on a copy of the tree without git's data, so it names no commit; with a development package, the Shell in the frames is the tree that made the package, which nothing in the package identifies. `composed` is the checkout that drew and encoded the files, which can be a later one; when the change lands as one squashed commit, it names a commit of the pull request's branch, not of `main`.

**What the tool does not try to handle.** It is a maintainer's tool, run by one person from a checkout, a few times a year. It does not coordinate two runs at once, and a crash while the output directory is being replaced leaves it incomplete (git tracks it, and the next run replaces it whole). It trusts its inputs as it trusts the checkout: the captures are what this script wrote in the project's own container, so compose checks them for mistakes, not against someone who can write into the captures or the output directory while it runs. It records only in the release test container, whose fonts and rendering are the ones in the frames; another host's are not supported.

### What a recording changes, and says it does

Every recording lists these in the manifest:

- the window's `remotecontrol` attribute is removed (the striped address bar of automation), as for the screenshots;
- the cursor is drawn afterwards: a headless window has no pointer, so hover states are not shown;
- typing is shown at a fixed pace, one frame per key, each key really typed into the field;
- while a new instance starts, nothing is recorded: the video cuts to its window once it is up, and the manifest says how many real seconds were cut;
- what the script set up before the scene (the profiles it created, a routing rule, a profile already open, a search engine, the protected profile unlocked and locked once to write its prefs, the fixture pages in each window's tabs, Settings scrolled) is a note of that recording.

Neutrality shapes the scenes too. A new window's own first page names the profile's search engine with nothing beside it; the focused address bar shows that engine's icon and, while an address is typed, offers to search with it; Settings' choice of a new profile's search engine lists providers. None of these is shown with a real provider alone: every window, the first one, one that opens and one already open, gets fixture pages in its tabs before its first frame; the profile where an address is typed searches with a local test engine on loopback (as `test_search` does); and Settings is scrolled so that its provider list stays out of frame. Each of these is a note of the recording, and a unit test reads the notes of the committed samples. A scene about search (planned) shows Settings › Search as it is: every provider in alphabetical order, each with its "Use" button, none recommended. No control of that list is preselected, but a profile always has an engine in use, and the scene shows that too: a new profile starts on DuckDuckGo (first run has no search step), so on a new profile DuckDuckGo's row reads "In use in normal and private windows".

Reproducible means: the same script on the same build records the same scenes. The files are not byte-identical between runs (frame timing, encoder versions), so the manifest holds the hashes of the files committed.

### Scenes

| Scene | Shows | Status |
|---|---|---|
| `profile-opens` | Settings › Profiles; Open on "Trabalho"/"Work"; its own window opens with its band | Recorded (sample) |
| `link-routed` | In "Pessoal"/"Personal", an address of the work intranet is typed; it opens in the "Trabalho"/"Work" window, whose band says the rule did it | Recorded (sample) |
| `protected-unlocks` | Settings › Profiles with "Bancos"/"Banking" locked; Unlock; the password typed on the unlock page; the profile opens in its window | Recorded (sample) |
| First launch | The welcome and its protection checks | Planned |
| Guard | A change made from outside, reported and undone | Planned |
| Search provider | Settings › Search: every provider in alphabetical order with its "Use" button, none recommended; one click on "Use" changes the profile's search. The row of the engine in use says so, which on a new profile is DuckDuckGo | Planned |
| Copy Link to Highlight | A link that opens on the passage | Planned |
| AI Bridge | An agent's workspace and what it may do | Planned |

The samples in [recordings/2026-11](recordings/2026-11/manifest.json) come from a development package of this tree on the published engine (160.0.1-0.2) and the brand before #175. Phase 2 records them again on the new brand; until then they show the pipeline, not the final site.

### For #176

The promotion pieces need more than the site: 4K at 60 frames a second, longer takes and exports in three aspect ratios. The capture here takes the window's pixels through Marionette, which gives a few dozen frames a second at most and draws no pointer, which is enough for the site (frames are held, the cursor is drawn). For 60 fps the capture would read a private X display instead (as the [reference captures](references/2026-11/README.md) did with `x11grab`), which needs Xvfb in the test container: a change to a container, so the maintainer's call. The timeline format, the cursor drawing, the captions and the manifest stay as they are.

## Phases

1. **Phase 1 (this change).** The specification, the recording pipeline, three sample scenes in both languages.
2. **Phase 2, after #175 lands.** `media-src 'self'`; the landing and the engineering pages rebuilt on the chosen direction and the new brand; the scenes recorded again and moved to `site/assets/clips/`; the static checks of the budgets in `test_site.py`; `verify_live.py` extended.
3. **Later.** The moodboard and directions (if the maintainer still wants them after #175), the feature pages, the press kit, the social exports, #172's scenes as they ship, #199's link previews.

## Open decisions

The maintainer's, with a recommendation each:

- **How LCP is measured in CI.** A browser in the site workflow is a new dependency. Recommendation: Nulavio's own build through the existing integration container and queue (no new tool), measuring LCP from the engine's own `largest-contentful-paint` entries on the built pages (support to check on the build); the static checks above cover the rest.
- **Loops on the landing, or videos only.** Recommendation: loops of at most 5 s that stop, plus the video for the whole scene; if the chosen direction wants a calmer page, posters only, with the video.
- **Xvfb in the test container for #176's 60 fps capture.** Recommendation: decide with #176's tool list and budget, not here.
