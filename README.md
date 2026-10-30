# TikTok Email Scraper API

<p align="center">
  <a href="https://www.scrapingbee.com/">
    <img src="https://github.com/user-attachments/assets/bc1e3bbc-3de3-4400-9400-5c1feeac23d0" alt="tiktok-email-scraper-api" />
  </a>
</p>



[![checks](https://github.com/ScrapingBee/tiktok-email-scraper-api/workflows/checks/badge.svg)](https://github.com/ScrapingBee/tiktok-email-scraper-api/actions)
[![license](https://img.shields.io/github/license/ScrapingBee/tiktok-email-scraper-api.svg)](LICENSE)

A [TikTok email scraper](https://www.scrapingbee.com/scrapers/tiktok-email-scraper-api/) has one legitimate job: collecting the business address a creator typed into their public bio so that brands can reach them. This repo does that job through ScrapingBee for 1 credit per profile, and it starts with the rules, because an email list is the kind of dataset that gets people fined.

Tested on 2026-10-29 against 29 usernames. Results, including how few profiles had an address, are further down.

## The rules come first

**Collect only what creators publish for business.** A bio line such as `Contact for business: brooke@friendsinreality.com` is an invitation to send business mail. The code reads the bio text and, optionally, the one link a creator puts in their bio. Nothing else.

**Out of scope, on purpose:**

- the email tied to a TikTok account, which is not on the public profile page;
- anything visible only after signing in, including private accounts. ScrapingBee's terms prohibit scraping under login credentials, and its accounts can be suspended for it;
- guessing addresses from names, or checking guessed addresses against a mail server.

**GDPR, if any recipient is in the EU or UK.** An address like `nicolelaenoteam@gmail.com` identifies a person, so it is personal data even though it was public. You need a lawful basis to process it ([Article 6](https://gdpr-info.eu/art-6-gdpr/)); for outreach that is usually legitimate interests, which you must weigh against the creator's interests. Because the data did not come from the creator directly, [Article 14](https://gdpr-info.eu/art-14-gdpr/) requires you to tell them who you are, why you hold their address and where you got it, at the latest in your first message. Under [Article 21](https://gdpr-info.eu/art-21-gdpr/) they can object to direct marketing at any time, and then you stop.

**CAN-SPAM, for commercial email in the US.** The FTC's compliance guide applies it to all commercial messages, business to business included: accurate headers, a subject line that is not deceptive, a valid postal address, a clear way to opt out, and opt-outs honoured within 10 business days. The same guide lists harvesting email addresses among the aggravated violations that can add penalties.

In practice: store the source URL and the date next to every address, send one relevant message per creator, and keep a suppression list. None of this is legal advice.

## What a public profile page contains

`https://www.tiktok.com/@<username>` returns about 375 KB of server HTML when fetched with `render_js=false`. All the profile data sits in one script tag:

```html
<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">
```

Inside, `__DEFAULT_SCOPE__["webapp.user-detail"]` holds `statusCode`, `userInfo.user` and two stats objects. Trimmed, for @nicolelaeno:

```json
{
  "id": "16762122",
  "uniqueId": "nicolelaeno",
  "nickname": "nicole 𐙚",
  "signature": "currently sailing around the world...\n💌 nicolelaenoteam@gmail.com\nstay positive⋆˚🎀˚⋆",
  "verified": true,
  "privateAccount": false,
  "isOrganization": 0,
  "bioLink": {"link": "https://youtube.com/@nicolelaeno?si=S_oqLjWPQr8Z9Ud8", "risk": 0}
}
```

`signature` is the bio. `stats` gives rounded numbers and `statsV2` gives exact ones as strings:

```json
"stats":   {"followerCount": 5600000,   "heartCount": 330600000,   "videoCount": 1457}
"statsV2": {"followerCount": "5568301", "heartCount": "330649526", "videoCount": "1457"}
```

A username that does not resolve still returns the script, with no `userInfo` and a non-zero code: `{"statusCode": 209002, "statusMsg": "", "needFix": false}` for one handle in our list.

### The 1,462 byte page

Some requests return HTTP 200, cost 1 credit, and contain no profile at all:

```html
<body> Please wait... <p id="wci" class="_wafchallengeid"></p> ...
<script tpye="text/javascript" src="https://sf16-website-login.neutral.ttwstatic.com/obj/tiktok_web_login_static/obj/waf-aiso/dd9808.js"></script>
```

That is TikTok's challenge page. On the final run 7 of 36 profile requests got it, and asking again with the same classic proxy settled every one of them within three tries. On an earlier run two usernames failed three times in a row; the `--premium-fallback` flag adds one premium proxy attempt for that case, which cost 10 credits and returned the profile when we tried it. Because the challenge page is a normal 200, ScrapingBee bills it, so the retry decision has to come from the content, not the status code:

```python
def user_detail(html: str) -> dict | None:
    match = DATA_RE.search(html)        # the __UNIVERSAL_DATA_FOR_REHYDRATION__ script
    if not match:
        return None                     # challenge page: retry
    return json.loads(match.group(1))["__DEFAULT_SCOPE__"].get("webapp.user-detail")
```

## TikTok email finder by username, step by step

[`examples/tiktok_email_finder.py`](examples/tiktok_email_finder.py) is the full tool. The core loop:

```python
def fetch_creator(bee, username, waf_retries=3, premium_fallback=False):
    c = Creator(username=username.lstrip("@").strip())
    url = f"https://www.tiktok.com/@{c.username}"
    plan = [False] * waf_retries + ([True] if premium_fallback else [])
    for premium in plan:
        c.attempts += 1
        status, html, cost = bee.get(url, premium=premium)   # render_js=false, 5xx retried
        c.credits += cost
        detail = user_detail(html) if status == 200 else None
        if detail is None:
            c.status = "blocked" if status == 200 else f"error_{status}"
            continue
        fill_profile(c, detail)          # bio, bioLink, statsV2, verified, private
        return c
    return c
```

`fill_profile` runs the bio through the email extractor. With `--follow-links`, the script then opens the bio link with one more 1 credit request, unless it points at YouTube, Instagram, X, Facebook or TikTok itself.

Link pages hide the address in different places. Linktree keeps the email button inside its `__NEXT_DATA__` JSON, not in an `<a>` tag:

```json
"socialLinks":[{"type":"INSTAGRAM","url":"https://instagram.com/noahbeck","position":0}, ...
  {"type":"EMAIL_ADDRESS","url":"mailto:noahbeck@underscoretalent.com","position":6}, ...
```

hoo.be renders a plain link:

```html
<a href="mailto:alixearleteam@unitedtalent.com" target="_blank" rel="nofollow ugc noopene ...
```

So `emails_in_html()` looks for `mailto:` anywhere in the raw HTML, scripts included, before it scans the visible text. The first version only read `href="mailto:` and missed Noah Beck's address.

Run it:

```bash
export SCRAPINGBEE_API_KEY=...
python examples/tiktok_email_finder.py --file usernames.txt --follow-links --csv creators.csv --json creators.json
```

Duplicates are removed twice: usernames are lowercased and deduplicated before any request, and addresses are lowercased and deduplicated per creator and across bio and link. The CSV has one row per username with `status`, `followers`, `emails`, `email_source` (`bio` or `link`), `bio_link`, the bio with line breaks flattened, and the credits that row cost.

## The extraction regex, tested

[`examples/email_patterns.py`](examples/email_patterns.py) holds the pattern and 18 test cases taken from what bios actually look like:

```python
EMAIL_RE = re.compile(
    r"(?<![\w.+-])"
    r"([a-z0-9](?:[a-z0-9._%+-]{0,62}[a-z0-9_])?"
    r"@"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z]{2,24})"
    r"(?![\w-])",
    re.IGNORECASE,
)
```

Before matching, text goes through Unicode NFKC normalisation. That one call turns a full width `＠` into `@` and bold maths letters such as `𝐛𝐢𝐳` into `biz`, both of which show up in stylised bios (one profile we fetched used `𝕰𝖒𝖕𝖙𝖞` as its whole bio). Bracketed spellings, `[at]`, `(at)`, `[dot]`, are rewritten; a bare "at" is not, because "meet me at the studio at 5" is a sentence. Matches ending in an image or video extension (`logo@2x.png`) are dropped, and so are @mentions, which have no domain.

```
$ python examples/email_patterns.py --selftest
ok   '💌 nicolelaenoteam@gmail.com\nstay positive'       -> ['nicolelaenoteam@gmail.com']
ok   'Inquiries: simonfpvbookings@gmail.com.'           -> ['simonfpvbookings@gmail.com']
ok   'collabs ＠ brand: hello＠studio.co'                 -> ['hello@studio.co']
ok   'book me: jane [at] agency [dot] io'               -> ['jane@agency.io']
ok   'logo@2x.png and icon@3x.webp'                     -> []
ok   'follow @zachking and @duolingo'                   -> []
ok   'meet me at the studio at 5'                       -> []
ok   '<script>{"type":"EMAIL_ADDRESS","url":"mailto:'   -> ['noahbeck@underscoretalent.com']
...
18/18 passed
```

## How many profiles actually had an email

Two lists, both run with `--follow-links --premium-fallback`.

**List A: 20 large accounts picked by name**, before we knew anything about their bios:

```
@zachking               ok          86,779,124 followers  tries 1  -
@gordonramsayofficial   ok          40,672,157 followers  tries 1  guestrelations@gordonramsay.com
@noahbeck               ok          32,619,755 followers  tries 1  noahbeck@underscoretalent.com
@alixearle              ok           8,726,766 followers  tries 1  alixearleteam@unitedtalent.com
@cookingwithlynja       ok          22,164,115 followers  tries 1  cookingwithlynja@gmail.com
@nicolelaeno            ok           5,568,302 followers  tries 1  nicolelaenoteam@gmail.com
@jamescharles           ok          39,150,324 followers  tries 1  management@painted.co
@unboxtherapy           ok                  11 followers  tries 2  -
@brookemonk_            ok          49,117,114 followers  tries 1  brooke@friendsinreality.com
@willsmith              ok          77,934,734 followers  tries 2  -
...
20 usernames, 20 profiles read, 7 with a public email (5 in bio, 2 only via bio link), 7 distinct addresses, 38 credits
```

**List B: 9 handles from a Google search** for `site:tiktok.com "business inquiries" "@gmail.com"` (one call to ScrapingBee's [Google API](https://www.scrapingbee.com/documentation/google-api/), 10 credits). This list is biased toward bios with an address, which is the point: it shows what a targeted list yields.

```
@kennedyavitia          ok              26,039 followers  tries 1  kennyavitia@gmail.com
@unstoppablestacy       ok              30,565 followers  tries 1  unstoppablebystacy@gmail.com
@shayna1lee             ok               9,146 followers  tries 1  shaynaleebusiness@gmail.com
@simonfruehwirth        ok             212,876 followers  tries 1  simonfpvbookings@gmail.com
@rrfashion.style        not_found            ? followers  tries 1  -
...
9 usernames, 8 profiles read, 6 with a public email (6 in bio, 0 only via bio link), 7 distinct addresses, 13 credits
```

| | List A (by name) | List B (search targeted) |
|---|---|---|
| Profiles read | 20 of 20 | 8 of 9 |
| Email in the bio | 5 | 6 |
| Email only behind the bio link | 2 | 0 |
| No public email | 13 | 2 |

Read those numbers with three caveats:

- **Big accounts rarely publish one.** 13 of the 20 large accounts had no address anywhere public. MrBeast, Khaby Lame, Charli D'Amelio, Zach King and the brand accounts (Duolingo, NASA) all came back empty.
- **A bio link can lead to the wrong inbox.** Gordon Ramsay's bio links to his website, and the only address on that page was `guestrelations@gordonramsay.com`. It is public, but it is a restaurant guest desk, not a partnership contact. Check `email_source=link` rows by hand.
- **A username is not an identity.** `@unboxtherapy` resolved to an account with 11 followers, not the tech channel. Check follower counts and `verified` before trusting a match.

## Node.js version

[`examples/tiktok_bio_emails.js`](examples/tiktok_bio_emails.js) ports the fetch, the challenge page check and the same regex to Node 18+, and prints one JSON line per username:

```bash
node examples/tiktok_bio_emails.js nicolelaeno simonfruehwirth mrbeast
```

```
{"username":"nicolelaeno","status":"ok","followers":5568565,"emails":["nicolelaenoteam@gmail.com"],"credits":1,"attempts":1,"nickname":"nicole 𐙚","bioLink":"https://youtube.com/@nicolelaeno?si=S_oqLjWPQr8Z9Ud8"}
{"username":"simonfruehwirth","status":"ok","followers":212876,"emails":["simonfpvbookings@gmail.com"],"credits":1,"attempts":1,"nickname":"Simon.Frwt","bioLink":"https://stan.store/SimonFPVBookings"}
{"username":"mrbeast","status":"ok","followers":145136654,"emails":[],"credits":1,"attempts":1,"nickname":"MrBeast","bioLink":"http://themostdangerousgames.com"}
credits used: 3
```

## Credit cost

| Request | Credits |
|---|---|
| Profile, classic proxy, `render_js=false` | 1 |
| Challenge page (billed, then retried) | 1 each |
| Profile through premium proxy (`--premium-fallback`) | 10 |
| Bio link page | 1 |
| Google search for discovery | 10 |

The two lists above cost 51 credits for 29 usernames, retries and link pages included. New accounts get 1,000 free credits, and plan sizes are on the [pricing page](https://www.scrapingbee.com/pricing/). Leaving `render_js` at its default switches the headless browser on and multiplies the profile cost by five for no extra data.

## Related ScrapingBee pages

[TikTok scraper API](https://www.scrapingbee.com/scrapers/tiktok-api/), [TikTok search API](https://www.scrapingbee.com/scrapers/tiktok-search-api/), [TikTok follower scraper](https://www.scrapingbee.com/scrapers/tiktok-follower/), [YouTube email scraper](https://www.scrapingbee.com/scrapers/youtube-email-scraper-api/), [Linktree profile details](https://www.scrapingbee.com/scrapers/linktree-profile-details-api/), [contact info scraper](https://www.scrapingbee.com/scrapers/contact-info-api/).

Docs: [HTML API parameters](https://www.scrapingbee.com/documentation/), [data extraction rules](https://www.scrapingbee.com/documentation/data-extraction/), [AI web scraping](https://www.scrapingbee.com/features/ai-web-scraping-api/).

## FAQ

**Is it legal to scrape emails from TikTok?**
Reading a business address a creator published is a different act from harvesting addresses in bulk, and what you do next matters most. In the EU and UK the GDPR applies to the address; in the US, CAN-SPAM applies to commercial mail. This repo keeps to public bios and is not legal advice.

**How does a TikTok email finder by username work?**
It fetches `tiktok.com/@username`, reads the `signature` field from the page's rehydration JSON, and runs an email pattern over it. With ScrapingBee that is 1 credit per profile.

**Can I get the email a TikTok account was registered with?**
No. It is not on the public profile page, and nothing in this repo tries to obtain it.

**Why does my TikTok email scraper return empty profiles?**
TikTok sometimes answers with a 1,462 byte "Please wait..." page instead of the profile. Check for the `__UNIVERSAL_DATA_FOR_REHYDRATION__` script and retry when it is missing.

**What share of TikTok creators list an email?**
In our test, 7 of 20 large accounts and 6 of 8 accounts found through a targeted search. Your niche will differ.

## License

MIT. See [LICENSE](LICENSE).
