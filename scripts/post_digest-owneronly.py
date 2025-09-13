#!/usr/bin/env python3
import json, os, sys, urllib.request, urllib.error, datetime

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ASSISTANT_ID   = os.environ.get("ASSISTANT_ID")
THREAD_ID      = os.environ.get("THREAD_ID")
BRANCH         = os.environ.get("BRANCH", "Strategy_4_1")

if not (OPENAI_API_KEY and ASSISTANT_ID and THREAD_ID):
    print("Missing one or more env vars: OPENAI_API_KEY, ASSISTANT_ID, THREAD_ID", file=sys.stderr)
    #sys.exit(1)

month = datetime.datetime.utcnow().strftime("%Y-%m")
base  = f"https://cdn.jsdelivr.net/gh/vaibhavrajebhosale/us-swing-trade-management@{BRANCH}/snapshots/{month}/latest"

tabs = {
    "EntryWatchlist": f"{base}/EntryWatchlist.json",
    "OversoldTracker": f"{base}/OversoldTracker.json",
    "ExitMonitor": f"{base}/ExitMonitor.json",
    "RiskMonitor": f"{base}/RiskMonitor.json",
    "EarningsMonitor": f"{base}/EarningsMonitor.json",
}

def fetch_rows(url: str):
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data.get("rows", [])
    except Exception as e:
        # Keep running even if a tab is missing/empty
        print(f"[warn] fetch failed {url}: {e}", file=sys.stderr)
        return []

def slurp():
    return {k: fetch_rows(v) for k, v in tabs.items()}

def pick(labels, key, n=8):
    vals = []
    for r in labels[:n]:
        v = r.get(key, "")
        if v:
            vals.append(v)
    return ", ".join(vals) if vals else "—"

def upcoming_14d(rows):
    # Try common field names for ISO8601 dates
    out = []
    now = datetime.datetime.utcnow().date()
    for r in rows:
        dt_str = r.get("EarningsDate") or r.get("NextEarnings") or r.get("EarningsDateISO") or r.get("Next ER (ISO)") or ""
        tick = r.get("Ticker") or r.get("Symbol") or ""
        if not tick or not dt_str:
            continue
        try:
            # Accept YYYY-MM-DD or full ISO
            d = datetime.datetime.fromisoformat(dt_str.replace("Z","")).date()
            days = (d - now).days
            if 0 <= days <= 14:
                out.append(f"{tick} ({days}d)")
        except Exception:
            continue
    return ", ".join(out) if out else "—"

def build_digest(d):
    ew = d.get("EntryWatchlist", [])
    ot = d.get("OversoldTracker", [])
    ex = d.get("ExitMonitor", [])
    rm = d.get("RiskMonitor", [])
    em = d.get("EarningsMonitor", [])

    buy = pick(ew, "Ticker", 8)
    oversold = pick(ot, "Ticker", 8)
    exits = pick(ex, "Ticker", 12)

    # Risk notes: try a few columns
    risk_notes = []
    for r in rm[:6]:
        note = r.get("Note") or r.get("Notes") or r.get("RiskNote") or ""
        if note:
            risk_notes.append(note)
    risk_str = "; ".join(risk_notes) if risk_notes else "—"

    earn_14 = upcoming_14d(em)

    lines = [
        "Watchlist Digest — Latest Scan",
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
    ]
    return "\n".join(lines)

def openai_post(url, payload):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))

def main():
    data = slurp()
    digest = build_digest(data)

    if (OPENAI_API_KEY and ASSISTANT_ID and THREAD_ID):
        # 1) Add a user message to thread
        msg_payload = {"role": "user", "content": digest}
         _ = openai_post(f"https://api.openai.com/v1/threads/{THREAD_ID}/messages", msg_payload)

    if (OPENAI_API_KEY and ASSISTANT_ID and THREAD_ID):
        # 2) Kick off a run
        run_payload = {"assistant_id": ASSISTANT_ID}
        run = openai_post(f"https://api.openai.com/v1/threads/{THREAD_ID}/runs", run_payload)

        print("[ok] posted digest to thread", THREAD_ID, "run", run.get("id","?"))

if __name__ == "__main__":
    main()
