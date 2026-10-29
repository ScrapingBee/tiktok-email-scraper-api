// TikTok bio email check in Node 18+ (global fetch, no dependencies).
// Reads public profiles only and prints one JSON line per username.
//
//   export SCRAPINGBEE_API_KEY=...
//   node tiktok_bio_emails.js nicolelaeno simonfruehwirth mrbeast

const API = "https://app.scrapingbee.com/api/v1/";
const KEY = process.env.SCRAPINGBEE_API_KEY;

// Same rules as email_patterns.py: NFKC first, bracketed [at]/[dot] only,
// reject asset names such as logo@2x.png.
const EMAIL_RE = /(?<![\w.+-])([a-z0-9](?:[a-z0-9._%+-]{0,62}[a-z0-9_])?@(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})(?![\w-])/gi;
const NOT_A_TLD = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg", "js", "css", "mp4", "mov", "heic"]);

function findEmails(text) {
  const norm = (text || "")
    .normalize("NFKC")
    .replace(/\s*[\[({]\s*at\s*[\])}]\s*/gi, "@")
    .replace(/\s*[\[({]\s*dot\s*[\])}]\s*/gi, ".");
  const out = [];
  for (const m of norm.matchAll(EMAIL_RE)) {
    const email = m[1].toLowerCase();
    if (!NOT_A_TLD.has(email.split(".").pop()) && !out.includes(email)) out.push(email);
  }
  return out;
}

async function scrape(url) {
  const qs = new URLSearchParams({ url, render_js: "false" });
  for (let i = 1; i <= 3; i++) {
    const res = await fetch(`${API}?${qs}`, { headers: { Authorization: `Bearer ${KEY}` } });
    if (res.status >= 500 && i < 3) continue; // not billed, try again
    return { status: res.status, html: await res.text(), cost: Number(res.headers.get("spb-cost") || 0) };
  }
}

function userDetail(html) {
  const m = html.match(/<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>([\s\S]*?)<\/script>/);
  if (!m) return null; // TikTok's "Please wait..." challenge page
  return JSON.parse(m[1]).__DEFAULT_SCOPE__?.["webapp.user-detail"] ?? {};
}

async function check(username, tries = 3) {
  const row = { username, status: "blocked", followers: null, emails: [], credits: 0, attempts: 0 };
  for (let i = 0; i < tries; i++) {
    row.attempts++;
    const { status, html, cost } = await scrape(`https://www.tiktok.com/@${username}`);
    row.credits += cost;
    if (status !== 200) { row.status = `error_${status}`; continue; }
    const detail = userDetail(html);
    if (!detail) continue;
    const user = detail.userInfo?.user;
    if (!user) return { ...row, status: "not_found", tiktokStatusCode: detail.statusCode };
    const stats = detail.userInfo.statsV2 || detail.userInfo.stats || {};
    return {
      ...row,
      status: "ok",
      nickname: user.nickname,
      followers: Number(stats.followerCount),
      bioLink: user.bioLink?.link || null,
      emails: findEmails(user.signature),
    };
  }
  return row;
}

async function main() {
  const names = process.argv.slice(2).map((n) => n.replace(/^@/, "").toLowerCase());
  if (!KEY || names.length === 0) {
    console.error("usage: SCRAPINGBEE_API_KEY=... node tiktok_bio_emails.js <username> [...]");
    process.exit(1);
  }
  let total = 0;
  for (const name of [...new Set(names)]) {
    const row = await check(name);
    total += row.credits;
    console.log(JSON.stringify(row));
  }
  console.error(`credits used: ${total}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
