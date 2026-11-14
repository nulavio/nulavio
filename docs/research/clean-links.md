# Clean links: the tracking parameters people meet, against the engine's lists

Status: measured 2026-11-14 for #158, on the engine of Nulavio 160.0-0.4 (Firefox 160.0).

"Copy Clean Link" and "Copy Clean Link to Highlight" are the engine's own feature (#157). They drop the parameters on the engine's strip-on-share list: `StripOnShare.json` (Mozilla's) and `StripOnShareLGPL.json` (from ClearURLs), both in `omni.ja` under `chrome/toolkit/content/global/antitracking/`, plus the parameters of the pref `privacy.query_stripping.strip_list` (`URLQueryStrippingListService.sys.mjs` adds them to the global rule). The pref is also the list the engine strips from a navigation when query stripping is on, which Nulavio's Strict mode turns on (`qps` in `browser.contentblocking.features.strict`).

So Nulavio adds what the lists miss through that pref, in `browser/config/prefs/baseline.js`, with no copy implementation of its own.

## The comparison

Each row is a parameter that common links carry. "Engine" says where the engine's lists already have it: `global` (any site), a site rule (that site's hosts only), or `—` (nowhere). The reference list was [ClearURLs](https://github.com/ClearURLs/Rules)' global rules (`data.min.json`, SHA-256 `907c2f52…3d9371`, read 2026-11-14), and the vendors' own documents where they publish one.

| Parameter | Who adds it, and where it is seen | Source | Engine | Nulavio |
|---|---|---|---|---|
| `utm_source`, `utm_medium`, `utm_campaign`, `utm_term`, `utm_content` and other `utm_*` | Campaign tags on links in mail, ads and posts | [Google Analytics, traffic-source dimensions](https://support.google.com/analytics/answer/11242870) | global | — |
| `gclid`, `gbraid`, `wbraid`, `gad_source`, `gad_campaignid` | Google Ads auto-tagging | same | global | — |
| `dclid` | Google Campaign Manager 360 and Display & Video 360 auto-tagging | same; [Display & Video 360, enhanced attribution](https://support.google.com/displayvideo/answer/9188083) | — | **added** |
| `srsltid` | Google's product results (Merchant Center) | ClearURLs global | global | — |
| `fbclid` | Facebook and Instagram, on every outbound link | ClearURLs global | global | — |
| `fb_action_ids`, `fb_action_types` | Facebook's Open Graph shares | ClearURLs global | — | **added** |
| `igshid` | Instagram's share button (older) | Mozilla's list, `instagram` rule | `www.instagram.com` only | **added** (also `instagram.com`, and links that carry it elsewhere) |
| `igsh` | Instagram's share button (current) | seen on links copied from Instagram; [InstaFix #75](https://github.com/Wikidepia/InstaFix/issues/75) | — | **added** |
| `si` | YouTube's and Spotify's share buttons | LGPL list (`youtube`), Mozilla's list (`spotify`) | `youtube.com`, `youtu.be`, `open.spotify.com` | — |
| `msclkid` | Microsoft Advertising | ClearURLs global | global | — |
| `ttclid` | TikTok ads | ClearURLs global | global | — |
| `twclid` | X ads | ClearURLs global | global | — |
| `__twitter_impression` | X's embedded posts | ClearURLs global | — | **added** |
| `li_fat_id` | LinkedIn ads | ClearURLs global | global | — |
| `rdt_cid` | Reddit ads click ID | [Tealium, Reddit Conversions connector](https://docs.tealium.com/server-side-connectors/reddit-conversions-connector/) | — | **added** |
| `yclid` | Yandex ads | ClearURLs global | global | — |
| `mc_eid`, `mc_cid` | Mailchimp newsletters | ClearURLs global | global | — |
| `_hsenc`, `_hsmi`, `__hssc`, `__hstc`, `__hsfp` | HubSpot mail and pages | ClearURLs global | global | — |
| `oly_anon_id`, `oly_enc_id` | Omeda newsletters | ClearURLs global | — | **added** |
| `vero_id` | Vero newsletters (`vero_conv` is on the list already) | ClearURLs global | — | **added** |
| `wickedid` | Wicked Reports click tracking | ClearURLs global | — | **added** |
| `mtm_*` | Matomo campaign tags | ClearURLs global | global (each name) | — |
| `mkt_tok` | Marketo mail | [Marketo knowledge base](https://experienceleague.adobe.com/en/docs/experience-cloud-kcs/kbarticles/ka-28604) | — | **kept**: Marketo reads it to know who arrived, including on its unsubscribe page; removed on navigation, an unsubscribe link from a mail could stop working |
| `ml_subscriber`, `ml_subscriber_hash` | MailerLite mail | ClearURLs global | — | **kept**: the landing pages read them to know the subscriber (forms, preferences), the same risk as `mkt_tok` |
| `fb_source`, `fb_ref`, `cmpid`, `wtrid`, `itm_*` | Various | ClearURLs global | — | **kept**: plain names that sites also use for their own content, so stripping them everywhere could change a page |

## What is checked

- `tests/unit/test_clean_links.py`: the pref holds exactly the rows marked **added** above, and none of the **kept** ones.
- `tests/integration/test_clean_links.py`, on the Nulavio build: "Copy Clean Link to Highlight" on a local page whose address carries one of each added parameter and the page's own `id=7` drops all of them and keeps `id=7`; the same address opened directly still shows the same page.

## Not covered

- Parameters inside a redirect (`/url?q=` on Google's results, `l.facebook.com/l.php?u=`): those are a different feature (the address the link leads to), left to the engine and to uBlock Origin's `removeparam` filters (#95).
- Site rules for hosts the engine's rules miss (for example `instagram.com` without `www` for `ig_rid`): only the two Instagram share tokens are added, globally.
- The engine's lists change with each release and with Remote Settings. This table is re-read when one of the added names lands in the engine's own list; the pref is then shortened.
