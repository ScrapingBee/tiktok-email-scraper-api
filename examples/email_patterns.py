"""Email extraction for short, messy profile text, with its own tests.

TikTok bios are not clean prose. They mix emoji, line breaks, stylised
Unicode letters and "at"/"dot" spelling. This module turns that text into
a list of lowercase addresses and runs its test cases with:

    python email_patterns.py --selftest

Design choices, each covered by a test below:
  * NFKC normalisation first, so a full width "＠" and maths style letters
    such as "𝐦𝐚𝐢𝐥" read as plain ASCII.
  * Bracketed obfuscation only: "name [at] host [dot] com" and "(at)".
    Bare " at " is left alone, it appears in normal sentences.
  * Asset names that look like emails ("logo@2x.png") are rejected by
    top level domain.
  * Trailing punctuation is never part of the address.
"""

from __future__ import annotations

import re
import sys
import unicodedata

EMAIL_RE = re.compile(
    r"(?<![\w.+-])"                                   # not glued to a previous token
    r"([a-z0-9](?:[a-z0-9._%+-]{0,62}[a-z0-9_])?"     # local part
    r"@"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"    # domain labels
    r"[a-z]{2,24})"                                   # top level domain
    r"(?![\w-])",
    re.IGNORECASE,
)

OBFUSCATED = [
    (re.compile(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", re.I), "@"),
    (re.compile(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", re.I), "."),
]

NOT_A_TLD = {"png", "jpg", "jpeg", "gif", "webp", "svg", "js", "css", "mp4", "mov", "heic"}

# Anywhere in the raw HTML, including JSON inside scripts: Linktree keeps
# its email button in __NEXT_DATA__ as {"type":"EMAIL_ADDRESS","url":"mailto:..."}
MAILTO_RE = re.compile(r"mailto:([^\"'?\\<>\s]+)", re.I)


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    for pattern, repl in OBFUSCATED:
        text = pattern.sub(repl, text)
    return text


def find_emails(text: str) -> list[str]:
    """Distinct lowercase addresses in order of first appearance."""
    seen: dict[str, None] = {}
    for match in EMAIL_RE.finditer(normalise(text)):
        email = match.group(1).lower().strip(".")
        if email.rsplit(".", 1)[-1] in NOT_A_TLD:
            continue
        seen.setdefault(email, None)
    return list(seen)


def emails_in_html(html: str) -> list[str]:
    """mailto: targets first (markup or embedded JSON), then visible text."""
    found = [m.lower() for m in MAILTO_RE.findall(html)]
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    for email in find_emails(text):
        if email not in found:
            found.append(email)
    return [e for e in found if find_emails(e) == [e]]


CASES = [
    # (input, expected)
    ("💌 nicolelaenoteam@gmail.com\nstay positive", ["nicolelaenoteam@gmail.com"]),
    ("Cookingwithlynja@gmail.com\n\n👇Lynja's Salts", ["cookingwithlynja@gmail.com"]),
    ("📧 mamamadeit3llc@gmail.com", ["mamamadeit3llc@gmail.com"]),
    ("Founder of \n@reale actives \nalixearleteam@unitedtalent.com", ["alixearleteam@unitedtalent.com"]),
    ("Inquiries: simonfpvbookings@gmail.com.", ["simonfpvbookings@gmail.com"]),
    ("collabs ＠ brand: hello＠studio.co", ["hello@studio.co"]),
    ("𝐛𝐢𝐳@𝐞𝐱𝐚𝐦𝐩𝐥𝐞.𝐜𝐨𝐦", ["biz@example.com"]),
    ("book me: jane [at] agency [dot] io", ["jane@agency.io"]),
    ("mgmt (at) talent.co.uk", ["mgmt@talent.co.uk"]),
    ("logo@2x.png and icon@3x.webp", []),
    ("follow @zachking and @duolingo", []),
    ("meet me at the studio at 5", []),
    ("a@b.c", []),
    ("first.last+tiktok@sub.domain.com, FIRST.LAST+tiktok@SUB.DOMAIN.COM", ["first.last+tiktok@sub.domain.com"]),
    ("(pr@brand.com)", ["pr@brand.com"]),
    ("email:brand-deals@my-agency.net!", ["brand-deals@my-agency.net"]),
]


def selftest() -> int:
    failed = 0
    for text, expected in CASES:
        got = find_emails(text)
        ok = got == expected
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {text[:46]!r:<50} -> {got}")
    html_cases = [
        ('<a href="mailto:alixearleteam@unitedtalent.com">Email</a><p>x@y.png</p>', ["alixearleteam@unitedtalent.com"]),
        ('<script>{"type":"EMAIL_ADDRESS","url":"mailto:noahbeck@underscoretalent.com"}</script>', ["noahbeck@underscoretalent.com"]),
    ]
    for html, expected in html_cases:
        got = emails_in_html(html)
        ok = got == expected
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {html[:46]!r:<50} -> {got}")
    total = len(CASES) + len(html_cases)
    print(f"{total - failed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    print(find_emails(sys.stdin.read()))
