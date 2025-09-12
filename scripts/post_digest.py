#!/usr/bin/env python3
# digest.py — Strategy 4.1 email-ready watchlist digest (plain text)
# Reads monthly "latest" JSON tabs from jsDelivr and prints a digest.

import os, sys, time, math, json, requests
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

BASE = "https://cdn.jsdelivr.net/gh/vaibhavrajebhosale/us-swing-trade-management@Strategy_4_1"
TZ = ZoneInfo("America/New_York")

# ---------- time helpers ----------
def now_et():
    return datetime.now(TZ)

def month_slug(dt=None) -> str:
    dt = dt or now_et()
    return dt.strftime("%Y-%m")

def parse_dt(s: str | None):
    if not s or not isinstance(s, str): return None
    try:
        # allow ISO with Z
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except Exception:
        return None

def days_until(dt: datetime | None, ref=None):
    if not dt: return None
    ref = ref or now_et().astimezone(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return math.floor((dt - ref).total_seconds() / 86400)

# ---------- robust URL resolver (monthly alias -> manifest fallbacks) ----------
def _pick_timestamp_path(manifest: dict) -> str | None:
    for k in ("timestampPath", "latestPath", "path"):
        v = manifest.get(k)
        if isinstance(v, str) and v.startswith("snapshots/"):
            return v
    for v in manifest.values():
        if isinstance(v, str) and v.startswith("snapshots/"):
            return v
    return None

def url_for_tab(tab: str) -> str:
    mm = month_slug()
    monthly = f"{BASE}/snapshots/{mm}/latest/{tab}.json"
    # try monthly alias
    r = requests.get(f"{monthly}?v={int(time.time())}", timeout=20)
    if r.ok: return monthly
    # monthly manifest fallback
    murl = f"{BASE}/manifest/month-{mm}.json?v={int(time.time())}"
    mr = requests.get(murl, timeout=20)
    if mr.ok:
        ts = _pick_timestamp_path(mr.json())
        if ts: return f"{BASE}/{ts}/{tab}.json"
    # global manifest fallback
    gurl = f"{BASE}/manifest/latest.json?v={int(time.time())}"
    gr = requests.get(gurl, timeout=20)
    if gr.ok:
        ts = _pick_timestamp_path(gr.json())
        if ts: return f"{BASE}/{ts}/{tab}.json"
    # last resort: monthly alias (may 404)
    return monthly

def url_for_monthly_manifest() -> str | None:
    mm = month_slug()
    u = f"{BASE}/snapshots/{mm}/latest/manifest.json"
    r = requests.get(f"{u}?v={int(time.time())}", timeout=20)
    return u if r.ok else None

# ---------- fetch & table helpers ----------
def fetch_json(url: str) -> dict:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

def to_rows(tab_json: dict) -> list[dict]:
    # Expected shape: {"columns":[...], "rows":[{...}]}
    if not tab_json: return []
    rows = tab_json.get("rows")
    if isinstance(rows, list): return rows
    # fallback if a flat array is stored
    if isinstance(tab_json, list): return tab_json
    return []

def pick(row: dict, *cands, default=None):
    if not row: return default
    lower = {k.lower(): k for k in row.keys()}
    for c in cands:
        if c in row: return row[c]
        lc = c.lower()
        if lc in lower: return row[lower[lc]]
    return default

def num(v, default=None):
    try:
        if v is None or v == "": return default
        return float(v)
    except Exception:
        return default

# ---------- section builders ----------
def section_buy_candidates(entry_rows):
    # Rank by BounceScore if present; else keep input order
    scored = []
    for r in entry_rows:
        tick = pick(r, "Ticker", "Symbol", default="?")
        score = num(pick(r, "BounceScore", "Bounce Score", "Score"), default=None)
        # basic gating: prefer things marked Buy/Watch
        rec = (pick(r, "Recommendation", "Status", default="") or "").lower()
        scored.append((score if score is not None else -1e9, tick, r, rec))
    scored.sort(key=lambda x: x[0], reverse=True)
    # choose 3–8; prefer items that look actionable
    chosen = [x for x in scored if ("buy" in x[3] or "watch" in x[3])][:8]
    if len(chosen) < 3:
        chosen = scored[:max(3, min(8, len(scored)))]
    lines = []
    for _, tick, r, _ in chosen:
        # entry zone candidates
        zone = pick(r, "EntryZone", "Entry Zone", "BuyZone", "SuggestedEntry", default="—")
        tags = pick(r, "ReasonTags", "Tags", default=None) or pick(r, "Notes", default="")
        if isinstance(tags, list): tags = ", ".join(tags)
        if tags: tags = tags.strip()
        tag_out = f" ({tags})" if tags else ""
        lines.append(f"• {tick}{tag_out} — Entry: {zone}")
    return "\n".join(lines) if lines else "• —"

def section_oversold_not_ready(overs_rows):
    out = []
    for r in overs_rows:
        tick = pick(r, "Ticker", "Symbol", default="?")
        miss = pick(r, "MissingSignals", "Missing", default="—")
        nca = pick(r, "NextCheckAt", "NextCheckAt (ISO8601)", "Next Check", default=None)
        if nca:
            t = parse_dt(nca)
            when = t.astimezone(TZ).strftime("%b %d, %I:%M %p %Z") if t else nca
        else:
            when = "—"
        out.append(f"• {tick} — missing: {miss}; next check: {when}")
    return "\n".join(out) if out else "• —"

def section_exits(exits_rows):
    out = []
    for r in exits_rows:
        tick = pick(r, "Ticker", "Symbol", default="?")
        rec = (pick(r, "Recommendation", "Action", "Status", default="") or "").lower()
        if any(k in rec for k in ("exit", "trim", "sell")):
            why = pick(r, "Trigger", "Reason", "Notes", default="—")
            out.append(f"• {tick} — {why}")
    return "\n".join(out) if out else "• —"

def section_risk_quota(risk_rows, sector_rows):
    # KillSwitch + DD from RiskMonitor; simple sector counts/flags
    ks = None; dd = None
    if risk_rows:
        r0 = risk_rows[0]
        ks = pick(r0, "KillSwitch", "KillSwitch State", "KS", default=None)
        dd = pick(r0, "DD10D", "Drawdown10D", "DD%", default=None)
    ks_s = f"KillSwitch: {ks}" if ks is not None else "KillSwitch: —"
    dd_s = f" | 10D DD: {dd}" if dd is not None else ""
    # sector caps: count <= 3 guideline
    caps = []
    for r in sector_rows or []:
        name = pick(r, "Sector", default=None)
        count = pick(r, "Count", "#", "Positions", default=None)
        if name and count is not None:
            try:
                n = int(float(count))
                flag = " (full)" if n >= 3 else ""
                caps.append(f"{name}:{n}{flag}")
            except Exception:
                pass
    caps_s = " | Sectors: " + ", ".join(caps) if caps else ""
    return ks_s + dd_s + caps_s

def section_upcoming_er(earn_rows, days=14):
    out = []
    nowu = now_et().astimezone(timezone.utc)
    for r in earn_rows:
        tick = pick(r, "Ticker", "Symbol", default="?")
        dt = parse_dt(pick(r, "EarningsDate", "NextEarnings", "NextER", "ERDate"))
        dleft = days_until(dt, ref=nowu)
        if dleft is not None and 0 <= dleft <= days:
            when = dt.astimezone(TZ).strftime("%b %d") if dt else "—"
            out.append((dleft, f"• {tick} — {when} ({dleft}d)"))
    out.sort(key=lambda x: x[0])
    return "\n".join([x[1] for x in out]) if out else "• —"

# ---------- main ----------
def main():
    # resolve and fetch tabs
    entry = to_rows(fetch_json(url_for_tab("EntryWatchlist")))
    overs = to_rows(fetch_json(url_for_tab("OversoldTracker")))
    exits = to_rows(fetch_json(url_for_tab("ExitMonitor")))
    risk  = to_rows(fetch_json(url_for_tab("RiskMonitor")))
    sect  = to_rows(fetch_json(url_for_tab("SectorExposure")))
    earn  = to_rows(fetch_json(url_for_tab("EarningsMonitor")))

    # snapshot info (best-effort)
    snap_info = ""
    murl = url_for_monthly_manifest()
    if murl:
        try:
            m = fetch_json(murl)
            ts = _pick_timestamp_path(m) or ""
            # e.g., snapshots/2025-09/2025-09-06/16-33-54Z
            parts = ts.split("/")
            if len(parts) >= 4:
                d = parts[-2]; t = parts[-1]
                iso = f"{d}T{t}".replace("Z","Z")
                dt = parse_dt(iso)
                if dt:
                    snap_info = dt.astimezone(TZ).strftime("%b %d, %Y %I:%M %p %Z")
        except Exception:
            pass

    # build sections
    s1 = section_buy_candidates(entry)
    s2 = section_oversold_not_ready(overs)
    s3 = section_exits(exits)
    s4 = section_risk_quota(risk, sect)
    s5 = section_upcoming_er(earn, days=14)

    # header
    hdr_date = now_et().strftime("%b %d, %Y")
    hdr = f"📮 Watchlist Digest — Strategy 4.1 ({hdr_date})"
    if snap_info:
        hdr += f"\nSnapshot: {snap_info}"

    # print digest
    out = f"""{hdr}

1) Buy Candidates
{s1}

2) Oversold but Not Ready
{s2}

3) Exits
{s3}

4) Risk & Quotas
{s4}

5) Upcoming Earnings (next 14 days)
{s5}
"""
    print(out.strip())

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stderr.write(f"ERROR: {e}\n")
        sys.exit(1)
