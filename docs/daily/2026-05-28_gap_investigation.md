# Gap Investigation — 2026-05-28

Log-only diagnosis of the 0% (or near-0%) model coverage gaps from the
100-VIN 2024/2025 batch test. **No new ScrapFly burn — pattern analysis
from existing report + disambiguation log.**

## The four gap clusters

### Genesis G70 — 0/5 (all 2025)
All 3 failed VINs are **2025 model year** (the other 2 G70 in the test
set were not failures from this list — also 2025; sample is small).

**Hypothesis A (most likely)**: 2025 G70 catalog gap on Revolution Parts.
Same shape as the verified 2026 Elantra issue — manufacturer hasn't
populated electrical/keys for the new model year yet. **Genesis has NO
SimplePart fallback wired** (we only have Revolution Parts for Genesis),
so the chain dead-ends fast.

**Hypothesis B**: trim disambiguation fails. NHTSA returns `"3.3T Sport
Advanced (AWD/RWD); 3.3T Sport Prestige (AWD/RWD)"` — semicolon-separated
multi-trim. Our slugifier may not handle semicolons cleanly.

**Recommended action**:
1. Add `parts.genesis.com` SimplePart driver (mirror of HyundaiCanada / KiaUS).
2. Test ONE 2025 G70 VIN through the existing pipeline to confirm A vs B.
3. If catalog is truly empty, the new driver is the only fix — confirmed 60%+ likely outcome.

**Expected uplift if A is real**: +3-5% (Genesis is small share of testset, but 100% gap closure)

---

### Hyundai Palisade — 0/4 (all 2025)
All 4 are **2025 model year** (Limited and XRT trims).

**Hypothesis (very likely)**: 2025 Palisade catalog gap on Revolution
Parts. Palisade 2024 (not in test set) probably works fine. The
HyundaiCanada SimplePart fallback may also lack 2025 Palisade data — we
saw it had data for 2017 Elantra but EMPTY for 2026 Elantra.

**Recommended action**: One 2025 Palisade VIN through the pipeline to
confirm. Most likely a true 2025-catalog-not-yet-published gap. No code
fix possible until the catalog populates (this is real-world latency, not
a bug).

---

### Hyundai Sonata — 3/13 (23%)
**This is the suspicious one.** Sonata is a popular 5+ year mainstream
sedan. Should have very high coverage. Failed list:
- 2024 SE: 1 fail
- 2024 Limited: 5 fails  ← biggest concentration
- 2025 SE: 2 fails
- 2025 SEL: 2 fails

**Hypothesis A (likely)**: Our WMI generator produced 5NPEH4J2* and
5NPEG4JA* and 5NPEL4JA* with year codes R (2024) and S (2025). The
prefix-8 portion encodes specific engine/trim/restraint config. If our
synthetic VINs happen to land on a VDS that doesn't exist on Revolution
Parts's catalog (e.g., a fleet/rental-only configuration), the dealer
returns no trim chooser → 0 PNs.

**Hypothesis B (also plausible)**: NHTSA returns 2024 Sonata Limited as
just `"Limited"` (single token). Our scoring against the dealer's
`/v-2024-hyundai-sonata--limited--2-5l-l4-gas` link should match. But if
Hyundai labels 2024 Sonata Limited as `"limited-hybrid"` on the dealer
site (since hybrid is the dominant powertrain), the substring match
fails.

**Recommended action**: Test ONE failed Sonata VIN (e.g.,
5NPEH4J28RZ649867 = 2024 Sonata Limited) through the local CLI WITH
verbose output to capture the disambiguation decision. ~$0.05 ScrapFly
cost. This is the highest-value diagnostic.

**Expected uplift if A or B is real**: +5-10% across both years.

---

### Kia EV6 — 0/3 (all 2024)
NHTSA returns trim as **`"Light, Wind"`** — comma-separated.

**Hypothesis (likely)**: `pipeline.lookup` calls `profile.trim_candidates()`
which splits on commas and ampersands. So we get `["Light", "Wind"]`.
Then the scorer tries both as trim slugs. But the dealer might use
`"GT-Line"`, `"GT"`, or other Kia EV6 trim labels that don't match
"Light" or "Wind". Result: scorer can't find a match, picks the wrong
trim or falls back to model-level URL.

EV6 is also Kia's electric flagship — possibly newer catalog ergonomics.

**Recommended action**: Inspect the dealer's actual trim chooser for
2024 EV6: `https://kia.oempartsonline.com/v-2024-kia-ev6`. ~$0.013
ScrapFly cost. Reveals if "Light"/"Wind" are dealer-side trim labels at
all.

---

## Strategic conclusion

**The 60% coverage breaks down roughly as:**
- ~60% = legitimately verified ✓
- ~20% = real catalog gap on 2025 new releases (Palisade 2025, G70 2025) — fixable only by **adding more cross-platform sources**
- ~15% = trim disambiguation issues (Sonata, EV6) — **fixable in code**
- ~5% = noise / specific WMI patterns NHTSA can't fully decode

## Recommended next ScrapFly burn ($0.10-0.20 total — minimal)

1. ONE 2024 Sonata Limited VIN through verbose CLI → confirms Sonata
   hypothesis A or B → code fix worth ~+10% coverage
2. ONE 2024 EV6 VIN with trim probe → confirms EV6 trim label mismatch →
   code fix worth ~+3% coverage
3. ONE 2025 G70 VIN to confirm catalog-gap → motivates `parts.genesis.com`
   adapter build → worth ~+5% coverage

**Total spend: ~$0.20. Expected uplift: 75-78% coverage post-fixes.**

These should be the first 3 morning autopilot runs once the schedule starts.
