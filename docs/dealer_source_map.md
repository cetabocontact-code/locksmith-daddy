# Dealer Source Map — by Make

Compiled 2026-05-29 from two locksmith-industry guides:
- americankeysupply.com (AKS) — finding OEM parts by VIN guide
- northcoastkeyless.com (NCK) — OEM key fob VIN lookup guide

This is the master roadmap for multi-make expansion. Each make has the
recommended dealer site + the exact category breadcrumb where fobs live.

## Confirmed mappings

| Make | Category (per AKS) | AKS source | NCK source | Notes |
|---|---|---|---|---|
| **Hyundai** | Electrical > Keyless Entry Components | hyundaioemparts.com | hyundaipartsdeal.com | ✅ Matches our current Revolution Parts driver |
| **Kia** | Electrical > Keyless Entry Components (Kia 2)<br>Trim > Key & Cylinder Set (Kia 1) | kiapartsnow.com, kiaparts.com | kiapartsnow.com | ✅ Matches our current driver |
| **Genesis** | (not listed — group with Hyundai) | — | — | TBD |
| **Toyota / Lexus** | Body > Lock Cylinder Set | toyotapartsdeal.com | toyotapartsdeal.com | ⚠ JS-rendered SPA — needs investigation |
| **Honda / Acura** | Electrical > Combination Switch | acurapartsnow.com<br>hondapartsnow.com | acurapartswarehouse.com<br>hondapartsnow.com | Future |
| **Ford** | Electronics & Telematics > Electronic Accessories > Keyless Entry Key Fob | fordparts.com | fordpartsgiant.com | Future |
| **Lincoln** | (Ford group) | — | fordpartsgiant.com/lincoln-parts.html | Future |
| **GM** (Buick/Cadillac/Chevy/GMC) | Electrical > Keyless Entry Components<br>OR Tires/Accessories > Electronics A/V and Mirrors | parts-catalog.acdelco.com | gmpartsgiant.com | Future |
| **Chrysler / Dodge / Jeep / RAM** | Electrical > Keyless Entry Components | moparpartsgiant.com | moparpartsgiant.com | Future |
| **Nissan / Infiniti** | Body Electrical > Electrical Unit > Switch Assy-Smart Keyless | parts.infinitiusa.com<br>nissanpartsdeal.com | infinitipartsdeal.com<br>nissanpartsdeal.com | Future |
| **Mazda** | Electrical > Keyless Entry Components > Transmitter | mazda-parts-dealer.com | (not listed) | Future |
| **Mitsubishi** | Electrical > Keyless Entry Components > Transmitter | mitsubishiparts.com | (not listed) | Future |
| **Subaru** | Subaru Genuine Accessories > Exterior | parts.subaru.com | subarupartsdeal.com | Future |
| **Volkswagen** | Electrical > Keyless Entry Components<br>OR Accessories > Accessories & Wheels | eeuroparts.com | (not listed) | Future |
| **Scion** | (Toyota group) | — | toyotapartsdeal.com/scion-parts.html | Future (legacy brand) |

## Platform clusters observed

**RevolutionParts family** (uniform CMS — `.marketplace-info-col` cards):
- hyundai.oempartsonline.com ✅ wired
- hyundaioempart.com ✅ wired
- kia.oempartsonline.com ✅ wired
- genesis.oempartsonline.com ✅ wired
- toyota.oempartsonline.com ✅ wired (no fobs — dealer restriction)
- Many dealer-named domains

**SimplePart** (manufacturer-direct, `spApp` namespace, `/wm.aspx/*` API):
- parts.hyundaicanada.com ✅ wired
- parts.kia.com ✅ wired
- parts.toyota.com (autoparts.toyota.com — TBD)
- parts.genesis.com (TBD)

**"PartsDeal/PartsNow/PartsGiant" family** (looks like same operator,
all custom SPA CMS with JS-rendered VIN search):
- toyotapartsdeal.com, lexuspartsnow.com, scionpartsdeal.com (Toyota Group)
- hondapartsnow.com, acurapartsnow.com, acurapartswarehouse.com (Honda)
- hyundaipartsdeal.com, hyundaipartsnow.com (Hyundai aftermarket)
- kiapartsnow.com (Kia)
- nissanpartsdeal.com, infinitipartsdeal.com (Nissan)
- gmpartsgiant.com, fordpartsgiant.com, moparpartsgiant.com (Big-3 Detroit)
- subarupartsdeal.com (Subaru)

**Mopar/GM custom catalogs**:
- parts-catalog.acdelco.com (GM)
- moparpartsgiant.com (Chrysler/Dodge/Jeep/RAM — also part of PartsGiant family)
- fordparts.com (Ford official)
- parts.infinitiusa.com (Infiniti official)

## What this means for our roadmap

1. **The PartsDeal/PartsGiant family is the multi-make unlock.** If we
   reverse-engineer their VIN AJAX endpoint once (similar to how we found
   SimplePart's `/wm.aspx/CreateVinLinks`), it gives us Toyota, Honda,
   Subaru, Nissan, Lexus, Acura, GM, Ford, Chrysler — all in one driver
   class with different `base_url` per make.

2. **Toyota fobs need toyotapartsdeal.com specifically** because
   toyota.oempartsonline.com (Revolution Parts) doesn't sell them —
   smart keys require dealer programming and are restricted at the
   Revolution Parts catalog level.

3. **Honda/Acura is most similar to Hyundai/Kia** — both Revolution Parts
   and the PartsNow family carry them. Likely easiest add after Toyota.
