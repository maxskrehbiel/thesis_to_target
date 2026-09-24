"""Fixed vocabulary of the synthetic world: name syllables, places, fictional contacts, trades."""

from __future__ import annotations

from dataclasses import dataclass

# Names are built from nonsense syllables so no generated firm names a real business.
# fmt: off
CORE_HEADS = (
    "Brax", "Quen", "Velt", "Hald", "Ostr", "Pryn", "Zenn", "Carv", "Dovr", "Grel", "Jast",
    "Kivel", "Lomb", "Narv", "Rusk", "Sovr", "Tamb", "Ulv", "Wexl", "Yorv", "Cresk", "Mald",
    "Fyl", "Istr", "Bexl", "Torv", "Hesk", "Pell",
)
CORE_TAILS = (
    "moor", "holt", "mere", "lund", "vane", "stead", "crest", "gard", "wyn", "by", "ridge",
    "haven", "bourne", "field", "ley", "wick", "stow", "combe", "hurst", "worth", "dell",
    "shaw", "thwaite", "rigg",
)
TOWN_HEADS = (
    "Ash", "Bram", "Cold", "Elm", "Glen", "Iron", "Lark", "Mill", "Oak", "Pine", "Red", "Stone",
    "Wil", "Hollow", "Cedar", "Fox",
)
TOWN_TAILS = ("brook", "dale", "field", "ford", "haven", "port", "ton", "ville", "wood", "view")
# fmt: on

MIDWEST = ("IL", "IN", "IA", "KS", "MI", "MN", "MO", "NE", "ND", "OH", "SD", "WI")
OTHER_STATES = ("TX", "GA", "PA", "AZ", "CO", "TN")

# Every phone number uses the 555-0100..0199 lines reserved for fiction.
# fmt: off
AREA_CODES = {
    "IL": ("217", "309"), "IN": ("317", "574"), "IA": ("319", "515"), "KS": ("316", "785"),
    "MI": ("517", "616"), "MN": ("507", "651"), "MO": ("417", "573"), "NE": ("308", "402"),
    "ND": ("701",),       "SD": ("605",),       "OH": ("330", "614"), "WI": ("608", "715"),
    "TX": ("254", "806"), "GA": ("229", "706"), "PA": ("570", "814"), "AZ": ("520", "928"),
    "CO": ("719", "970"), "TN": ("423", "931"),
}
ZIP_PREFIX = {
    "IL": "612", "IN": "473", "IA": "505", "KS": "670", "MI": "490", "MN": "560",
    "MO": "654", "NE": "688", "ND": "585", "SD": "572", "OH": "441", "WI": "535",
    "TX": "765", "GA": "310", "PA": "168", "AZ": "856", "CO": "810", "TN": "373",
}
# fmt: on
FICTIONAL_LINES = range(100, 200)
# Websites use the reserved .example top-level domain (RFC 2606).
FICTIONAL_TLD = "example"

FEEDS = ("state_license", "business_registry", "web_listing", "trade_association")
FEED_PREFIX = {
    "state_license": "LIC",
    "business_registry": "REG",
    "web_listing": "WEB",
    "trade_association": "ASN",
}
DB_PREFIX = {"commercial_db_a": "DBA", "commercial_db_b": "DBB", "investor_db": "INV"}


@dataclass(frozen=True)
class Trade:
    """A kind of business the generator can create.

    Attributes:
        in_sector: Whether the trade belongs to the demo thesis.
        weight: Relative frequency among generated firms.
        phrases: Name endings, e.g. ``"Fire Protection"``.
        services: Service phrases used in listings.
        category: Directory category text.
        license: State license class held by firms in the trade, if any.
        naics: NAICS code the registry reports.
        revenue_per_employee: True median revenue per employee, USD.
        web_word: Word used to build the website host.
        mix_prior: Probabilities of recurring-heavy, mixed and install-heavy.
    """

    in_sector: bool
    weight: float
    phrases: tuple[str, ...]
    services: tuple[str, ...]
    category: str
    license: str | None
    naics: str
    revenue_per_employee: float
    web_word: str
    mix_prior: tuple[float, float, float] = (0.2, 0.4, 0.4)


