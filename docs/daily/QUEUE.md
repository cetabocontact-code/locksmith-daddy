# Investigation Queue

Tasks the morning autopilot will pick up in order. As each is completed,
the autopilot strikes it off and moves to the next.

## Active queue

- [ ] Toyota category tuning — probe Camry vehicle landing page to find where fobs (89904-*/89070-*) actually live. Likely body/locks-hardware or accessories
- [ ] Apply year-segment fix to KiaOempartsDriver (defensive — same base class so already inherited, but verify with 1 VIN)
- [ ] Add parts.genesis.com SimplePart driver (closes Genesis G70 0% gap)
- [ ] Bug #4 — Kia EV6 NHTSA returns "Light, Wind" multi-trim; dealer uses "GT-Line" or similar. Inspect dealer trim chooser
- [ ] Investigate Hyundai Palisade 2025 0/4 (likely real catalog gap on new model year)
- [ ] Wait for user's real-VIN DB (data/real_vins_from_codex.csv) → re-run full coverage measurement
- [ ] Add parts.toyota.com SimplePart-like driver as Toyota tier-2 fallback
- [ ] Build VA brief #1: "Toyota OEM key fob naming research" task in Arabic

## Done this week

- [x] 2026-05-29 — Bug #1 fix: require year segment in candidate URLs
- [x] 2026-05-29 — Bug #2 fix: retry-on-placeholder ~30% recovery
- [x] 2026-05-29 — Parallelize category sweeps within driver (3x latency win)
- [x] 2026-05-29 — Diagnostic capture layer wired (LBT1_DIAGNOSTICS=1)
- [x] 2026-05-29 — Daily 5-min loading message + close-tab-safe UX
- [x] 2026-05-29 — ScrapFly budget governor (50%/90% alerts, hard stop at 95%)
- [x] 2026-05-29 — Windows Task Scheduler registered (8/14/20 CST daily)
- [x] 2026-05-29 — ToyotaOempartsDriver added (Revolution Parts CMS, structurally works)
- [x] 2026-05-29 — Real-VIN regression test: 20/30 = 66.7% verified

## How the autopilot picks

Reads the topmost `- [ ]` line in the Active queue. The text after `- [ ]`
becomes the morning session topic. Each known bug has a matching script
in `scripts/autopilot_*.py` that the dispatcher invokes.

When you want to override or add priority, edit this file directly.
