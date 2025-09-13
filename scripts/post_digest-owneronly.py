#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Post a plain-text watchlist digest to a GitHub Issue (owner-only flavor).
- Reads latest snapshot JSONs from jsDelivr CDN
- Month is dynamic (YYYY-MM, UTC)
- Uses PAT via GH_PAT (or GITHUB_TOKEN fallback) to write Issues/Comments
- Sets a proper User-Agent and logs detailed API errors
- Optional: also posts the digest into an OpenAI thread if OPENAI vars are present

Required repo settings:
- Settings → Actions → General → Workflow permissions → READ & WRITE
- Issues feature enabled

ENV (recommended):
- GH_PAT: classic PAT with `repo` scope (preferred over GITHUB_TOKEN if org restricts writes)
- BRANCH: git branch name (default: Strategy_4_1)
- ISSUE_NUMBER: (optional) post as a comment to this issue
- ISSUE_TITLE:  (optional) if no ISSUE_NUMBER, create or reuse an issue with this title
- ISSUE_LABELS: (optional) comma-separated labels (e.g. "digest,automation")

Optional OpenAI:
- OPENAI_API_KEY, THREAD_ID  (ASSISTANT_ID optional; we only append a message)
"""

from __future__ import annotations
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

REPO = os.getenv("GITHUB_REPOSITORY")  # "owner/repo"
BRANCH = os.getenv("BRANCH", "Strategy_4_1")
NOW_UTC = datetime.now(timezone.utc)
MONTH = NOW_UTC.strftime("%Y-%m")

# CDN base (dynamic month)
CDN_BASE = (
    f"https://cdn.jsdelivr.net/gh/vaibhavrajebhosale/"
    f"us-swing-trade-management@{BRANCH}/snapshots/{MONTH}/latest"
)

# Tab URLs
URLS = {
    "manifest": f"{CDN_BASE}/manifest.json",
    "CurrentHoldings": f"{CDN_BASE}/CurrentHoldings.json",
    "ExitMonitor": f"{CDN_BASE}/ExitMonitor.json",
    "RiskMonitor": f"{CDN_BASE}/RiskMonitor.json",
    "SectorExposure": f"{CDN_BASE}/SectorExposure.json",
    "EarningsMonitor": f"{CDN_BASE}/EarningsMonitor.json",
    "EntryWatchlist": f"{CDN_BASE}/EntryWatchlist.json",
    "OversoldTracker": f"{CDN_BASE}/OversoldTracker.json",
    "MasterStockList": f"{CDN_BASE}/MasterStockList.json",
    "BacktestQueue": f"{CDN_BASE}/BacktestQueue.json",
    "BacktestResults": f"{CDN_BASE}/BacktestResults.json",
    "PortfolioEquity": f"{CDN_BASE}/PortfolioEquity.json",
}

# ----------------------------- Utilities ---------------------------------- #

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
        text = http_get(url)
        return json.loads(text)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        print(f"[warn] GET {url} → {e.code} {e.reason}\n{body}", file=sys.stderr)
    except Exception as ex:
        print(f"[warn] GET {url} failed: {ex}", file=sys.stderr)
    return None


def gh_request(method: str, path: str, payload: Optional[dict] = None) -> dict:
    token = os.getenv("GH_PAT") or os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Missing GH_PAT or GITHUB_TOKEN.")
    if not REPO:
        raise RuntimeError("Missing GITHUB_REPOSITORY.")

    api = os.getenv("GITHUB_API_URL", "https://api.github.com")
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


def parse_rows(obj: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not obj or "rows" not in obj:
        return []
    rows = obj.get("rows") or []
    # Ensure each row is dict-like
    good = [r for r in rows if isinstance(r, dict)]
    return good


def first_nonempty(d: Dict[str, Any], keys: List[str]) -> str:
    for k in keys:
        v = d.get(k)
        if v is not None and str(v).strip() != "":
            return str(v)
    return ""


# ----------------------------- Section logic -------------------------------- #

def section_buy_candidates(entry_rows: List[Dict[str, Any]]) -> List[str]:
    # Choose 3–8 highest BounceScore (descending)
    scored = []
    for r in entry_rows:
        t = first_nonempty(r, ["Ticker", "Symbol"])
        if not t:
            continue
        bs = r.get("BounceScore")
        try:
            score = float(bs) if bs is not None and str(bs) != "" else None
        except Exception:
            score = None
        # Build reason tags + entry zone if available
        reasons = []
        if str(r.get("Recommendation", "")).lower().startswith("buy"):
            reasons.append("Buy")
        if "RSI" in r:
            try:
                if float(r["RSI"]) < 45:
                    reasons.append("RSI<45")
            except Exception:
                pass
        if "%B" in r:
            try:
                if float(r["%B"]) <= 0.05:
                    reasons.append("%B≤0.05")
            except Exception:
                pass
        if str(r.get("MACDHook", "")).lower() in ("true", "yes", "hook", "cross", "hook/cross"):
            reasons.append("MACD hook")
        if r.get("EarningsSafe", "") in ("true", True, "yes", "ok"):
            reasons.append("ER≥35d")
        zone = first_nonempty(r, ["EntryZone", "Entry Zone", "SuggestedEntry"])
        reason_str = ", ".join(reasons) if reasons else "watch"
        scored.append((score if score is not None else -1e9, t, reason_str, zone))

    # sort by score desc, take up to 8
    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for _, t, reason, zone in scored[:8]:
        zone_txt = f" — {zone}" if zone else ""
        out.append(f"   {t} ({reason}){zone_txt}")
    return out[:8] if len(out) >= 3 else out  # allow fewer if limited


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
    # Try to surface key flags if present
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
    # Expect manifest contains {"snapshot_iso":"2025-09-13T04:21:00Z", ...}
    if not manifest_obj:
        return f"Manifest missing at {URLS['manifest']}"
    iso = manifest_obj.get("snapshot_iso") or manifest_obj.get("timestamp") or ""
    if not iso:
        return f"Manifest timestamp missing"
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        delta = NOW_UTC - ts
        mins = int(delta.total_seconds() // 60)
        stale_flag = " (STALE!)" if mins > 90 else ""
        return f"Snapshot {iso} — {mins} minutes ago{stale_flag}"
    except Exception:
        return f"Manifest timestamp unreadable: {iso}"


# --------------------------- Digest builder --------------------------------- #

def build_digest(data: Dict[str, Any]) -> str:
    entry_rows    = parse_rows(data.get("EntryWatchlist"))
    over_rows     = parse_rows(data.get("OversoldTracker"))
    exit_rows     = parse_rows(data.get("ExitMonitor"))
    risk_rows     = parse_rows(data.get("RiskMonitor"))
    earn_rows     = parse_rows(data.get("EarningsMonitor"))
    manifest_obj  = data.get("manifest")

    header = f"Watchlist Digest — {NOW_UTC.strftime('%Y-%m-%d %H:%MZ')}\n"
    buy_lines = section_buy_candidates(entry_rows)
    buy_block = "\n".join(buy_lines) if buy_lines else "   —"

    over_lines = section_oversold_not_ready(over_rows)
    over_block = "\n".join(over_lines) if over_lines else "   —"

    exit_lines = section_exits(exit_rows)
    exit_block = "\n".join(exit_lines) if exit_lines else "   —"

    risk_block = section_risk_quota(risk_rows) or "Bootstrap row; system trigger"
    er14 = section_upcoming_earnings(earn_rows)

    staleness = manifest_staleness(manifest_obj)

    text = (
        f"{header}\n"
        f"1) Buy Candidates\n{buy_block}\n\n"
        f"2) Oversold but Not Ready\n{over_block}\n\n"
        f"3) Exits\n{exit_block}\n\n"
        f"4) Risk & Quotas\n   {risk_block}\n\n"
        f"5) Upcoming Earnings (next 14 days)\n   {er14}\n\n"
        f"Staleness\n   {staleness}\n"
    )
    return text


# ----------------------------- GitHub Issue I/O ----------------------------- #

def ensure_issue(issue_number: Optional[int], title: Optional[str], labels_csv: Optional[str]) -> int:
    if issue_number:
        return int(issue_number)

    # Try to find existing open issue by title; else create
    if not title:
        title = f"Watchlist Digest — {MONTH}"

    # search issues (open) by title
    q = f" is:issue is:open repo:{REPO} in:title \"{title}\""
    search = gh_request("GET", f"/search/issues?q={urllib.parse.quote(q)}")
    for item in search.get("items", []):
        if item.get("title") == title:
            return int(item["number"])

    # create new
    labels = [s.strip() for s in (labels_csv or "").split(",") if s.strip()]
    created = gh_request("POST", "/issues", {"title": title, "labels": labels})
    return int(created["number"])


def post_comment(issue_number: int, body: str) -> None:
    gh_request("POST", f"/issues/{issue_number}/comments", {"body": body})


# ----------------------------- OpenAI (optional) ---------------------------- #

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


# --------------------------------- Main ------------------------------------- #

def main() -> None:
    # Load JSONs
    data: Dict[str, Any] = {}
    for key, url in URLS.items():
        data[key] = fetch_json(url)

    # Build digest
    digest = build_digest(data)

    print("\n===== DIGEST (plain text) =====\n")
    print(digest)

    # Post to GitHub Issue (using PAT)
    try:
        issue_no_env = os.getenv("ISSUE_NUMBER")
        issue_title = os.getenv("ISSUE_TITLE")
        labels = os.getenv("ISSUE_LABELS", "digest,automation")
        issue_no = ensure_issue(int(issue_no_env) if issue_no_env else None, issue_title, labels)
        post_comment(issue_no, digest)
        print(f"[info] Posted digest comment to Issue #{issue_no}.")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        print(f"[warn] Issue posting failed: {e}\n{body}", file=sys.stderr)
    except Exception as ex:
        print(f"[warn] Issue posting failed: {ex}", file=sys.stderr)

    # Optional OpenAI paste
    post_to_openai_thread(digest)


if __name__ == "__main__":
    main()
