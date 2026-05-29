# CSV training data — workflow logic

Source: `data/kia_vin_training.csv` (23 rows).

Each row contains:
- `VIN`
- `Instructions` — the manual procedure the human locksmith followed
- `PN 1..PN 6` — the part numbers captured (1–6 per VIN)
- `Link 1..Link 6` — the dealer URLs for each PN

## The workflow as code

```
1. Open https://{make}.oempartsonline.com/
2. Paste VIN into the VIN search box → submit.
3. If a trim/engine disambiguation page appears, pick the trim that matches
   NHTSA's decoded Series or Trim field.
   Examples in CSV:
     - Row 14: "confirm car trim 'LX 2.4L L4 - Gas'"
     - Row 25: "confirm car trim 'LX 2.0L L4 - Gas'"
     - Row 47: "confirm car trim 'X-Line 2.0L L4 - Gas'"
     - Row 50: "confirm car trim 'X-Line 2.0L L4 - Gas'"
     - Row 61: "confirm car trim 'S 2.0L L4 - Gas'"
     - Row 70: "confirm car trim 'SX 3.3L V6 - Gas'"
     - Row 84: "confirm car trim 'SX Prestige X-Pro 3.8L V6 - Gas'"
     - Row 98: "confirm car trim 'LXS 2.0L L4 - Gas'"
4. Sweep these category paths in priority order:
     a. Electrical → Keyless Entry Components   [primary, every row]
     b. Electrical → Anti-Theft System          [rows 123, 127]
     c. Electrical → Electrical Components      [rows 88, 97]
     d. Related Parts rail on each part page    [rows 83, 117]
5. Capture every PN appearing under any of these case-insensitive labels:
     - "fob smart key"
     - "smart key"
     - "transmitter"
     - "transmitter/tranciever"  ← yes, with that typo
     - "keyless entry transmitter"
     - "remote control"
     - "keyless lock pad"
6. Return all captured PNs. Variants exist because of:
     - Button count (3 vs 4 vs 5 buttons)
     - Prox-equipped vs non-prox
     - Supersession (an old PN replaced by a new one)
```

## PN-count distribution

| PNs found | Rows |
|---|---|
| 1 | 92, 114, 118 |
| 2 | 5, 9, 13, 18, 47, 60, 65, 69, 74, 78, 102, 110, 130 |
| 3 | 22, 38, 52, 56, 83, 97, 106 |
| 4 | 42, 88, 127 |
| 6 | 123 |

This tells us: returning a single "best" PN is wrong. The tool must return all variants and let the locksmith pick by button-count and feature set.

## Category-path coverage by row

- **All 23 rows** require sweeping *Electrical → Keyless Entry Components*.
- **Rows 88, 97** also require *Electrical → Electrical Components* (Telluride, Carnival — newer Kias seem to split keys across two categories).
- **Rows 123, 127** also require *Electrical → Anti-Theft System* (older 2014-era Forte/Optima).
- **Rows 83, 117** also require walking the *Related Parts* rail on a part page to surface additional variants.

## Trim disambiguation appears on roughly a third of VINs

8 out of 23 rows (35%) explicitly call out "confirm trim". The other 15 rows go straight from VIN → category page, meaning the VIN was specific enough to resolve to a single vehicle on the dealer site.

The scraper's `_resolve_trim()` method handles both cases — it only acts when the trim-options DOM element is present.

## Part name vocabulary by model year

Rough pattern observed:

- **2019+** Kias use "fob smart key", "smart key", "transmitter" labels.
- **2014–2018** Kias mix "transmitter" + "keyless entry transmitter".
- **Older** Kias (pre-2014) use "remote control" or "keyless lock pad".
- "Transmitter/tranciever" appears once (row 42) and is just a typo on the dealer page — we still match it.

## What this means for the scraper

The 7-label match set + 4-path category sweep + related-parts walk is *the* algorithm. The CSV is the ground truth. The scraper's correctness measure is: for each of the 23 VINs, do we capture the same set of PNs the human captured?
