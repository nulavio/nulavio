# Search providers Nulavio offers by name

Status: list reviewed on 2026-11-16 for #151. The providers are defined in `PROVIDERS` in
[`NulavioSearch.sys.mjs`](../../browser/shell/modules/NulavioSearch.sys.mjs); the rules are in
[ADR 0002](../adr/0002-nulavio-search.md).

Nulavio has no partnership with any search provider and receives nothing from them. Settings list the providers by
name, in alphabetical order, with none marked. Which one a new profile starts with is ADR 0002's decision (DuckDuckGo)
and did not change here.

## What a provider needs to be on the list

1. Search works without an account, or the list says that it needs one (today only Kagi).
2. The provider publishes its own OpenSearch description, and the addresses Nulavio uses come from it, over `https`.
3. Its suggestions address, if it has one, is in the same description, so the host that receives typed text (only
   after the person turns suggestions on for it) is the provider's own declared one.
4. It is a general web search in pt-BR and en-US. Whose index it uses is written down, not judged.

## The list

| Provider | Offered | Account | Search address (from its OpenSearch description) | Suggestions host | Checked |
|---|---|---|---|---|---|
| Brave Search | first run | no (an optional paid plan exists, not handled) | `https://search.brave.com/search?q={searchTerms}` | `search.brave.com` | 2026-10-25, again 2026-11-16 |
| DuckDuckGo | first run, the default | no | `https://duckduckgo.com/?q={searchTerms}` | `duckduckgo.com` | 2026-10-25 |
| Ecosia | on request | no | `https://www.ecosia.org/search?q={searchTerms}` | `ac.ecosia.org` | 2026-11-16 |
| Kagi | on request | **yes**, paid | `https://kagi.com/search?q={searchTerms}` | `kagisuggest.com` | 2026-10-25 |
| Mojeek | first run | no | `https://www.mojeek.com/search?q={searchTerms}` | none | 2026-10-25, again 2026-11-16 |
| Qwant | on request | no | `https://www.qwant.com/?q={searchTerms}` | `api.qwant.com` | 2026-11-16 |
| Startpage | on request | no | `https://www.startpage.com/sp/search?query={searchTerms}` | `www.startpage.com` | 2026-11-16 |

Plus, as before: a SearXNG instance at an address the person types (Nulavio never picks a public one), a custom
address, and a site's own OpenSearch description.

Where the descriptions were read on 2026-11-16: `https://www.ecosia.org/opensearch.xml`,
`https://www.qwant.com/opensearch.xml`, `https://www.startpage.com/sp/cdn/opensearch/en/opensearch.xml`,
`https://search.brave.com/opensearch.xml`, `https://www.mojeek.com/opensearch.xml`. On the search address Nulavio
leaves out the parameters that only say the search came from an OpenSearch client or an English page
(`addon=opensearch` on Ecosia's, `client=opensearch` on Qwant's, `cat=web&pl=opensearch&language=english` on
Startpage's); the suggestion addresses are kept as the descriptions give them, since their parameters choose the
answer's format. Whether a search without them gives the same results was not compared.

Not verified here: each provider's privacy policy. The pages of Ecosia (HTTP 403), Qwant (not served to this
machine's country) and Startpage (refused to an automated client) could not be read on 2026-11-16, so this list says
nothing about how they treat searches. That is for a person to read before recommending any of them.

## Accounts

A provider with accounts says in Settings whether the profile is signed in. Nulavio reads only whether the
provider's session cookie is present in the profile's normal cookie jar, by its name, never its value, and sends
nothing.

| Provider | Session cookie | Sign-in page | Source |
|---|---|---|---|
| Kagi | `kagi_session` | `https://kagi.com/signin` | [Kagi's cookie list](https://help.kagi.com/kagi/privacy/cookies.html) ("Session identifier, which should never be shared"), read 2026-11-16; the sign-in link is the one on `kagi.com/welcome` |

A sign-in is kept by the profile like any other site's cookies: it survives a restart, in an encrypted profile too
while it is unlocked, and a temporary profile forgets it when it closes. Private windows never have it; what Nulavio
offers there is #152.
