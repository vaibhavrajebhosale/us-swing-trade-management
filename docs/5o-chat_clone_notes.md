# Chat Clone Notes — Strategy 4.1 + Schema v2.2

## Snapshot (2025-09-17, America/Chicago)
This file captures the operative context cloned from the “Improved Strategy” chat so Custom GPTs and scripts can rely on the repo copy (not transient chat memory).

---

### Clone Summary — Strategy 4.1 + Schema v2.2 (verbatim)
Core Setup
  •  Schema Version: v2.2 (all date fields standardized as (ISO8601))
  •  Strategy Version: 4.1
  •  Flow: Raw data → Signals → Actions → Audit

Tabs & Roles
  •  Settings → knobs: ER buffer (35d), exit buffer (7d), kill switch, sector caps.
  •  CacheDailyBars → OHLCV store for RSI(14), MACD(12,26,9), %B(20,2), ATR20, VolZ.
  •  APIBudget → throttle API calls, fall back to cache.
  •  TickerMetadata → liquidity, GICS, dedupe ADRs.
  •  Validate → symbol hygiene; Valid?=N → Excluded.
  •  EarningsMonitor → single ER truth: date, BMO/AMC, Δ flag, DaysUntil.
  •  EarningsDeltaLog → append-only audit of ER date shifts.
  •  BacktestResults → avg return %, hit rate, best window; used for “StrongEarningsHistory.”
  •  MasterStockList → universe brain: status, latest indicators, gates (SectorSlotOK, KillSwitchOK, WashSale).
  •  OversoldTracker → staging: Oversold / Bounce Pending / Entry Ready.
  •  EntryWatchlist → actionable: signals, gates, ProposedSize, Confidence, Recommendation, NextCheckAt.
  •  CurrentHoldings → live book: entries, returns, exit triggers, carve-outs.
  •  ExitMonitor → computed exits: triggers firing, RecommendedAction, RuleSet Pre-Oct vs Post-Oct.
  •  SectorExposure → enforce sector quotas (≤3 holdings per GICS sector).
  •  RiskMonitor → portfolio guardrail: DD_10d_%, KillSwitch state, exposures.
  •  NextCycleQueue → parking lot: ER<35d, SectorCap, KillSwitch, WashSale.
  •  ClosedTrades → realized history, feeds wash-sale + P&L analytics.
  •  BacktestQueue → enqueue for sims; filled by external engine.
  •  PortfolioEquity → equity curve, cross-check DD.
  •  LongTermHoldings → carved LTH lots with thesis & review cadence.
  •  AlertsLog → audit of critical warnings.

Daily Flow
  1. Pre-open: Settings → CacheDailyBars → update MasterStockList → stage OversoldTracker → promote EntryWatchlist.
  2. Intraday: poll only NextCheckAt due rows → refresh signals, update recs → log ER deltas.
  3. Pre-close: apply exit logic → update ExitMonitor & CurrentHoldings → append ClosedTrades → update wash-sale dates.
  4. Overnight: drain BacktestQueue → update BacktestResults → sync MasterStockList.

Payload Recipes (v2.2 headers only)
  - See docs/payload_recipes.md for the five canonical write templates:
    1) Promote to EntryWatchlist
    2) Blocked Candidate
    3) ExitNow via ExitMonitor
    4) Carve LTH (update CurrentHoldings + insert LongTermHoldings)
    5) Snooze to NextCycle

---

### Additional Norms
- **Buffers**: ER buffer = 35d; exit buffer = 7d.
- **RuleSet** difference:
  - Pre-Oct-2025: Min hold 33 days; sell window Day 33–40; always exit ≥7d pre-ER.
  - Post-Oct-2025: Dynamic exits (profit 5–10%, RSI>65, MACD rollover, stop −10% or 2.5×ATR20), still ≥7d pre-ER.
- **LTH**: default carve 10% if gain ≥ +8% and guardrails allow.
- **Automations**: Disabled by default (user directive on 2025-09-06).

### Changelog
- **2025-09-17**: Initial clone to repo docs (schema v2.2 + strategy 4.1 + recipes).
