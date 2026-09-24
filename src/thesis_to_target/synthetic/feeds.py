"""Rendering ground-truth firms into four messy source feeds and three database indexes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..models import RawRecord
from ..presence import Listing
from .draws import Draws
from .firms import SyntheticFirm, WorldConfig
from .mess import abbreviate, band_label, format_phone, format_website, typo, with_suffix
from .vocabulary import (
    DB_PREFIX,
    DBA_MARKERS,
    FEED_PREFIX,
    FEEDS,
    MIDWEST,
    MIX_WORDS,
    OTHER_STATES,
    RESIDENTIAL_SERVICES,
    TRADES,
)

#: One rendered row before shuffling: (firm id, RawRecord keyword arguments).
Draft = tuple[str, dict[str, Any]]


class FeedRenderer:
    """Turns firms into source rows with realistic coverage gaps and damage."""

    def __init__(self, draws: Draws, cfg: WorldConfig) -> None:
        """Start with empty feeds."""
        self.draws = draws
        self.cfg = cfg
        self.drafts: dict[str, list[Draft]] = {feed: [] for feed in FEEDS}
        self._parents = 0

    def _emit(self, feed: str, firm: SyntheticFirm, **fields: Any) -> None:
        self.drafts[feed].append((firm.firm_id, fields))

    def registry(self, firm: SyntheticFirm) -> None:
        """Business-registry row: legal names, often in capitals, holding-company DBAs."""
        d, cfg = self.draws, self.cfg
        name, dba = firm.legal_name, None
        if firm.holding:
            if d.chance(cfg.inline_dba_share):
                name = f"{firm.legal_name} {d.choice(DBA_MARKERS)} {firm.name}"
            else:
                dba = firm.name
        upper = d.chance(cfg.registry_upper_share)
        attrs: dict[str, Any] = {
            "formation_year": firm.founded + d.integer(0, cfg.formation_lag_years),
            "entity_status": "Active",
        }
        if d.chance(cfg.naics_coverage):
            attrs["naics"] = TRADES[firm.trade].naics
        if d.chance(cfg.band_coverage):
            attrs["employee_band"] = band_label(firm.employees, d, cfg.band_noise)
        if firm.parent_owned:
            self._parents += 1
            attrs["parent_entity"] = f"Parent Entity {self._parents:02d} (synthetic)"
        zip4 = d.chance(cfg.zip4_share)
        self._emit(
            "business_registry",
            firm,
            name=name.upper() if upper else name,
            dba=dba.upper() if (dba and upper) else dba,
            city=firm.city.upper() if upper else firm.city,
            state=firm.state,
            zip=f"{firm.zip}-{d.integer(1000, 9999)}" if zip4 else firm.zip,
            attributes=attrs,
        )

    def license_roll(self, firm: SyntheticFirm) -> None:
        """State license-roll row: sector licenses and licensed-technician counts."""
        d, cfg = self.draws, self.cfg
        use_legal = d.chance(cfg.license_legal_name_share) and not firm.holding
        name = firm.legal_name if use_legal else firm.name
        if d.chance(cfg.license_abbreviation_share):
            name = abbreviate(name, d, cfg.max_abbreviated_words)
        self._emit(
            "state_license",
            firm,
            name=name.upper() if d.chance(cfg.license_upper_share) else name,
            city=firm.city,
            state=firm.state,
            zip=firm.zip,
            phone=format_phone(firm.phone, d) if d.chance(cfg.license_phone_share) else None,
            attributes={
                "license_type": TRADES[firm.trade].license,
                "license_status": "Active" if d.chance(cfg.license_active_share) else "Expired",
                "licensed_technicians": max(
                    1, round(firm.licensed_techs * d.uniform(*cfg.roster_lag))
                ),
            },
        )

    def _listing_name(self, firm: SyntheticFirm) -> str:
        d, cfg = self.draws, self.cfg
        name = firm.name
        if d.chance(cfg.drop_word_share) and len(name.split()) >= 3:
            name = " ".join(name.split()[:-1])
        if d.chance(cfg.abbreviation_share):
            name = abbreviate(name, d, cfg.max_abbreviated_words)
        if d.chance(cfg.typo_share):
            name = typo(name, d, cfg.typo_swap_share)
        if d.chance(cfg.web_suffix_share):
            name = with_suffix(name, d)
        return name

    def _listing_attributes(self, firm: SyntheticFirm) -> dict[str, Any]:
        d, cfg, trade = self.draws, self.cfg, TRADES[firm.trade]
        services = d.sample(trade.services, cfg.listing_services)
        services += d.sample(MIX_WORDS[firm.service_mix], d.integer(*cfg.mix_phrases_per_listing))
        if firm.residential_only and firm.in_sector:
            services += list(RESIDENTIAL_SERVICES)
        attrs: dict[str, Any] = {"listing_category": trade.category, "services": services}
        if d.chance(cfg.stated_headcount_share):
            attrs["stated_headcount"] = max(
                1, round(firm.employees * d.uniform(*cfg.stated_headcount_noise))
            )
        if firm.branches > 1 and d.chance(cfg.locations_share):
            attrs["locations"] = firm.branches
        return attrs

    def web_listing(self, firm: SyntheticFirm) -> None:
        """Web-listing row: operating names with the most damage, services and size hints."""
        d, cfg = self.draws, self.cfg
        name = self._listing_name(firm)
        attrs = self._listing_attributes(firm)
        use_alt = firm.alt_phone is not None and d.chance(cfg.web_alt_phone_share)
        phone = firm.alt_phone if use_alt and firm.alt_phone else firm.phone
        zip_share, phone_share, site_share = cfg.web_field_shares
        self._emit(
            "web_listing",
            firm,
            name=name,
            city=firm.city,
            state=firm.state,
            zip=firm.zip if d.chance(zip_share) else None,
            phone=format_phone(phone, d) if d.chance(phone_share) else None,
            website=format_website(firm.domain, d)
            if (firm.domain and d.chance(site_share))
            else None,
            attributes=attrs,
        )

    def association(self, firm: SyntheticFirm) -> None:
        """Trade-association directory row."""
        d, cfg = self.draws, self.cfg
        and_share, suffix_share = cfg.association_name_shares
        phone_share, site_share = cfg.association_field_shares
        first_year, last_year = cfg.association_years
        name = firm.name.replace(" & ", " and ") if d.chance(and_share) else firm.name
        if d.chance(suffix_share):
            name = with_suffix(name, d)
        self._emit(
            "trade_association",
            firm,
            name=name,
            city=firm.city,
            state=firm.state,
            phone=format_phone(firm.phone, d) if d.chance(phone_share) else None,
            website=format_website(firm.domain, d)
            if (firm.domain and d.chance(site_share))
            else None,
            attributes={
                "services": d.sample(TRADES[firm.trade].services, cfg.directory_services),
                "member_since": d.integer(max(firm.founded, first_year), last_year),
            },
        )

    def render(self, firms: Sequence[SyntheticFirm]) -> None:
        """Render every firm into the feeds that would plausibly list it."""
        d, cfg = self.draws, self.cfg
        for firm in firms:
            trade = TRADES[firm.trade]
            before = sum(len(v) for v in self.drafts.values())
            if d.chance(cfg.registry_coverage):
                self.registry(firm)
            license_p = cfg.license_coverage[0] if firm.in_sector else cfg.license_coverage[1]
            if trade.license and d.chance(license_p):
                self.license_roll(firm)
            if d.chance(cfg.web_coverage[0] if firm.domain else cfg.web_coverage[1]):
                for _ in range(2 if d.chance(cfg.duplicate_listing_share) else 1):
                    self.web_listing(firm)
            base, bonus = cfg.association_rate
            large = firm.employees >= cfg.association_large_employees
            if firm.in_sector and d.chance(base + bonus * large):
                self.association(firm)
            if sum(len(v) for v in self.drafts.values()) == before:
                self.web_listing(firm)  # every firm is visible somewhere

    def finalize(self) -> tuple[dict[str, list[RawRecord]], dict[str, str]]:
        """Shuffle each feed, assign record ids, and return records plus record -> firm truth."""
        records: dict[str, list[RawRecord]] = {}
        truth: dict[str, str] = {}
        for feed in FEEDS:
            rows = []
            for i, (firm_id, fields) in enumerate(self.draws.shuffled(self.drafts[feed]), start=1):
                record_id = f"{FEED_PREFIX[feed]}-{i:04d}"
                truth[record_id] = firm_id
                rows.append(RawRecord(record_id=record_id, source=feed, **fields))
            records[feed] = rows
        return records, truth


def render_listings(
    firms: Sequence[SyntheticFirm], draws: Draws, cfg: WorldConfig, spare_cores: list[str]
) -> dict[str, list[Listing]]:
    """Render each database's listings, including firms outside the world.

    Args:
        firms: Ground-truth firms.
        draws: Random source.
        cfg: Generator knobs, including the per-database presence models.
        spare_cores: Unused name cores; distractor listings consume them.

    Returns:
        Database name -> listings in random order.
    """
    in_sector = [t for t in TRADES.values() if t.in_sector]
    listings: dict[str, list[Listing]] = {}
    for model in cfg.presence_models:
        rows: list[tuple[str, str]] = []
        for firm in firms:
            if not firm.in_db[model.database]:
                continue
            listed = draws.choice(
                (firm.name, firm.name, firm.name if firm.holding else firm.legal_name)
            )
            if draws.chance(cfg.abbreviation_share):
                listed = abbreviate(listed, draws, cfg.max_abbreviated_words)
            if draws.chance(cfg.listing_typo_share):
                listed = typo(listed, draws, cfg.typo_swap_share)
            rows.append((listed, firm.state))
        for _ in range(cfg.distractor_listings):
            trade = draws.choice(in_sector)
            rows.append(
                (
                    f"{spare_cores.pop()} {draws.choice(trade.phrases)}",
                    draws.choice(MIDWEST + OTHER_STATES),
                )
            )
        prefix = DB_PREFIX.get(model.database, model.database[:3].upper())
        listings[model.database] = [
            Listing(f"{prefix}-{i:04d}", name, state)
            for i, (name, state) in enumerate(draws.shuffled(rows), start=1)
        ]
    return listings
