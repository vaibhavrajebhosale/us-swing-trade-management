#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

REPO = os.getenv("GITHUB_REPOSITORY")  # "owner/repo"
BRANCH = os.getenv("BRANCH", "Strategy_4_1")
NOW_UTC = datetime.now(timezone.utc)
MONTH = NOW_UTC.strftime("%Y-%m")
STALE_MINUTES = int(os.getenv("STALE_MINUTES", "120"))

CDN_BASE = (
    f"https://cdn.jsdelivr.net/gh/vaibhavrajebhosale/"
    f"us-swing-trade-management@{BRANCH}/snapshots/{MONTH}/latest"
)
URLS = {
    "manifest":        f"{CDN_BASE}/manifest.json",
    "CurrentHoldings": f"{CDN_BASE}/CurrentHoldings.json",
    "ExitMonitor":     f"{CDN_BASE}/ExitMonitor.json",
    "RiskMonitor":     f"{CDN_BASE}/RiskMonitor.json",
    "SectorExposure":  f"{CDN_BASE}/SectorExposure.json",
    "EarningsMonitor": f"{CDN_BASE}/EarningsMonitor.json",
    "EntryWatchlist":  f"{CDN_BASE}/EntryWatchlist.json",
    "OversoldTracker": f"{CDN_BASE}/OversoldTracker.json",
    "MasterStockList": f"{CDN_BASE}/MasterStockList.json",
    "BacktestQueue":   f"{CDN_BASE}/BacktestQueue.json",
    "BacktestResults": f"{CDN_BASE}/BacktestResults.json",
    "PortfolioEquity": f"{CDN_BASE}/PortfolioEquity.json",
}

def http_get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": os.getenv("GH_API_USER_AGENT", "us-swing-trade-bot/1.0"),
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")

def fetch_json(url: str) -> Optional[Dict[str, Any]]:
    try: return json.loads(http_get(url))
    except urllib.error.HTTPError as e:
        print(f"[warn] GET {url} → {e.code} {e.reason}\n{e.read().decode('utf-8','ignore')}", file=sys.stderr)
    except Exception as ex:
        print(f"[warn] GET {url} failed: {ex}", file=sys.stderr)
    return None

# -------- GitHub API (force PAT) --------
def _get_pat() -> str:
    pat = os.getenv("GH_PAT")
    if not pat:
        raise RuntimeError("GH_PAT (fine-grained PAT with Issues:write) is missing.")
    return pat

def gh_repo(method: str, path: str, payload: Optional[dict] = None) -> dict:
    token = _get_pat()
    if not REPO:
        raise RuntimeError("GITHUB_REPOSITORY is not set.")
    api = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    url = f"{api}/repos/{REPO}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": os.getenv("GH_API_USER_AGENT", "us-swing-trade-bot/1.0"),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8","ignore")
        print(f"[error] GitHub API {method} {path} → {e.code}\n{body}", file=sys.stderr)
        raise

