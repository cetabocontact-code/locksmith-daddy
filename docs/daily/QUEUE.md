# Investigation Queue

Tasks the morning autopilot will pick up in order. As each is completed,
the autopilot strikes it off and moves to the next.

## Active queue

- [ ] Bug #2 — placeholder /v?vin=... page returns empty candidates. Retry after 2s delay test
- [ ] Bug #3 — synthetic VIN methodology (switch evening test to real NHTSA-recall VINs)
- [ ] Add parts.genesis.com SimplePart driver (closes Genesis G70 0% gap)
- [ ] Apply year-segment fix to KiaOempartsDriver (defensive, may not be needed)
- [ ] Investigate Hyundai Palisade 2025 0/4 (likely real catalog gap)
- [ ] Investigate Kia EV6 2024 trim disambiguation ("Light, Wind" vs dealer labels)
- [ ] Add Toyota driver (after Hyundai/Kia hit 90% verified rate)

## Done this week

- [x] 2026-05-29 — Bug #1 fix: require year segment in candidate URLs
- [x] 2026-05-29 — Parallelize category sweeps within driver (3x latency win)
- [x] 2026-05-29 — Diagnostic capture layer wired (LBT1_DIAGNOSTICS=1)
- [x] 2026-05-29 — Daily 5-min loading message + close-tab-safe UX

## How the autopilot picks

Reads the topmost `- [ ]` line in the Active queue. The text after `- [ ]`
becomes the morning session topic. Each known bug has a matching script
in `scripts/autopilot_*.py` that the dispatcher invokes.

When you want to override or add priority, edit this file directly.
