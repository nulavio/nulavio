# Web services on a click: translation and summaries

Status: implemented 2026-11-16 (#156, #154). The module is
[`NulavioServices.sys.mjs`](../../browser/shell/modules/NulavioServices.sys.mjs); the maintainer's decisions are on #156
(the preset list) and #154 (on-device summaries stay off for 1.0, under D-UX7).

## What the person gets

- **Translation stays on the device by default.** The engine's own translation is unchanged: it runs on the
  computer, after downloading its models once per pair of languages ([connections](../security/new-profile-connections.md#on-use-translation-and-web-services)).
- **Web translation services** are listed in Settings › Idiomas, after the engine's own group, by name in alphabetical
  order, none added: DeepL, Google Translate, Kagi Translate, a LibreTranslate instance the person types (Nulavio never
  picks a public one, the rule of SearXNG), or the address of any other service. Once added, the page menu offers
  "Traduzir seleção com …" and, for a service that translates pages, "Traduzir página com …". The target language follows
  the browser's, and Settings can change it.
- **Summaries** are off until the person chooses one service in Settings › Assistente e IA: Nulavio's assistant
  (ADR 0007), Kagi Universal Summarizer, or the address of another service. Then "Resumir página com …" is in the page
  menu and, for a web service, "Resumir o link com …" in the link menu.
- Services' own extensions (DeepL's, Kagi's) are not bundled. Settings says they can be installed from addons.mozilla.org.

## What leaves the browser, and when

Nothing until the click on an item that names the service. Then:

| Service | Receives | How |
|---|---|---|
| A translation service, on a selection | The selected text (cut at 5,000 characters) and the target language | In the address of a new tab. DeepL and LibreTranslate put the text in the fragment (after `#`), which the browser does not send in the request; their page reads it there |
| A translation service, on a page | The page's address without its fragment (the part after `#`, which never goes to the page's own server and may hold a key or a token), and the target language | In the address of a new tab; the service then fetches the page itself |
| A summary service on the web | The page's or the link's address, without its fragment | In the address of a new tab; the service fetches the page. The page's text is not sent |
| Nulavio's assistant | The page's text, as an item in the assistant's panel, with the question "Resuma esta página." written | Nothing is sent until the person presses Send, and then only to the agent they connected, under its permissions |

A service that fetches an address is never offered one it should not fetch: not an address on this computer
(`localhost`, loopback), a private, shared, link-local, documentation, benchmarking or reserved address, an IPv6 address
that carries an IPv4 one (mapped, compatible, NAT64, 6to4), a `.local`, `.internal`, `.lan` or
`.home.arpa` name, a host without a dot (an intranet name), an address with a user name, or anything that is not an
`http(s)` page. The menu item stays, unusable, and says why. Private windows show none of these items unless the person
ticks "Oferecer estes serviços e os resumos também nas janelas privadas"; then the service opens in a private tab.
The assistant is never offered in a private window, whatever that box says (ADR 0007).

What is left, written as residual risk R80: a page's address can still carry a secret in its query (a token a site
put there), and a web service then receives it on the click; the person chose that service and that click.

## The addresses, and where they come from

All of them are in `SERVICES` in the module, in one place. A service the person adds is a template validated like a
search template: `https://` only, a host that is not built from the page, no user name or password, and only the
placeholders that kind of service takes (`{text}` or `{url}`, and `{lang}`).

| Service | Selection | Page | Read on 2026-11-16 from |
|---|---|---|---|
| DeepL | `https://www.deepl.com/translator#xx/{lang}/{text}` | — | Kagi's public bang list ([kagisearch/bangs](https://github.com/kagisearch/bangs) at `af28e0bd`, `!deepl`); `xx` is DeepL's "detect" |
| Google Translate | `https://translate.google.com/?sl=auto&tl={lang}&text={text}&op=translate` | `https://translate.google.com/translate?sl=auto&tl={lang}&u={url}` | Google's own address form |
| Kagi Translate | `https://translate.kagi.com/?from=auto&to={lang}&text={text}` | `https://translate.kagi.com/<address without scheme>?to={lang}` | [Kagi's URL parameters page](https://help.kagi.com/kagi/translate/url-parameters.html) and the `!kt` bang |
| LibreTranslate | `<instance>?source=auto&target={lang}#q={text}` | — | Its web page's code, `libretranslate/templates/app.js.template` on `main` |
| Kagi Universal Summarizer | — | `https://kagi.com/summarizer?url={url}` | The `!sum` bang |

Not verified: that each service shows the text or the page as expected once opened. The tests check the address each
item opens and that nothing is sent before the click; they cancel every request to the services. Kagi's services need
an account and were not opened signed in. How Kagi Translate reads a page address that has its own `?` or `#` (Nulavio
encodes them so they stay in the path) is not documented by Kagi.