# -------- parsing helpers --------
def parse_rows(obj: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not obj or "rows" not in obj: return []
    rows = obj.get("rows") or []
    return [r for r in rows if isinstance(r, dict)]

def first(d: Dict[str, Any], keys: List[str]) -> str:
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip() != "":
            return str(v)
    return ""

# -------- digest sections --------
def section_buy(entry_rows):  # top 8 by BounceScore
    scored = []
    for r in entry_rows:
        t = first(r, ["Ticker","Symbol"])
        if not t: continue
        try: score = float(r["BounceScore"]) if r.get("BounceScore") not in (None,"") else None
        except: score = None
        reasons = []
        try:
            if float(r.get("RSI","100")) < 45: reasons.append("RSI<45")
        except: pass
        try:
            if float(r.get("%B","1")) <= 0.05: reasons.append("%B≤0.05")
        except: pass
        if str(r.get("MACDHook","")).lower() in ("true","yes","hook","cross","hook/cross"):
            reasons.append("MACD hook")
        if r.get("EarningsSafe") in (True,"true","True","OK","ok","yes"):
            reasons.append("ER≥35d")
        zone = first(r, ["EntryZone","Entry Zone","SuggestedEntry"])
        scored.append((score if score is not None else -1e9, t, ", ".join(reasons) or "watch", zone))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [f"   {t} ({why})" + (f" — {zone}" if zone else "") for _,t,why,zone in scored[:8]] or ["   —"]

def section_over(oversold_rows):
    out=[]
    for r in oversold_rows:
        t = first(r, ["Ticker","Symbol"])
        if not t: continue
        missing = first(r, ["MissingSignals","Missing","Need"])
        nxt = first(r, ["NextCheckAt","Next Check","NextCheckAt (ISO8601)"])
        out.append(f"   {t} — missing {missing}" + (f"; next {nxt}" if nxt else "") if missing else f"   {t}")
    return out or ["   —"]

def section_exits(exit_rows):
    out=[]
    for r in exit_rows:
        t = first(r, ["Ticker","Symbol"])
        if not t: continue
        why = first(r, ["Reason","Trigger","Status"])
        out.append(f"   {t}" + (f" — {why}" if why else ""))
    return out or ["   —"]

def section_risk(risk_rows):
    if not risk_rows: return "Bootstrap row; system trigger"
    r0 = risk_rows[0]
    flags=[]
    ks = first(r0, ["KillSwitch","KillSwitchState"])
    if ks: flags.append(f"KillSwitch: {ks}")
    dd = first(r0, ["Drawdown","DD_Pct","DD"])
    if dd: flags.append(f"DD: {dd}")
    q  = first(r0, ["SectorOverweights","QuotaFlags","Sector Quotas"])
    if q: flags.append(f"Quotas: {q}")
    return ", ".join(flags) or "Bootstrap row; system trigger"

def section_earn14(earn_rows):
    items=[]
    today = NOW_UTC.date()
    for r in earn_rows:
        t = first(r, ["Ticker","Symbol"])
        if not t: continue
        dt = first(r, ["EarningsDate","NextEarnings","EarningsDateISO","Next ER (ISO)","Next ER (Est.)","NextERISO"])
        if not dt: continue
        try:
            ds = dt.replace("Z","+00:00")
            d = datetime.fromisoformat(ds)
            if d.tzinfo is None: d = d.replace(tzinfo=timezone.utc)
            days = (d.date()-today).days
            if 0 <= days <= 14: items.append(f"{t} ({days}d)")
        except: pass
    return ", ".join(sorted(items)) if items else "—"

def staleness(manifest_obj):
    if not manifest_obj: return f"Manifest missing at {URLS['manifest']}"
    iso = manifest_obj.get("snapshot_iso") or manifest_obj.get("timestamp") or ""
    if not iso: return "Manifest timestamp missing"
    try:
        ts = datetime.fromisoformat(iso.replace("Z","+00:00"))
        if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
        mins = int((NOW_UTC - ts).total_seconds() // 60)
        return f"Snapshot {iso} — {mins} minutes ago" + (" (STALE!)" if mins > STALE_MINUTES else "")
    except: return f"Manifest timestamp unreadable: {iso}"

def build_digest(data: Dict[str,Any]) -> str:
    entry  = parse_rows(data.get("EntryWatchlist"))
    over   = parse_rows(data.get("OversoldTracker"))
    exits  = parse_rows(data.get("ExitMonitor"))
    risk   = parse_rows(data.get("RiskMonitor"))
    earn   = parse_rows(data.get("EarningsMonitor"))
    mani   = data.get("manifest")

    return (
        f"Watchlist Digest — {NOW_UTC.strftime('%Y-%m-%d %H:%MZ')}\n\n"
        f"1) Buy Candidates\n" + "\n".join(section_buy(entry)) + "\n\n"
        f"2) Oversold but Not Ready\n" + "\n".join(section_over(over)) + "\n\n"
        f"3) Exits\n" + "\n".join(section_exits(exits)) + "\n\n"
        f"4) Risk & Quotas\n   {section_risk(risk)}\n\n"
        f"5) Upcoming Earnings (next 14 days)\n   {section_earn14(earn)}\n\n"
        f"Staleness\n   {staleness(mani)}\n"
    )

# -------- issues (no /search) --------
def ensure_issue(issue_number: Optional[int], title: Optional[str], labels_csv: Optional[str]) -> int:
    if issue_number: return int(issue_number)
    title = title or f"Watchlist Digest — {MONTH}"
    # list open issues, match exactly
    issues = gh_repo("GET", "/issues?state=open&per_page=100")
    for it in issues:
        if "pull_request" in it: continue
        if it.get("title") == title:
            return int(it["number"])
    labels = [s.strip() for s in (labels_csv or "").split(",") if s.strip()]
    created = gh_repo("POST", "/issues", {"title": title, "labels": labels})
    return int(created["number"])

def post_comment(issue_number: int, body: str) -> None:
    gh_repo("POST", f"/issues/{issue_number}/comments", {"body": body})

# -------- main --------
def main() -> None:
    data: Dict[str, Any] = {}
    for k, url in URLS.items():
        data[k] = fetch_json(url)
    data["manifest"] = fetch_json(URLS["manifest"])  # keep manifest key if present

    digest = build_digest(data)
    print("\n===== DIGEST (plain text) =====\n")
    print(digest)

    issue_no_env = os.getenv("ISSUE_NUMBER")
    issue_title  = os.getenv("ISSUE_TITLE")
    labels       = os.getenv("ISSUE_LABELS", "digest,automation")

    try:
        issue_no = ensure_issue(int(issue_no_env) if issue_no_env else None, issue_title, labels)
        post_comment(issue_no, digest)
        print(f"[info] Posted digest comment to Issue #{issue_no}.")
    except Exception as ex:
        print(f"[warn] Issue posting failed: {ex}", file=sys.stderr)

if __name__ == "__main__":
    main()
