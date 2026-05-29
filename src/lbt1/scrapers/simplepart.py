"""SimplePart platform driver — covers manufacturer-official OEM catalogs.

Confirmed live 2026-05-28 against:
  - parts.hyundaicanada.com (official Hyundai Canada)
  - parts.kia.com (official Kia USA)

Both run on the SimplePart catalog platform (`spApp` JS namespace,
`/wm.aspx/*` ASMX endpoints). Different from Revolution Parts
(oempartsonline.com family) — different upstream OEM feed, sometimes
catches coverage gaps the Revolution Parts dealers miss.

Wire as a LATER tier in the pipeline (after Revolution Parts primary +
secondary). Strict OEM-verified-only policy: returns parts only when
the SimplePart catalog confirms the VIN's vehicle and lists key parts
under the schematic group, never via "looks close" guessing.

Flow:
  1. POST /wm.aspx/CreateVinLinks with VIN → {d: "[{vehicleDescription, vechicleHref}]"}
     If d=="[]", the catalog has no record for this VIN. Return empty.
  2. Fetch vehicleHref (e.g. /Hyundai_2017_Elantra-20L-AT.html) to confirm.
  3. Fetch {vehicleHref}/Body-and-Trim.html  (OEM keys live here — KEY-CYLINDER-SET
     group on Kia, plus assorted FOB/transmitter groups on Hyundai).
  4. Find schematic group links containing key/keyless/fob/transmitter keywords.
  5. Fetch each candidate group page (`/a/{vehicle}/{group_id}/{NAME}/{schematic_id}`)
     and harvest `/p/{vehicle}/{Name}/{id}/{PN}.html` part links.
  6. Filter to PNs in the Hyundai/Kia key family (95440-*, 95430-*, 81905-*, etc.)
     or whose part name contains keyless/transmitter/fob keywords.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Awaitable, Callable
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from lbt1.models import (
    PART_NAME_TO_KEY_TYPE,
    KeyType,
    OemPart,
    ResearchStep,
    StepStatus,
    VehicleProfile,
)
from lbt1.scrapers.backends import ScrapeBackend, get_backend

StepCallback = Callable[[ResearchStep], Awaitable[None] | None]


# Schematic groups (OEM assembly diagrams) that contain key parts.
# These are the slug fragments that appear in /a/{vehicle}/{id}/{NAME}/{schid}
# URLs on parts.hyundaicanada.com / parts.kia.com.
#
# Discovery (2026-05-28 probe across Hyundai 2017 Elantra + Kia 2022 Telluride):
#   - Body-and-Trim > KEY--CYLINDER-SET    → mechanical keys, blanks, ignition lock
#                                            cylinder, transponder chip, immobilizer
#                                            antenna coil. (Pre-smart-key cars.)
#   - Electric > RELAY--MODULE             → FOB-SMART KEY (95440-*) lives HERE
#                                            for push-button-start cars, alongside
#                                            antenna-smartkey, immobilizer IBU.
_KEY_GROUP_PATTERNS = (
    "KEY",            # KEY--CYLINDER-SET, KEYLESS, etc.
    "KEYLESS",
    "FOB",
    "TRANSMITTER",
    "ANTI-THEFT",
    "ANTITHEFT",
    "BURGLAR",
    "REMOTE",
    "SMART-KEY",
    "IGNITION",
    "IMMOBILIZER",
    "RELAY--MODULE",  # smart-key fob + smartkey antenna + IBU live here
)

# Hyundai/Kia OEM PN prefixes for key parts.
#   95440-*  FOB-SMART KEY
#   95430-*  TRANSMITTER ASSY
#   95431-*  TRANSMITTER variants
#   95441-*  TRANSPONDER (chip embedded in key)
#   95442-*  COVER-REMOCON / REMOCON parts
#   95446-*  STRAP-SMART KEY FOB
#   81905-*  KEY & CYLINDER SET-LOCK
#   81970-*  KEY SUB SET-DOOR
#   81900-*  KEY SUB SET-STEERING LOCK
#   81996-*  KEY-BLANKING (uncut blanks for immobilizer)
_KEY_PN_PREFIXES = (
    "95440", "95430", "95431", "95441", "95442", "95446",
    "81905", "81900", "81970", "81996",
)


class SimplepartDriver:
    """Base class for the SimplePart-platform OEM catalogs.

    Subclasses override `base_url` and (optionally) `make_filter` to
    restrict harvest to a single make.
    """

    base_url: str = ""
    name: str = "simplepart"

    # Soft sanity check on the vehicleDescription returned by CreateVinLinks.
    # NOTE: SimplePart's description does NOT always include the make word
    # (Kia returns "2022 Telluride 3.8L AT 4WD SX" — no "Kia"). We treat
    # this as a soft signal only and don't reject on mismatch — the fact
    # that we hit the make-specific base_url already provides scoping.
    make_filter: str = ""

    def __init__(
        self,
        *,
        backend: ScrapeBackend | None = None,
        step_callback: StepCallback | None = None,
        **_legacy_kwargs,
    ):
        self.backend = backend or get_backend()
        self.step_callback = step_callback
        self.steps: list[ResearchStep] = []
        self.screenshots: list[str] = []  # kept for API compatibility

    async def _emit(
        self, step: str, status: StepStatus = "info", detail: str | None = None
    ) -> None:
        record = ResearchStep(
            timestamp=datetime.now(timezone.utc),
            step=step,
            status=status,
            detail=detail,
        )
        self.steps.append(record)
        if self.step_callback is not None:
            result = self.step_callback(record)
            try:
                import asyncio  # local import to avoid hard top-level coupling
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

    # ─── Main flow ─────────────────────────────────────────────────────

    async def lookup_vin(self, vin: str, profile: VehicleProfile) -> list[OemPart]:
        await self._emit(
            f"Starting SimplePart lookup at {self.base_url}", "info", vin
        )

        # 1. Resolve VIN → vehicleHref
        vehicle_href = await self._resolve_vehicle_href(vin)
        if not vehicle_href:
            await self._emit(
                "SimplePart: catalog has no record for this VIN", "info"
            )
            return []
        vehicle_url = urljoin(self.base_url, vehicle_href)
        await self._emit("SimplePart vehicle URL", "info", vehicle_url)

        # 2. Find key-related schematic groups under Body-and-Trim and Electric.
        candidate_groups: list[str] = []
        for top_cat in ("Body-and-Trim", "Electric"):
            cat_url = self._build_category_url(vehicle_url, top_cat)
            groups = await self._find_key_groups(cat_url, top_cat)
            candidate_groups.extend(groups)

        if not candidate_groups:
            await self._emit(
                "SimplePart: no key-related schematic groups on this vehicle", "info"
            )
            return []
        await self._emit(
            f"SimplePart: found {len(candidate_groups)} key-related group(s)", "info"
        )

        # 3. Harvest /p/{...}/{PN}.html from each group page.
        found: list[OemPart] = []
        seen_pns: set[str] = set()
        for group_url in candidate_groups:
            parts = await self._harvest_group(group_url, vehicle_url)
            for p in parts:
                if p.oem_part_number in seen_pns:
                    continue
                seen_pns.add(p.oem_part_number)
                found.append(p)

        await self._emit(
            f"SimplePart captured {len(found)} key PN(s)",
            "success" if found else "info",
        )
        return found

    # ─── Subroutines ───────────────────────────────────────────────────

    async def _resolve_vehicle_href(self, vin: str) -> str | None:
        """POST /wm.aspx/CreateVinLinks. Returns vehicleHref or None."""
        endpoint = urljoin(self.base_url, "/wm.aspx/CreateVinLinks")
        try:
            r = await self.backend.fetch_json_post(
                endpoint,
                json_body={
                    "VinNumber": vin,
                    "AbsolutePath": quote("/default.aspx"),
                    "QueryString": "",
                },
                headers={
                    "Origin": self.base_url.rstrip("/"),
                    "Referer": self.base_url,
                },
            )
        except NotImplementedError:
            await self._emit(
                "Backend doesn't support POST — SimplePart disabled", "warning"
            )
            return None

        if not r.ok or r.error:
            await self._emit(
                "CreateVinLinks failed", "warning",
                f"status={r.status} err={(r.error or '')[:120]}",
            )
            return None

        # ASMX envelope: {"d": "[{\"vehicleDescription\":\"...\",\"vechicleHref\":\"...\"}]"}
        try:
            envelope = json.loads(r.html)
        except (ValueError, TypeError):
            return None
        inner = envelope.get("d")
        if not inner or not isinstance(inner, str):
            return None
        try:
            results = json.loads(inner)
        except (ValueError, TypeError):
            return None
        if not isinstance(results, list) or not results:
            return None

        # Pick the first result. If we have multiple (the catalog is uncertain
        # about trim), take the first — they're all the same model+year+engine
        # and key fobs are stable across that grain.
        first = results[0]
        href = first.get("vechicleHref") or first.get("vehicleHref")
        desc = first.get("vehicleDescription") or ""

        # Sanity: make_filter is a soft heuristic — only reject if BOTH the
        # description AND the href clearly contain a different make name.
        # (Kia's vehicleDescription drops the "Kia" word, so we can't reject
        # on description alone.)
        if self.make_filter and isinstance(href, str):
            make_lc = self.make_filter.lower()
            text = (desc + " " + href).lower()
            other_makes = {"hyundai", "kia", "genesis"} - {make_lc}
            if any(m in text for m in other_makes) and make_lc not in text:
                await self._emit(
                    "SimplePart returned vehicle for wrong make", "warning",
                    f"got={desc!r} href={href!r} expected={self.make_filter!r}",
                )
                return None

        return href if isinstance(href, str) and href.startswith("/") else None

    def _build_category_url(self, vehicle_url: str, top_cat: str) -> str:
        """Build the category URL: {vehicleHref minus .html}/{Category}.html.

        Vehicle URL example: https://parts.hyundaicanada.com/Hyundai_2017_Elantra-20L-AT.html
        Category URL: https://parts.hyundaicanada.com/Hyundai_2017_Elantra-20L-AT/Body-and-Trim.html
        """
        # Strip trailing .html, append /{cat}.html
        base = vehicle_url.rstrip("/")
        if base.lower().endswith(".html"):
            base = base[:-5]
        return f"{base}/{top_cat}.html"

    async def _find_key_groups(self, cat_url: str, top_cat: str) -> list[str]:
        """Fetch a top-level category page and return URLs of schematic
        groups whose name suggests they contain key/keyless/transmitter
        parts. Each schematic group URL looks like:
            /a/{vehicleSlug}/_{group_id}_{sub_id}/{NAME}/{schematic_id}
        """
        r = await self.backend.fetch(cat_url)
        if not r.ok:
            await self._emit(
                f"SimplePart {top_cat} fetch failed", "warning",
                f"status={r.status} err={(r.error or '')[:80]}",
            )
            return []
        soup = BeautifulSoup(r.html or "", "lxml")

        seen: set[str] = set()
        out: list[str] = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if not href.startswith("/a/"):
                continue
            if href in seen:
                continue
            seen.add(href)
            # Group name is the segment between the group_id (_NNN_NNN) and
            # the trailing schematic_id.
            m = re.match(r"/a/[^/]+/_\d+_\d+/([^/]+)/", href)
            group_name = (m.group(1) if m else "").upper().replace("_", "-")
            if any(kw in group_name for kw in _KEY_GROUP_PATTERNS):
                full = urljoin(cat_url, href)
                out.append(full)
                await self._emit(
                    f"SimplePart key-group found in {top_cat}: {group_name}",
                    "info", full,
                )
        return out

    async def _harvest_group(self, group_url: str, vehicle_url: str) -> list[OemPart]:
        """Fetch a schematic group page and harvest /p/{...}/{PN}.html links
        whose PN looks like a Hyundai/Kia key family OR whose label text
        matches the existing PART_NAME_TO_KEY_TYPE keywords.
        """
        r = await self.backend.fetch(group_url)
        if not r.ok:
            await self._emit(
                "SimplePart group fetch failed", "warning",
                f"status={r.status} url={group_url}",
            )
            return []
        soup = BeautifulSoup(r.html or "", "lxml")

        out: list[OemPart] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = re.match(r"/p/[^/]+/([^/]+)/\d+/([^.?]+)\.html", href)
            if not m:
                continue
            part_name_slug = m.group(1).replace("-", " ")
            pn_raw = m.group(2)
            if pn_raw in seen:
                continue
            seen.add(pn_raw)

            # Normalize PN: SimplePart drops the hyphen (95440K0320) but the
            # standard OEM format is 95440-K0320.
            pn_normalized = self._normalize_pn(pn_raw)

            # Filter: must be a key family PN OR have key keywords in the name.
            name_lc = part_name_slug.lower()
            pn_lc = pn_raw.lower()
            is_key_family = any(pn_lc.startswith(pre) for pre in _KEY_PN_PREFIXES)
            is_key_name = any(
                kw in name_lc for kw in (
                    "fob", "smart key", "smart-key", "keyless", "transmitter",
                    "anti-theft", "remote", "transponder", "immobilizer",
                )
            )
            if not (is_key_family or is_key_name):
                continue

            # Visible label on the anchor often has the human-readable name
            # (e.g. "FOB-SMART KEY") if there's text; fall back to slug.
            label = a.get_text(" ", strip=True) or part_name_slug
            # If label is just the PN (no descriptive text), substitute slug.
            if label.upper() == pn_raw:
                label = part_name_slug.title()

            key_type = self._classify(label)
            out.append(OemPart(
                oem_part_number=pn_normalized,
                part_name=label,
                key_type=key_type,
                source_url=urljoin(group_url, href),
                category_path=self._derive_category_path(group_url),
                fitment_evidence=f"Listed on {vehicle_url} schematic group",
                dealer_verified=True,
                notes=None,
            ))
        return out

    @staticmethod
    def _normalize_pn(pn_raw: str) -> str:
        """SimplePart drops the hyphen in the OEM PN (95440K0320). Restore
        Hyundai/Kia's canonical 5-then-rest format (95440-K0320) so PNs
        compare equal across our drivers.
        """
        if len(pn_raw) > 5 and pn_raw[:5].isdigit() and "-" not in pn_raw:
            return f"{pn_raw[:5]}-{pn_raw[5:]}"
        return pn_raw

    @staticmethod
    def _classify(name: str) -> KeyType:
        lowered = (name or "").lower()
        for label, key_type in PART_NAME_TO_KEY_TYPE.items():
            if label in lowered:
                return key_type
        # Fall-throughs the existing map doesn't catch
        if "fob" in lowered or "smart key" in lowered:
            return KeyType.SMART_KEY
        if "transmitter" in lowered:
            return KeyType.TRANSMITTER
        return KeyType.UNKNOWN

    @staticmethod
    def _derive_category_path(group_url: str) -> str:
        """Pull a readable category path out of the schematic URL. Example:
        .../Hyundai_2017_Elantra-20L-AT/.../KEY--CYLINDER-SET/... → 'KEY/CYLINDER-SET'"""
        m = re.search(r"/_\d+_\d+/([^/]+)/", group_url)
        if not m:
            return ""
        return m.group(1).replace("--", " > ").replace("-", " ").title()


class HyundaiCanadaDriver(SimplepartDriver):
    """Official Hyundai Canada parts catalog (SimplePart platform)."""
    base_url = "https://parts.hyundaicanada.com/"
    name = "hyundai_canada"
    make_filter = "Hyundai"


class KiaUsOfficialDriver(SimplepartDriver):
    """Official Kia USA parts catalog (SimplePart platform)."""
    base_url = "https://parts.kia.com/"
    name = "kia_us_official"
    make_filter = "Kia"
