#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

REPO = os.getenv("GITHUB_REPOSITORY")  # "owner/repo", provided by GH Actions
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

# ---------- HTTP helpers ----------

def http_get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": os.getenv("GH_API_USER_AGENT", "us-swing-trade-bot/1.0"),
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")

def fetch_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(http_get(url))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        print(f"[warn] GET {url} → {e.code} {e.reason}\n{body}", file=sys.stderr)
    except Exception as ex:
        print(f"[warn] GET {url} failed: {ex}", file=sys.stderr)
    return None

def gh_request_repo(method: str, path: str, payload: Optional[dict] = None) -> dict:
    token = os.getenv("GH_PAT") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Missing GH_PAT or GITHUB_TOKEN.")
    if not REPO:
        raise RuntimeError("Missing GITHUB_REPOSITORY.")

    api = os.getenv("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    url = f"{api}/repos/{REPO}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=data,
        method=method,
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
        body = e.read().decode("utf-8", "ignore")
        print(f"[error] GitHub API {method} {path} → {e.code}\n{body}", file=sys.stderr)
        raise

# ---------- parsing & sections ----------

def parse_rows(obj: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not obj or "rows" not in obj:
        return []
    rows = obj.get("rows") or []
    return [r for r in rows if isinstance(r, dict)]

def first_nonempty(d: Dict[str, Any], keys: List[str]) -> str:
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip() != "":
            return str(v)
    return ""

def section_buy_candidates(entry_rows: List[Dict[str, Any]]) -> List[str]:
    scored = []
    for r in entry_rows:
        t = first_nonempty(r, ["Ticker", "Symbol"])
        if not t:
            continue
        try:
            score = float(r["BounceScore"]) if r.get("BounceScore") not in (None, "") else None
        except Exception:
            score = None
        reasons = []
        try:
            if float(r.get("RSI", "100")) < 45:
                reasons.append("RSI<45")
        except Exception:
            pass
        try:
            if float(r.get("%B", "1")) <= 0.05:
                reasons.append("%B≤0.05")
        except Exception:
            pass
        if str(r.get("MACDHook", "")).lower() in ("true", "yes", "hook", "cross", "hook/cross"):
            reasons.append("MACD hook")
        if r.get("EarningsSafe") in (True, "true", "True", "OK", "ok", "yes"):
            reasons.append("ER≥35d")
        zone = first_nonempty(r, ["EntryZone", "Entry Zone", "SuggestedEntry"])
        reason_str = ", ".join(reasons) if reasons else "watch"
        scored.append((score if score is not None else -1e9, t, reason_str, zone))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for _, t, reason, zone in scored[:8]:
        out.append(f"   {t} ({reason})" + (f" — {zone}" if zone else ""))
    return out[:8] if len(out) >= 1 else out

def section_oversold_not_ready(oversold_rows: List[Dict[str, Any]]) -> List[str]:
    out = []
    for r in oversold_rows:
        t = first_nonempty(r, ["Ticker", "Symbol"])
        if not t:
            continue
        missing = first_nonempty(r, ["MissingSignals", "Missing", "Need"])
        next_at = first_nonempty(r, ["NextCheckAt", "Next Check", "NextCheckAt (ISO8601)"])
        nxt = f"; next {next_at}" if next_at else ""
        msg = f"   {t} — missing {missing}{nxt}" if missing else f"   {t}"
        out.append(msg)
    return out

def section_exits(exit_rows: List[Dict[str, Any]]) -> List[str]:
    out = []
    for r in exit_rows:
        t = first_nonempty(r, ["Ticker", "Symbol"])
        if not t:
            continue
        why = first_nonempty(r, ["Reason", "Trigger", "Status"])
        out.append(f"   {t}" + (f" — {why}" if why else ""))
    return out

def section_risk_quota(risk_rows: List[Dict[str, Any]]) -> str:
    if not risk_rows:
        return "Bootstrap row; system trigger"
    r0 = risk_rows[0]
    flags = []
    ks = str(first_nonempty(r0, ["KillSwitch", "KillSwitchState"])).upper()
    if ks:
        flags.append(f"KillSwitch: {ks}")
    dd = first_nonempty(r0, ["Drawdown", "DD_Pct", "DD"])
    if dd:
        flags.append(f"DD: {dd}")
    sector = first_nonempty(r0, ["SectorOverweights", "QuotaFlags", "Sector Quotas"])
    if sector:
        flags.append(f"Quotas: {sector}")
    return ", ".join(flags) if flags else "Bootstrap row; system trigger"

def section_upcoming_earnings(earn_rows: List[Dict[str, Any]]) -> str:
    items = []
    today = NOW_UTC.date()
    for r in earn_rows:
        t = first_nonempty(r, ["Ticker", "Symbol"])
        if not t:
            continue
        dt_str = first_nonempty(
            r,
            ["EarningsDate", "NextEarnings", "EarningsDateISO", "Next ER (ISO)", "Next ER (Est.)", "NextERISO"],
        )
        if not dt_str:
            continue
        try:
            ds = dt_str.replace("Z", "+00:00")
            d = datetime.fromisoformat(ds)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            days = (d.date() - today).days
            if 0 <= days <= 14:
                items.append(f"{t} ({days}d)")
        except Exception:
            continue
    return ", ".join(sorted(items)) if items else "—"

def manifest_staleness(manifest_obj: Optional[Dict[str, Any]]) -> str:
    if not manifest_obj:
        return f"Manifest missing at {URLS['manifest']}"
    iso = manifest_obj.get("snapshot_iso") or manifest_obj.get("timestamp") or ""
    if not iso:
        return "Manifest timestamp missing"
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        mins = int((NOW_UTC - ts).total_seconds() // 60)
        stale_flag = " (STALE!)" if mins > STALE_MINUTES else ""
        return f"Snapshot {iso} — {mins} minutes ago{stale_flag}"
    except Exception:
        return f"Manifest timestamp unreadable: {iso}"

# ---------- digest ----------

def build_digest(data: Dict[str, Any]) -> str:
    entry_rows   = parse_rows(data.get("EntryWatchlist"))
    over_rows    = parse_rows(data.get("OversoldTracker"))
    exit_rows    = parse_rows(data.get("ExitMonitor"))
    risk_rows    = parse_rows(data.get("RiskMonitor"))
    earn_rows    = parse_rows(data.get("EarningsMonitor"))
    manifest_obj = data.get("manifest")

    header = f"Watchlist Digest — {NOW_UTC.strftime('%Y-%m-%d %H:%MZ')}\n"
    buy_block  = "\n".join(section_buy_candidates(entry_rows)) or "   —"
    over_block = "\n".join(section_oversold_not_ready(over_rows)) or "   —"
    exit_block = "\n".join(section_exits(exit_rows)) or "   —"
    risk_block = section_risk_quota(risk_rows) or "Bootstrap row; system trigger"
    er14       = section_upcoming_earnings(earn_rows)
    stale      = manifest_staleness(manifest_obj)

    return (
        f"{header}\n"
        f"1) Buy Candidates\n{buy_block}\n\n"
        f"2) Oversold but Not Ready\n{over_block}\n\n"
        f"3) Exits\n{exit_block}\n\n"
        f"4) Risk & Quotas\n   {risk_block}\n\n"
        f"5) Upcoming Earnings (next 14 days)\n   {er14}\n\n"
        f"Staleness\n   {stale}\n"
    )

# ---------- GitHub Issues (no /search) ----------

def ensure_issue(issue_number: Optional[int], title: Optional[str], labels_csv: Optional[str]) -> int:
    if issue_number:
        return int(issue_number)
    if not title:
        title = f"Watchlist Digest — {MONTH}"
    # list first 100 open issues and match locally
    issues = gh_request_repo("GET", "/issues?state=open&per_page=100")
    for it in issues:
        if "pull_request" in it:   # skip PRs
            continue
        if it.get("title") == title:
            return int(it["number"])
    # create new
    labels = [s.strip() for s in (labels_csv or "").split(",") if s.strip()]
    created = gh_request_repo("POST", "/issues", {"title": title, "labels": labels})
    return int(created["number"])

def post_comment(issue_number: int, body: str) -> None:
    gh_request_repo("POST", f"/issues/{issue_number}/comments", {"body": body})

# ---------- OpenAI (optional) ----------

def post_to_openai_thread(message: str) -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    thread_id = os.getenv("THREAD_ID")
    if not api_key or not thread_id:
        print("[info] OPENAI vars missing; skipping OpenAI post.")
        return
    try:
        url = f"https://api.openai.com/v1/threads/{thread_id}/messages"
        data = json.dumps({"role": "user", "content": message}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": os.getenv("GH_API_USER_AGENT", "us-swing-trade-bot/1.0"),
            },
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            _ = r.read()
        print("[info] Posted digest to OpenAI thread.")
    except Exception as e:
        print(f"[warn] OpenAI post failed: {e}", file=sys.stderr)

# ---------- main ----------

def main() -> None:
    data: Dict[str, Any] = {}
    for key, url in URLS.items():
        data[key] = fetch_json(url)

    digest = build_digest(data)
    print("\n===== DIGEST (plain text) =====\n")
    print(digest)

    try:
        issue_no_env = os.getenv("ISSUE_NUMBER")
        issue_title  = os.getenv("ISSUE_TITLE")
        labels       = os.getenv("ISSUE_LABELS", "digest,automation")
        issue_no = ensure_issue(int(issue_no_env) if issue_no_env else None, issue_title, labels)
        post_comment(issue_no, digest)
        print(f"[info] Posted digest comment to Issue #{issue_no}.")
    except Exception as ex:
        print(f"[warn] Issue posting failed: {ex}", file=sys.stderr)

    post_to_openai_thread(digest)

if __name__ == "__main__":
    main()
