# Tools and budget

> **Draft, not approved (2026-11-27).** Nothing has been recorded, generated or published, and nothing has been bought or signed up for ([#176](https://github.com/nulavio/nulavio/issues/176)).

The tools the trailer and the shorts could use, and the budget. The maintainer approves each tool and each spend (rule 8). Pillow is already used by [`scripts/site/capture_site.py`](../../scripts/site/capture_site.py), and #173's pipeline uses it and FFmpeg on the host. Every other tool here is new to the repository. Adding one to the pipeline in [#173](https://github.com/nulavio/nulavio/issues/173) is a dependency change and follows [dependency updates](../security/dependency-updates.md).

**Decided by the maintainer on 2026-11-27** ([#176](https://github.com/nulavio/nulavio/issues/176#issuecomment-7210333283)):

- **Budget:** start at the free tier. The low tier (one month of a paid voice, US$6) is bought only if the free Portuguese voice sample does not serve.
- **Motion:** Motion Canvas, not Remotion.

Each tool below still waits for its own approval, and so does each spend. A decision on the tier does not approve a tool whose row says "not verified".

How to read the tables:

- **Promotional use counts as commercial use.** The videos promote a free project, but a tool whose terms allow only non-commercial use is treated as not allowed (rule 5).
- **Checked** means the terms were read on the tool's own page on 2026-11-27, at the link given. **Not verified** means they were not, and must be before approval. Terms change: they are read again on the day an asset is made, and that date goes in the manifest.
- Prices are list prices in US dollars on 2026-11-27, per month, before taxes (in Brazil, IOF on a card in a foreign currency). Promotional prices are not used.

## Recording and assembly

| Tool | Use | Software licence | Output | Cost | Data and privacy | Checked |
|---|---|---|---|---|---|---|
| The project's harness (`tests/lib/harness`, Marionette), through #173's `scripts/site/record_site.py` | Drives the real build through each scene and takes the window's own pixels frame by frame, headless, in the release test container | MPL-2.0 (this repository) | Ours | 0 | Local; throwaway HOME and profiles | n/a (in the repository) |
| [FFmpeg](https://ffmpeg.org/legal.html) | Encodes (VP9 WebM, H.264 MP4), assembly, caption tracks, in #173's compose step | LGPL-2.1 or later; GPL when built with its GPL parts | Ours | 0 | Local | Licence checked 2026-11-27 |
| Pillow | Draws the cursor and click ripples on the frames, in #173's compose step | Not verified | Ours | 0 | Local | Not verified |

Not a tool today, and the maintainer's to decide: a private X display (Xvfb) in the test container, for a capture at 60 real frames a second. The pipeline's frames are held, a few dozen a second at most ([trailer](trailer.md#what-173s-pipeline-records-today)). It would change a container, so it is decided with this list. Recommendation: not now; cut a sample from what the pipeline gives first.

## AI voice (text to speech)

Rule 3: no voice cloning, no voice imitating a real person. The provenance column says what is known about whose voice each one is. "Unknown" and "not verified" there are open points for the maintainer's approval of that voice.

| Tool | Languages | Software and model licence | Output | Voice provenance | Cost | Data and privacy | Checked |
|---|---|---|---|---|---|---|---|
| [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (open) | en (best graded voices: `af_heart` A, `af_bella` A−); pt-BR: `pf_dora`, `pm_alex`, `pm_santa` (ungraded) ([voices](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md)) | Apache-2.0 weights | No restriction stated; Apache-2.0 places none on output | **Unknown**: the model page does not say whose recordings trained the voices | 0; hardware needs not verified | Local: the script never leaves the computer | Licence and voices checked 2026-11-27 |
| [Piper](https://github.com/OHF-Voice/piper1-gpl) (open) | en_US: `joe`, `mike` (CC0, from rdh), `kristin`, `ljspeech`, `norman` (public domain), `kathleen` (from Hi-Fi TTS) and more; pt_BR: `cadu`, `jeff` (CC0, from rdh), `faber` (from Hi-Fi TTS) ([commercial use list](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/COMMERCIAL_USE.md)) | Code GPL-3.0 (piper1-gpl). The project grants no licence over voices: each voice's terms come from its training chain | Not stated for generated audio; the voices listed are those whose training chain is commercially permissive. `hifi_tts_92` and the voices fine-tuned from it (`faber`, `kathleen`) need a credit to Hi-Fi TTS, which then goes in the manifest and the description | Speakers of public datasets (rdh, Hi-Fi TTS, LJ Speech). The `faber` voice's [model card](https://huggingface.co/rhasspy/piper-voices/blob/main/pt/pt_BR/faber/medium/MODEL_CARD) names a CC0 dataset. Many voices were retrained in late 2026: only current copies are covered | 0; hardware needs not verified | Local | Checked 2026-11-27 |
| [ElevenLabs](https://elevenlabs.io/pricing) (paid) | en, pt-BR and many more | Proprietary service | Free plan: no commercial use, and credit is required. Paid plans: commercial licence, kept after the plan ends, outside beta features ([help centre](https://elevenlabs.io/docs/help-center/legal/can-i-publish-the-content-i-generate-on-the-platform)) | **Not verified**: whose voices the vendor offers was not read. Rule 3 decides it: a voice that is a clone of a real person's voice, which a voice shared in a vendor's library may be, is not used without that person's written consent. Before the low tier is bought, the chosen voice's provenance and terms are read on the vendor's own pages and written in the manifest. If no voice with a provenance that rule 3 allows serves, this row is not usable | Starter US$6 (30,000 credits, about 30,000 characters); Creator US$22 (121,000 credits) | The script text goes to the vendor. Whether inputs train its models, and the opt-out, is not verified | Terms and prices checked 2026-11-27; data use not verified |

Decided (2026-11-27): Kokoro and Piper first, on a sample of the trailer in both languages. A paid voice only if the free Portuguese sample does not serve, and then only a voice that passes the provenance check in its row.

## Music

| Tool | Software and model licence | Output | Cost | Data and privacy | Checked |
|---|---|---|---|---|---|
| [Stable Audio Open 1.0](https://huggingface.co/stabilityai/stable-audio-open-1.0) (open weights) | [Stability AI Community License](https://stability.ai/license) | Commercial use allowed for individuals and organisations under US$1M annual revenue; "as between you and Stability, you own outputs". Up to 47 s a clip; better at sound effects and textures than music | 0; hardware needs not verified | Local. Whether the weights' download needs an account is not verified | Checked 2026-11-27 |
| [Pixabay](https://pixabay.com/service/license-summary/) music (library, not AI) | n/a | Free, no credit required; selling it on its own, misleading use, and use as a trademark are prohibited. The summary says nothing about Content ID claims on platforms | 0 | Account to download | Summary checked 2026-11-27; full licence and Content ID not verified |
| [Suno](https://suno.com/pricing) (paid) | Proprietary service | Free plan: Suno keeps ownership, non-commercial only, so **not usable** (rule 5). Pro and Premier: commercial use for songs made while subscribed ([help](https://help.suno.com/en/articles/2416769)); download limits per month were announced in 2026, not verified | Pro US$10 a month billed monthly (US$8 a month billed yearly, US$96); Premier US$30 a month (US$24 billed yearly, US$288) | Prompts go to the vendor | Prices and ownership checked 2026-11-27; download limits not verified |

YouTube asks for its synthetic-content label when generated music is the main focus of a video ([YouTube help](https://support.google.com/youtube/answer/14328491)). Here it is background, but the label is set anyway (rule 4).

## Sound effects

| Tool | Output | Cost | Checked |
|---|---|---|---|
| [Freesound](https://freesound.org/help/faq/) (library) | Only CC0 sounds; CC BY only with the credit in the manifest and the description; CC BY-NC never (no commercial use) | 0; account to download | Checked 2026-11-27 |
| Stable Audio Open 1.0 | As in the music table; its strength is short effects | 0 | Checked 2026-11-27 |
| ElevenLabs sound effects (paid) | Paid-plan terms apply, but the sound-effect terms were not read separately | In the plan's credits | Not verified |

## Motion and composition

| Tool | Licence | Output | Cost | Checked |
|---|---|---|---|---|
| [Motion Canvas](https://github.com/motion-canvas/motion-canvas) (decided 2026-11-27) | MIT | Ours. It renders each frame as an image (PNG, JPEG or WebP) from its editor, which runs in a browser, and the frames go to video with FFmpeg ([rendering](https://motioncanvas.io/docs/rendering/)). Whether a render can be started by a command, without the editor, is not verified, and #176 asks for one command that re-renders every piece | 0 | Licence and rendering checked 2026-11-27; a render without the editor not verified |
| FFmpeg | As above | Ours | 0 | As above |

Decided (2026-11-27): Motion Canvas. [Remotion](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md) was considered and is not used: its licence (read on 2026-11-27) is free only for individuals, for-profit organisations of up to 3 employees and non-profits, which would need an eligibility check that MIT does not.

## Captions and transcripts

WebVTT captions and transcripts in both languages are generated from these scripts by the pipeline (#173), not by speech recognition, so they match the approved text. No tool is needed beyond the pipeline's own code.

## AI disclosure

Every video says it in three places (rule 4):

1. **In the video:** the line on the end card ([message house](message-house.md#every-piece-carries)).
2. **In the description:** the same line, plus the link to the claims.
3. **The platform's label**, where one exists:
   - YouTube: "Altered or synthetic content" set to yes on upload ([YouTube help](https://support.google.com/youtube/answer/14328491), checked 2026-11-27).
   - TikTok, Instagram and Facebook: their AI-generated content labels. Not verified.
   - Mastodon, Bluesky, LinkedIn: no label known. The line goes in the post text and the video's alt text.

## Asset manifest (rule 5)

Each generated or licensed asset gets one entry, beside the asset, like [`site/assets/shots/manifest.json`](../../site/assets/shots/manifest.json). The pipeline in #173 writes it. Fields proposed:

- `file` and `sha256`;
- `kind` (voice, music, sfx, motion, recording) and `ai_generated` (yes or no);
- `tool`, `model` or version, `plan` (free, a paid plan's name), `date`;
- `input`: the script line ID (for example `T2 VO en`), or the prompt;
- `terms_url`, `terms_checked` (date), `commercial_use` (yes or no), `credit_required` (and its text);
- `voice_provenance` for a voice;
- for a recording: the build version and ID, the `dom_changes`, and the frame check.

## Budget

The voice-over is short. All of it, the trailer and the six shorts in both languages, is about 5,600 characters (counted on 2026-11-27). With four takes of each line, about 22,000 characters.

| Option | Status | What it buys | Cost | Quality risk |
|---|---|---|---|---|
| **Free** | **Decided: the start** | Kokoro or Piper voice, Stable Audio Open or Pixabay music, Freesound CC0 effects, Motion Canvas, FFmpeg | US$0 in tools. The cost is the maintainer's computer time | The Portuguese voices are the weakest part: Kokoro's are ungraded, Piper's sound more synthetic |
| **Low** | Decided: only if the free Portuguese voice sample does not serve | Free, plus ElevenLabs Starter for one month for the voice (22,000 characters fit its 30,000 credits) | US$6 once, plus taxes | Low for the sound: a natural voice. Open for rule 3: the voice's provenance is not verified (its row above). Music stays from the free route |
| **Full** | Not chosen | Low, but ElevenLabs Creator for headroom, plus Suno Pro for one month for an original score | US$22 + US$10 = US$32 for one month, plus taxes. Each later re-render month (after 1.0, for example) is the same again | Low. Generated music needs listening for artefacts and resemblance to known songs |

**Decided on 2026-11-27 ([#176](https://github.com/nulavio/nulavio/issues/176#issuecomment-7210333283)): free first; low only if the free Portuguese voice does not serve.** The order of work:

1. Once the free tools are approved, render a sample of the trailer in both languages with them: Kokoro's `pf_dora`, `pm_alex` and `pm_santa` and Piper's `cadu`, `jeff` and `faber` for Portuguese.
2. The maintainer listens. If one Portuguese voice serves, nothing is bought.
3. If none serves, the low tier: one month of ElevenLabs Starter (US$6), after the chosen voice's provenance and the vendor's data use are read (both are "not verified" above).

Music stays free. The full tier was not chosen. Any spend is the maintainer's, after the tool is approved (rule 8).
