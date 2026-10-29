"""Find the business email a TikTok creator published in their public bio.

For each username the script fetches https://www.tiktok.com/@<username>
through ScrapingBee (classic proxy, no JavaScript, 1 credit), reads the
`webapp.user-detail` object from the `__UNIVERSAL_DATA_FOR_REHYDRATION__`
script, and runs the bio text through `email_patterns.find_emails`.
With --follow-links it also opens the profile's bio link (Linktree, hoo.be
and similar pages) and reads mailto: links and visible text there.

Only what the creator chose to print on a public page is read. The email
tied to an account, and anything shown only after signing in, is out of
scope and is not attempted.

    export SCRAPINGBEE_API_KEY=...
    python tiktok_email_finder.py nicolelaeno cookingwithlynja noahbeck --follow-links
    python tiktok_email_finder.py --file usernames.txt --csv creators.csv --json creators.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

import requests

from email_patterns import emails_in_html, find_emails

API_URL = "https://app.scrapingbee.com/api/v1/"
DATA_RE = re.compile(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S)

# Bio links that point at other platforms are skipped: they are either
# sign in walled or covered by their own scrapers.
SKIP_LINK_HOSTS = ("youtube.com", "youtu.be", "instagram.com", "tiktok.com", "x.com", "twitter.com", "facebook.com")


@dataclass
class Creator:
    username: str
    status: str = "pending"            # ok | not_found | blocked | error
    tiktok_status_code: int | None = None
    nickname: str = ""
    user_id: str = ""
    verified: bool = False
    private: bool = False
    organization: bool = False
    followers: int | None = None
    videos: int | None = None
    likes: int | None = None
    bio: str = ""
    bio_link: str = ""
    emails_bio: list[str] = field(default_factory=list)
    emails_link: list[str] = field(default_factory=list)
    attempts: int = 0
    credits: int = 0

    @property
    def emails(self) -> list[str]:
        return list(dict.fromkeys(self.emails_bio + self.emails_link))


class ScrapingBee:
    def __init__(self, api_key: str | None = None, timeout: int = 60):
        key = api_key or os.environ.get("SCRAPINGBEE_API_KEY")
        if not key:
            raise SystemExit("Set SCRAPINGBEE_API_KEY first.")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {key}"
        self.timeout = timeout
        self.credits = 0

    def get(self, url: str, premium: bool = False, tries: int = 3) -> tuple[int, str, int]:
        """Return (status, body, credits). 5xx from ScrapingBee is retried, it is not billed."""
        params = {"url": url, "render_js": "false"}
        if premium:
            params["premium_proxy"] = "true"
        for attempt in range(1, tries + 1):
            try:
                resp = self.session.get(API_URL, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt == tries:
                    raise
                time.sleep(2 * attempt)
                continue
            if resp.status_code >= 500 and attempt < tries:
                time.sleep(2 * attempt)
                continue
            cost = int(resp.headers.get("spb-cost", 0) or 0)
            self.credits += cost
            return resp.status_code, resp.text, cost
        return 0, "", 0


def user_detail(html: str) -> dict | None:
    """The user-detail scope, or None when TikTok served its WAF page instead."""
    match = DATA_RE.search(html)
    if not match:
        return None
    scope = json.loads(match.group(1)).get("__DEFAULT_SCOPE__", {})
    return scope.get("webapp.user-detail")


def _int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fill_profile(c: Creator, detail: dict) -> None:
    c.tiktok_status_code = detail.get("statusCode")
    info = detail.get("userInfo") or {}
    user = info.get("user")
    if not user:
        c.status = "not_found"
        return
    # statsV2 carries exact counts as strings; stats is rounded
    stats = info.get("statsV2") or info.get("stats") or {}
    c.status = "ok"
    c.nickname = user.get("nickname", "")
    c.user_id = str(user.get("id", ""))
    c.verified = bool(user.get("verified"))
    c.private = bool(user.get("privateAccount"))
    c.organization = bool(user.get("isOrganization"))
    c.followers = _int(stats.get("followerCount"))
    c.videos = _int(stats.get("videoCount"))
    c.likes = _int(stats.get("heartCount"))
    c.bio = user.get("signature", "")
    c.bio_link = (user.get("bioLink") or {}).get("link", "")
    c.emails_bio = find_emails(c.bio)


def fetch_creator(bee: ScrapingBee, username: str, waf_retries: int = 3, premium_fallback: bool = False) -> Creator:
    c = Creator(username=username.lstrip("@").strip())
    url = f"https://www.tiktok.com/@{c.username}"
    plan = [False] * waf_retries + ([True] if premium_fallback else [])
    for premium in plan:
        c.attempts += 1
        status, html, cost = bee.get(url, premium=premium)
        c.credits += cost
        if status != 200:
            c.status = f"error_{status}"
            continue
        detail = user_detail(html)
        if detail is None:
            # about 1.5 KB "Please wait..." challenge page, billed as a normal 200
            c.status = "blocked"
            continue
        fill_profile(c, detail)
        return c
    return c


def follow_bio_link(bee: ScrapingBee, c: Creator) -> None:
    link = c.bio_link
    if not link:
        return
    if not link.startswith("http"):
        link = "https://" + link
    host = urlparse(link).netloc.lower()
    if any(host == h or host.endswith("." + h) for h in SKIP_LINK_HOSTS):
        return
    status, html, cost = bee.get(link)
    c.credits += cost
    if status == 200:
        c.emails_link = [e for e in emails_in_html(html) if e not in c.emails_bio]


def write_outputs(rows: list[Creator], csv_path: str | None, json_path: str | None) -> None:
    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            fields = ["username", "status", "nickname", "verified", "private", "followers", "videos",
                      "emails", "email_source", "bio_link", "bio", "credits"]
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for c in rows:
                source = "bio" if c.emails_bio else ("link" if c.emails_link else "")
                w.writerow({
                    "username": c.username, "status": c.status, "nickname": c.nickname,
                    "verified": c.verified, "private": c.private, "followers": c.followers,
                    "videos": c.videos, "emails": ";".join(c.emails), "email_source": source,
                    "bio_link": c.bio_link, "bio": c.bio.replace("\n", " / "), "credits": c.credits,
                })
    if json_path:
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump([{**asdict(c), "emails": c.emails} for c in rows], fh, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="TikTok email finder by username (public bios only)")
    ap.add_argument("usernames", nargs="*")
    ap.add_argument("--file", help="text file, one username per line")
    ap.add_argument("--follow-links", action="store_true", help="also read the bio link page (+1 credit)")
    ap.add_argument("--premium-fallback", action="store_true", help="try premium proxy (10 credits) after classic retries")
    ap.add_argument("--csv")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    names = list(args.usernames)
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            names += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    names = list(dict.fromkeys(n.lstrip("@").lower() for n in names))  # dedupe input
    if not names:
        ap.error("give usernames or --file")

    bee = ScrapingBee()
    rows: list[Creator] = []
    for name in names:
        c = fetch_creator(bee, name, premium_fallback=args.premium_fallback)
        if args.follow_links and c.status == "ok":
            follow_bio_link(bee, c)
        rows.append(c)
        found = ", ".join(c.emails) or "-"
        followers = f"{c.followers:,}" if c.followers is not None else "?"
        print(f"@{c.username:<22} {c.status:<9} {followers:>12} followers  tries {c.attempts}  {found}")

    ok = [c for c in rows if c.status == "ok"]
    with_email = [c for c in ok if c.emails]
    unique = {e for c in with_email for e in c.emails}
    print(f"\n{len(rows)} usernames, {len(ok)} profiles read, {len(with_email)} with a public email "
          f"({sum(1 for c in ok if c.emails_bio)} in bio, {sum(1 for c in ok if c.emails_link and not c.emails_bio)} only via bio link), "
          f"{len(unique)} distinct addresses, {bee.credits} credits")
    write_outputs(rows, args.csv, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