# fmt: off
TRADES: dict[str, Trade] = {
    "sprinkler": Trade(
        in_sector=True, weight=0.24,
        phrases=("Fire Protection", "Fire Sprinkler", "Sprinkler Co", "Fire Sprinkler Systems"),
        services=("fire sprinkler installation", "sprinkler inspection", "fire pump testing",
                  "standpipe service", "backflow testing"),
        category="Fire sprinkler contractor", license="Fire Sprinkler Contractor",
        naics="238220", revenue_per_employee=178_000, web_word="fire",
        mix_prior=(0.25, 0.35, 0.40),
    ),
    "alarm": Trade(
        in_sector=True, weight=0.20,
        phrases=("Fire Alarm", "Fire & Alarm", "Life Safety Systems", "Fire Detection"),
        services=("fire alarm installation", "fire alarm inspection", "alarm monitoring",
                  "emergency lighting", "notification appliances"),
        category="Fire alarm contractor", license="Fire Alarm Contractor",
        naics="238210", revenue_per_employee=165_000, web_word="alarm",
        mix_prior=(0.40, 0.35, 0.25),
    ),
    "inspection": Trade(
        in_sector=True, weight=0.20,
        phrases=("Fire Inspection Services", "Fire & Life Safety", "Fire Safety Services",
                 "Life Safety Inspections"),
        services=("fire and life safety inspections", "annual testing", "code compliance reports",
                  "deficiency repairs"),
        category="Fire safety inspection service", license="Fire Protection Inspector",
        naics="541350", revenue_per_employee=135_000, web_word="firesafety",
        mix_prior=(0.60, 0.30, 0.10),
    ),
    "suppression": Trade(
        in_sector=True, weight=0.14,
        phrases=("Fire Equipment", "Extinguisher Service", "Fire Suppression",
                 "Fire Extinguisher Co"),
        services=("fire extinguisher service", "kitchen hood suppression", "clean agent systems",
                  "hydrostatic testing"),
        category="Fire extinguisher service", license="Portable Extinguisher Service",
        naics="811310", revenue_per_employee=142_000, web_word="fireequip",
        mix_prior=(0.60, 0.30, 0.10),
    ),
    "hvac": Trade(
        in_sector=False, weight=0.06, phrases=("Heating & Air", "Mechanical", "HVAC Services"),
        services=("furnace repair", "air conditioning installation", "duct cleaning"),
        category="HVAC contractor", license=None,
        naics="238220", revenue_per_employee=150_000, web_word="air",
    ),
    "plumbing": Trade(
        in_sector=False, weight=0.05, phrases=("Plumbing", "Plumbing & Drain"),
        services=("drain cleaning", "water heater installation", "commercial plumbing"),
        category="Plumbing contractor", license=None,
        naics="238220", revenue_per_employee=145_000, web_word="plumbing",
    ),
    "electrical": Trade(
        in_sector=False, weight=0.05, phrases=("Electric", "Electrical Contractors"),
        services=("commercial wiring", "lighting retrofits", "emergency lighting"),
        category="Electrical contractor", license="Fire Alarm Contractor",
        naics="238210", revenue_per_employee=160_000, web_word="electric",
    ),
    "home_inspection": Trade(
        in_sector=False, weight=0.04, phrases=("Home Inspections", "Property Inspection"),
        services=("home inspections", "radon testing", "serving homeowners"),
        category="Home inspector", license=None,
        naics="541350", revenue_per_employee=110_000, web_word="inspect",
    ),
    "janitorial": Trade(
        in_sector=False, weight=0.02, phrases=("Building Services", "Cleaning Co"),
        services=("janitorial service", "floor care", "window cleaning"),
        category="Janitorial service", license=None,
        naics="561720", revenue_per_employee=60_000, web_word="clean",
    ),
}
# fmt: on

#: Trades a same-town look-alike firm is drawn from.
LOOK_ALIKE_TRADES = ("hvac", "plumbing", "electrical")
#: Trade whose firms always serve homeowners only.
RESIDENTIAL_TRADE = "home_inspection"
#: Service phrases added to an in-sector firm that serves homeowners only.
RESIDENTIAL_SERVICES = ("residential fire sprinklers", "serving homeowners")

MIXES = ("recurring_heavy", "mixed", "install_heavy")
MIX_WORDS = {
    "recurring_heavy": ("inspection agreements", "scheduled maintenance", "24/7 service"),
    "mixed": ("installation and service", "maintenance agreements"),
    "install_heavy": ("design-build installation", "new construction", "tenant finish"),
}
# The world's true margins differ from the demo thesis assumptions on purpose, so
# the estimator is graded against a world it does not describe perfectly.
TRUE_MARGIN = {
    "recurring_heavy": (0.12, 0.21),
    "mixed": (0.09, 0.17),
    "install_heavy": (0.06, 0.13),
}
EMPLOYEE_BANDS = ((1, 4), (5, 9), (10, 19), (20, 49), (50, 99), (100, 249), (250, 499), (500, 999))
LEGAL_SUFFIXES = ("Inc.", "Inc", "LLC", "L.L.C.", "Co.", "Company", "Corp.", "Corporation")
HOLDING_FORMS = ("Holdings, LLC", "Enterprises, Inc.", "Group LLC")
DBA_MARKERS = ("d/b/a", "DBA", "dba", "d.b.a.")
# fmt: off
NAME_ABBREVIATIONS = (
    ("Protection", ("Prot.", "Prot")), ("Services", ("Svcs", "Svcs.")), ("Service", ("Svc",)),
    ("Systems", ("Sys.",)), ("Sprinkler", ("Spklr",)), ("Equipment", ("Equip.",)),
    ("Inspections", ("Insp.",)), ("Inspection", ("Insp.",)), ("Extinguisher", ("Ext.",)),
    ("Electrical", ("Elec.",)), ("Mechanical", ("Mech.",)),
)
# fmt: on
