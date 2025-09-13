#!/usr/bin/env python3
import json, os, sys, urllib.request, urllib.error, datetime

# ---------- Config (all optional except BRANCH & repo context) ----------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")       # optional
ASSISTANT_ID   = os.getenv("ASSISTANT_ID")         # optional
THREAD_ID      = os.getenv("THREAD_ID")            # optional
BRANCH         = os.getenv("BRANCH", "Strategy_4_1")

# GitHub issue posting (optional)
GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN")         # auto-provided in Actions
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com")
GITHUB_REPO    = os.getenv("GITHUB_REPOSITORY")    # e.g. "owner/repo"
ISSUE_NUMBER   = os.getenv("ISSUE_NUMBER")         # optional: post comment to this issue
ISSUE_TITLE    = os.getenv("ISSUE_TITLE", "Watchlist Digest — Latest")  # optional: create/find by title
ISSUE_LABELS   = [s.strip() for s in os.getenv("ISSUE_LABELS", "digest,automation").split(",") if s.strip()]

POST_TO_OPENAI = all([OPENAI_API_KEY, ASSISTANT_ID, THREAD_ID])
POST_TO_ISSUE  = bool(GITHUB_TOKEN and GITHUB_REPO and (ISSUE_NUMBER or ISSUE_TITLE))

# ---------- Data sources (month auto-rolls) ----------
month = datetime.datetime.utcnow().strftime("%Y-%m")
base  = f"https://cdn.jsdelivr.net/gh/vaibhavrajebhosale/us-swing-trade-management@{BRANCH}/snapshots/{month}/latest"

tabs = {
    "EntryWatchlist":   f"{base}/EntryWatchlist.json",
    "OversoldTracker":  f"{base}/OversoldTracker.json",
    "ExitMonitor":      f"{base}/ExitMonitor.json",
    "RiskMonitor":      f"{base}/RiskMonitor.json",
    "EarningsMonitor":  f"{base}/EarningsMonitor.json",
}

# ---------- Helpers ----------
def fetch_rows(url: str):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data.get("rows", []), data
    except Exception as e:
        print(f"[warn] fetch failed {url}: {e}", file=sys.stderr)
        return [], None

def slurp():
    out = {}
    meta = {}
    for k, v in tabs.items():
        rows, raw = fetch_rows(v)
        out[k] = rows
        meta[k] = raw or {}
    return out, meta

def pick(labels, key, n=8):
    vals = []
    for r in labels:
        v = str(r.get(key, "")).strip()
        if v:
            vals.append(v)
        if len(vals) >= n:
            break
    return ", ".join(vals) if vals else "—"

def upcoming_14d(rows):
    out = []
    now = datetime.datetime.utcnow().date()
    for r in rows:
        dt_str = r.get("EarningsDate") or r.get("NextEarnings") or r.get("EarningsDateISO") or r.get("Next ER (ISO)") or ""
        tick = r.get("Ticker") or r.get("Symbol") or ""
        if not tick or not dt_str:
            continue
        try:
            d = datetime.datetime.fromisoformat(dt_str.replace("Z","")).date()
            days = (d - now).days
            if 0 <= days <= 14:
                out.append(f"{tick} ({days}d)")
        except Exception:
            continue
    return ", ".join(out) if out else "—"

def staleness(meta):
    # If JSON includes "asOf" or similar, surface it; else show month alias
    hints = []
    for tab, raw in meta.items():
        asof = ""
        if isinstance(raw, dict):
            asof = raw.get("asOf") or raw.get("AsOf") or raw.get("timestamp") or ""
        if asof:
            hints.append(f"{tab}: {asof}")
    return "; ".join(hints) if hints else f"Using monthly alias {month}/latest/ (ensure snapshot is current)."

def build_digest(d, meta):
    ew = d.get("EntryWatchlist", [])
    ot = d.get("OversoldTracker", [])
    ex = d.get("ExitMonitor", [])
    rm = d.get("RiskMonitor", [])
    em = d.get("EarningsMonitor", [])

    buy       = pick(ew, "Ticker", 8)
    oversold  = pick(ot, "Ticker", 8)
    exits     = pick(ex, "Ticker", 12)

    risk_notes = []
    for r in rm[:8]:
        note = r.get("Note") or r.get("Notes") or r.get("RiskNote") or ""
        if note:
            risk_notes.append(note)
    risk_str = "; ".join(risk_notes) if risk_notes else "—"

    earn_14 = upcoming_14d(em)
    stale   = staleness(meta)

    # Plain-text digest
    lines = [
        f"Watchlist Digest — {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%MZ')}",
        "",
        "1) Buy Candidates",
        f"   {buy}",
        "",
        "2) Oversold but Not Ready",
        f"   {oversold}",
        "",
        "3) Exits",
        f"   {exits}",
        "",
        "4) Risk & Quotas",
        f"   {risk_str}",
        "",
        "5) Upcoming Earnings (next 14 days)",
        f"   {earn_14}",
        "",
        "Staleness",
        f"   {stale}",
    ]
    return "\n".join(lines)

def openai_post(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def gh_request(method, path, payload=None):
    if not (GITHUB_TOKEN and GITHUB_REPO):
        raise RuntimeError("Missing GITHUB_TOKEN or GITHUB_REPOSITORY")
    url = f"{GITHUB_API_URL}/repos/{GITHUB_REPO}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def ensure_issue_by_title(title, labels):
    # Look for open issue with this exact title; if none, create
    items = gh_request("GET", f"/issues?state=open&per_page=100")
    for it in items:
        if it.get("title") == title:
            return it["number"], it.get("html_url")
    body = "Created by automation to collect daily digests."
    created = gh_request("POST", "/issues", {"title": title, "body": body, "labels": labels})
    return created["number"], created.get("html_url")

def post_comment(issue_number, body):
    return gh_request("POST", f"/issues/{issue_number}/comments", {"body": body})

# ---------- Main ----------
def main():
    data, meta = slurp()
    digest = build_digest(data, meta)

    # 1) Optional: Post to OpenAI thread
    if POST_TO_OPENAI:
        try:
            _ = openai_post(f"https://api.openai.com/v1/threads/{THREAD_ID}/messages", {"role": "user", "content": digest})
            run = openai_post(f"https://api.openai.com/v1/threads/{THREAD_ID}/runs", {"assistant_id": ASSISTANT_ID})
            print(f"[ok] posted to OpenAI thread {THREAD_ID} run {run.get('id','?')}")
        except Exception as e:
            print(f"[warn] OpenAI post failed: {e}", file=sys.stderr)
    else:
        print("[info] OPENAI vars missing; skipping OpenAI post.", file=sys.stderr)

    # 2) Optional: Write digest to a GitHub Issue (logbook)
    if POST_TO_ISSUE:
        try:
            if ISSUE_NUMBER:
                num = int(ISSUE_NUMBER)
                c = post_comment(num, f"```\n{digest}\n```")
                print(f"[ok] commented on issue #{num}: {c.get('html_url','')}")
            else:
                num, url = ensure_issue_by_title(ISSUE_TITLE, ISSUE_LABELS)
                c = post_comment(num, f"```\n{digest}\n```")
                print(f"[ok] posted to issue #{num} ({url})")
        except Exception as e:
            print(f"[warn] Issue posting failed: {e}", file=sys.stderr)
    else:
        print("[info] Issue post skipped (set GITHUB_TOKEN and ISSUE_NUMBER or ISSUE_TITLE to enable).", file=sys.stderr)

    # 3) Always echo digest to logs
    print("\n===== DIGEST (plain text) =====\n")
    print(digest)

if __name__ == "__main__":
    main()
