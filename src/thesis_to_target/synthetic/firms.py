"""Ground-truth firms of the synthetic world: configuration, capacity limits and generation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..config import SyntheticSettings
from ..errors import CapacityError
from .draws import Draws
from .mess import with_suffix
from .vocabulary import (
    AREA_CODES,
    CORE_HEADS,
    CORE_TAILS,
    FICTIONAL_LINES,
    FICTIONAL_TLD,
    HOLDING_FORMS,
    LOOK_ALIKE_TRADES,
    MIDWEST,
    MIXES,
    OTHER_STATES,
    RESIDENTIAL_TRADE,
    TOWN_HEADS,
    TOWN_TAILS,
    TRADES,
    TRUE_MARGIN,
    ZIP_PREFIX,
)

# Each firm uses at most two phone lines (main and alternate).
_LINES_PER_FIRM = 2


@dataclass(frozen=True)
class PresenceModel:
    """Logistic model of whether a firm is listed in one database.

    ``P(listed) = logistic(intercept + log_employee_slope * ln(employees)
    + website_coef * has_website + visibility_coef * visibility)``.

    Attributes:
        database: Database name.
        intercept: Logistic intercept.
        log_employee_slope: Effect of log headcount (bigger firms are listed more).
        website_coef: Effect of having a website.
        visibility_coef: Effect of the firm's latent visibility (shared across databases).
    """

    database: str
    intercept: float
    log_employee_slope: float
    website_coef: float
    visibility_coef: float


@dataclass(frozen=True)
class WorldConfig:
    """Knobs of the synthetic generator; probabilities are per firm or per record.

    Attributes:
        midwest_share: Share of firms placed in the thesis geography.
        employee_median: Median headcount of generated firms.
        employee_log_sigma: Spread of ln(headcount).
        employee_bounds: Minimum and maximum headcount.
        holding_share: Share of firms registered under an unrelated holding name.
        alt_phone_share: Share of firms with a second phone line.
        parent_owned_share: Share of in-sector firms with a parent owner.
        residential_share: Share of in-sector firms that serve homeowners only.
        rpe_log_sigma: Firm-to-firm spread of ln(revenue per employee).
        founded_bounds: Earliest and latest founding year.
        branch_divisor: Range of employees per branch.
        licensed_share: Range of the licensed share of employees.
        website_curve: Base, slope on ln(employees / 10), minimum and maximum of P(website).
        registry_coverage: P(firm appears in the business registry).
        naics_coverage: P(registry record carries a NAICS code).
        band_coverage: P(registry record carries an employee band).
        band_noise: P(reported band is one band off).
        registry_upper_share: P(registry prints the record in capitals).
        inline_dba_share: P(a holding firm's DBA is printed inside the name field).
        zip4_share: P(ZIP printed as ZIP+4).
        formation_lag_years: Registration may trail founding by up to this many years.
        license_coverage: P(licensed in-sector firm / licensed adjacent firm is on the roll).
        license_active_share: P(license is active).
        license_legal_name_share: P(license roll prints the legal name).
        license_abbreviation_share: P(license roll abbreviates the name).
        license_upper_share: P(license roll prints the name in capitals).
        license_phone_share: P(license roll carries a phone).
        roster_lag: Range of the licensed-roster count as a share of the true count.
        web_coverage: P(web listing) for firms with / without a website.
        duplicate_listing_share: P(firm has two web listings).
        drop_word_share: P(web listing drops the last word of the name).
        abbreviation_share: P(web listing abbreviates words).
        max_abbreviated_words: Most words abbreviated in one name.
        typo_share: P(web listing contains a typo).
        typo_swap_share: P(a typo swaps two letters rather than dropping one).
        web_suffix_share: P(web listing appends a legal suffix).
        web_alt_phone_share: P(web listing shows the second phone line).
        web_field_shares: P(web listing carries a ZIP, a phone, a website).
        listing_services: Service phrases shown per web listing.
        mix_phrases_per_listing: Fewest and most service-mix phrases per web listing.
        stated_headcount_share: P(web listing states a headcount).
        stated_headcount_noise: Range of the stated headcount as a share of the truth.
        locations_share: P(multi-branch firm's listing states its locations).
        association_rate: Base P(association membership) and bonus for larger firms.
        association_large_employees: Headcount at which the bonus applies.
        association_name_shares: P(directory swaps "&" for "and"; appends a suffix).
        association_field_shares: P(directory carries a phone; a website).
        association_years: Earliest and latest membership year.
        directory_services: Service phrases shown per association entry.
        sister_every: One same-core look-alike firm per this many firms.
        namesake_every: One same-name firm in another state per this many firms.
        distractor_listings: Listings per database for firms outside the world.
        listing_typo_share: P(database listing contains a typo).
        presence_models: One logistic listing model per database.
    """

    midwest_share: float = 0.80
    employee_median: float = 38.0
    employee_log_sigma: float = 0.85
    employee_bounds: tuple[int, int] = (3, 420)
    holding_share: float = 0.15
    alt_phone_share: float = 0.20
    parent_owned_share: float = 0.08
    residential_share: float = 0.04
    rpe_log_sigma: float = 0.12
    founded_bounds: tuple[int, int] = (1962, 2019)
    branch_divisor: tuple[float, float] = (30.0, 80.0)
    licensed_share: tuple[float, float] = (0.25, 0.50)
    website_curve: tuple[float, float, float, float] = (0.35, 0.15, 0.30, 0.95)
    registry_coverage: float = 0.92
    naics_coverage: float = 0.90
    band_coverage: float = 0.60
    band_noise: float = 0.20
    registry_upper_share: float = 0.60
    inline_dba_share: float = 0.50
    zip4_share: float = 0.30
    formation_lag_years: int = 2
    license_coverage: tuple[float, float] = (0.80, 0.15)
    license_active_share: float = 0.92
    license_legal_name_share: float = 0.60
    license_abbreviation_share: float = 0.20
    license_upper_share: float = 0.50
    license_phone_share: float = 0.50
    roster_lag: tuple[float, float] = (0.80, 1.00)
    web_coverage: tuple[float, float] = (0.85, 0.55)
    duplicate_listing_share: float = 0.08
    drop_word_share: float = 0.15
    abbreviation_share: float = 0.15
    max_abbreviated_words: int = 2
    typo_share: float = 0.08
    typo_swap_share: float = 0.50
    web_suffix_share: float = 0.25
    web_alt_phone_share: float = 0.30
    web_field_shares: tuple[float, float, float] = (0.60, 0.95, 0.90)
    listing_services: int = 3
    mix_phrases_per_listing: tuple[int, int] = (1, 2)
    stated_headcount_share: float = 0.35
    stated_headcount_noise: tuple[float, float] = (0.85, 1.20)
    locations_share: float = 0.70
    association_rate: tuple[float, float] = (0.25, 0.30)
    association_large_employees: int = 40
    association_name_shares: tuple[float, float] = (0.30, 0.30)
    association_field_shares: tuple[float, float] = (0.60, 0.50)
    association_years: tuple[int, int] = (1985, 2023)
    directory_services: int = 2
    sister_every: int = 20
    namesake_every: int = 30
    distractor_listings: int = 25
    listing_typo_share: float = 0.05
    presence_models: tuple[PresenceModel, ...] = (
        PresenceModel("commercial_db_a", -5.2, 1.1, 0.5, 1.4),
        PresenceModel("commercial_db_b", -5.6, 1.1, 0.4, 1.4),
        PresenceModel("investor_db", -7.2, 1.2, 0.0, 1.4),
    )

    def look_alikes(self, n_firms: int) -> tuple[int, int]:
        """Number of same-town and same-name look-alike firms planted for ``n_firms``."""
        return max(1, n_firms // self.sister_every), max(1, n_firms // self.namesake_every)


@dataclass
class SyntheticFirm:
    """Ground truth for one fictional firm.

    Attributes:
        firm_id: True entity id, e.g. ``"F007"``.
        core: Nonsense syllable word at the start of the name.
        trade: Key into :data:`~.vocabulary.TRADES`.
        name: Operating name.
        legal_name: Registered name (a holding-company name for some firms).
        holding: Whether the legal name is unrelated to the operating name.
        state: Two-letter state code.
        city: Fictional town name.
        zip: Five-digit ZIP code.
        phone: Main ten-digit phone (fictional 555-01XX line).
        alt_phone: Second line, if any.
        domain: Website host on the ``.example`` domain, if any.
        employees: True headcount.
        branches: Number of locations.
        licensed_techs: Licensed individuals.
        service_mix: True service mix.
        founded: Founding year.
        parent_owned: Whether a parent entity owns the firm.
        residential_only: Whether the firm serves homeowners only.
        true_ebitda: True annual EBITDA, USD.
        in_db: Database -> whether the firm is listed there.
    """

    firm_id: str
    core: str
    trade: str
    name: str
    legal_name: str
    holding: bool
    state: str
    city: str
    zip: str
    phone: str
    alt_phone: str | None
    domain: str | None
    employees: int
    branches: int
    licensed_techs: int
    service_mix: str
    founded: int
    parent_owned: bool
    residential_only: bool
    true_ebitda: float
    in_db: dict[str, bool] = field(default_factory=dict)

    @property
    def in_sector(self) -> bool:
        """Whether the firm's trade belongs to the demo thesis."""
        return TRADES[self.trade].in_sector


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _state_capacity_ok(n_firms: int, cfg: WorldConfig) -> bool:
    in_geo = round(n_firms * cfg.midwest_share)
    sisters, namesakes = cfg.look_alikes(n_firms)
    for state, codes in AREA_CODES.items():
        region = MIDWEST if state in MIDWEST else OTHER_STATES
        placed = in_geo if state in MIDWEST else n_firms - in_geo
        # Base firms are spread evenly; in the worst case every look-alike lands here too.
        worst = math.ceil(placed / len(region)) + (sisters + namesakes if state in MIDWEST else 0)
        if _LINES_PER_FIRM * worst > len(codes) * len(FICTIONAL_LINES):
            return False
    return True


def _name_capacity_ok(n_firms: int, cfg: WorldConfig) -> bool:
    sisters, namesakes = cfg.look_alikes(n_firms)
    # One core per base firm, one per holding-company name (worst case: every firm),
    # and one per distractor listing in each database.
    needed = (
        n_firms
        + (n_firms + sisters + namesakes)
        + cfg.distractor_listings * len(cfg.presence_models)
    )
    return needed <= len(CORE_HEADS) * len(CORE_TAILS)


def max_firms(cfg: WorldConfig | None = None) -> int:
    """Largest ``n_firms`` the fixed name and fictional phone pools can always supply."""
    cfg = cfg or WorldConfig()
    n = 1
    while _state_capacity_ok(n + 1, cfg) and _name_capacity_ok(n + 1, cfg):
        n += 1
    return n


def check_capacity(settings: SyntheticSettings, cfg: WorldConfig) -> None:
    """Refuse up front to build a world the pools cannot supply.

    Raises:
        CapacityError: If ``settings.n_firms`` exceeds :func:`max_firms`.
    """
    limit = max_firms(cfg)
    if settings.n_firms > limit:
        raise CapacityError(
            f"n_firms={settings.n_firms} exceeds the synthetic generator's capacity of {limit} "
            "(its fictional name and 555-01XX phone pools are fixed)"
        )


class FirmFactory:
    """Creates firms from shuffled pools of names, towns and fictional phone numbers."""

    def __init__(self, draws: Draws, cfg: WorldConfig) -> None:
        """Shuffle the pools once, from the world's random stream."""
        self.draws = draws
        self.cfg = cfg
        self.cores = draws.shuffled([h + t for h in CORE_HEADS for t in CORE_TAILS])
        self._towns = [h + t for h in TOWN_HEADS for t in TOWN_TAILS]
        self._phones = {
            state: draws.shuffled(
                [f"{code}555{line:04d}" for code in codes for line in FICTIONAL_LINES]
            )
            for state, codes in AREA_CODES.items()
        }
        self.firms: list[SyntheticFirm] = []

    def _employees(self) -> int:
        lo, hi = self.cfg.employee_bounds
        drawn = round(
            math.exp(
                self.draws.normal(math.log(self.cfg.employee_median), self.cfg.employee_log_sigma)
            )
        )
        return int(min(max(drawn, lo), hi))

    def _listed_in(self, employees: int, has_site: bool) -> dict[str, bool]:
        visibility = self.draws.normal()
        return {
            m.database: self.draws.chance(
                _logistic(
                    m.intercept
                    + m.log_employee_slope * math.log(employees)
                    + m.website_coef * has_site
                    + m.visibility_coef * visibility
                )
            )
            for m in self.cfg.presence_models
        }

    def _has_website(self, employees: int) -> bool:
        base, slope, p_min, p_max = self.cfg.website_curve
        return self.draws.chance(min(max(base + slope * math.log(employees / 10), p_min), p_max))

    def add(
        self,
        trade_key: str,
        state: str,
        *,
        core: str | None = None,
        phrase: str | None = None,
        city: str | None = None,
        zip_code: str | None = None,
        domain_suffix: str = "",
    ) -> SyntheticFirm:
        """Create one firm; keyword arguments pin fields to build look-alikes."""
        d, cfg, trade = self.draws, self.cfg, TRADES[trade_key]
        core = core or self.cores.pop()
        name = f"{core} {phrase or d.choice(trade.phrases)}"
        employees = self._employees()
        holding = d.chance(cfg.holding_share)
        legal = f"{self.cores.pop()} {d.choice(HOLDING_FORMS)}" if holding else with_suffix(name, d)
        mix = d.weighted(MIXES, trade.mix_prior)
        rpe = trade.revenue_per_employee * math.exp(d.normal(0.0, cfg.rpe_log_sigma))
        has_site = self._has_website(employees)
        firm = SyntheticFirm(
            firm_id=f"F{len(self.firms) + 1:03d}",
            core=core,
            trade=trade_key,
            name=name,
            legal_name=legal,
            holding=holding,
            state=state,
            city=city or d.choice(self._towns),
            zip=zip_code or f"{ZIP_PREFIX[state]}{d.integer(1, 99):02d}",
            phone=self._phones[state].pop(),
            alt_phone=self._phones[state].pop() if d.chance(cfg.alt_phone_share) else None,
            domain=f"{core.lower()}{trade.web_word}{domain_suffix}.{FICTIONAL_TLD}"
            if has_site
            else None,
            employees=employees,
            branches=max(1, round(employees / d.uniform(*cfg.branch_divisor))),
            licensed_techs=max(1, round(employees * d.uniform(*cfg.licensed_share))),
            service_mix=mix,
            founded=d.integer(*cfg.founded_bounds),
            parent_owned=trade.in_sector and d.chance(cfg.parent_owned_share),
            residential_only=trade_key == RESIDENTIAL_TRADE
            or (trade.in_sector and d.chance(cfg.residential_share)),
            true_ebitda=employees * rpe * d.uniform(*TRUE_MARGIN[mix]),
            in_db=self._listed_in(employees, has_site),
        )
        self.firms.append(firm)
        return firm

    def add_base_firms(self, n_firms: int) -> None:
        """Create ``n_firms`` firms, spread evenly over the in-geography and other states."""
        in_geo = round(n_firms * self.cfg.midwest_share)
        midwest, other = self.draws.shuffled(MIDWEST), self.draws.shuffled(OTHER_STATES)
        states = [midwest[i % len(midwest)] for i in range(in_geo)]
        states += [other[i % len(other)] for i in range(n_firms - in_geo)]
        keys = list(TRADES)
        weights = [TRADES[k].weight for k in keys]
        for state in self.draws.shuffled(states):
            self.add(self.draws.weighted(keys, weights), state)

    def add_look_alikes(self, n_firms: int) -> None:
        """Plant firms that entity resolution must keep apart from their look-alikes."""
        d = self.draws
        anchors = [f for f in self.firms if f.in_sector and f.state in MIDWEST]
        sisters, namesakes = self.cfg.look_alikes(n_firms)
        # Same syllable core, same town, different business.
        for base in d.sample(anchors, sisters):
            self.add(
                d.choice(LOOK_ALIKE_TRADES),
                base.state,
                core=base.core,
                city=base.city,
                zip_code=base.zip,
            )
        # Identical name, different state, unrelated firm.
        for base in d.sample(anchors, namesakes):
            other = d.choice([s for s in MIDWEST if s != base.state])
            phrase = base.name[len(base.core) + 1 :]
            self.add(base.trade, other, core=base.core, phrase=phrase, domain_suffix=other.lower())
        # Two unrelated firms answering the same phone line.
        by_state: dict[str, list[SyntheticFirm]] = {}
        for f in self.firms:
            by_state.setdefault(f.state, []).append(f)
        for state in sorted(by_state):
            first, *rest = by_state[state]
            unrelated = [f for f in rest if f.core != first.core]
            if unrelated:
                unrelated[0].phone = first.phone
                break
