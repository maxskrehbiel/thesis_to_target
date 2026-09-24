"""The seeded synthetic world: determinism, fictional markers, capacity and planted hard cases."""

from __future__ import annotations

import numpy as np
import pytest

from thesis_to_target.config import SyntheticSettings
from thesis_to_target.errors import CapacityError, ConfigError
from thesis_to_target.normalize import normalize_domain, normalize_phone
from thesis_to_target.synthetic import (
    FEEDS,
    SyntheticFeedAdapter,
    WorldConfig,
    build_world,
    max_firms,
    synthetic_presence_checker,
)
from thesis_to_target.synthetic.draws import Draws
from thesis_to_target.synthetic.mess import abbreviate, band_label, format_phone, typo, with_suffix
from thesis_to_target.thesis import PresenceSpec, Thesis

WORLD = build_world(SyntheticSettings(seed=42, n_firms=60))


def test_same_seed_same_world_different_seed_different_world() -> None:
    fresh = build_world.__wrapped__(SyntheticSettings(seed=42, n_firms=60))
    assert [(r.record_id, r.name) for r in fresh.records["web_listing"]] == [
        (r.record_id, r.name) for r in WORLD.records["web_listing"]
    ]
    other = build_world(SyntheticSettings(seed=7, n_firms=60))
    assert [r.name for r in other.records["web_listing"]] != [
        r.name for r in WORLD.records["web_listing"]
    ]


def test_draws_are_pinned_to_the_raw_random_stream() -> None:
    # Only Generator.random() is used, so this sequence is fixed for PCG64 seed 0.
    assert Draws(np.random.default_rng(0)).uniform() == 0.6369616873214543
    draws = Draws(np.random.default_rng(0))
    assert [draws.integer(1, 6) for _ in range(5)] == [4, 2, 1, 1, 5]


def test_draw_helpers() -> None:
    draws = Draws(np.random.default_rng(1))
    assert sorted(draws.shuffled([1, 2, 3, 4])) == [1, 2, 3, 4]
    assert len(set(draws.sample(range(10), 4))) == 4 and len(draws.sample([1, 2], 5)) == 2
    assert draws.weighted(["a", "b"], [0.0, 1.0]) == "b"
    values = [draws.normal() for _ in range(2000)]
    assert abs(float(np.mean(values))) < 0.1 and abs(float(np.std(values)) - 1) < 0.1
    assert all(0 <= draws.integer(0, 3) <= 3 for _ in range(100))


def test_every_contact_detail_is_fictional() -> None:
    for feed in FEEDS:
        for r in WORLD.records[feed]:
            if r.phone:
                digits = normalize_phone(r.phone)
                assert digits is not None and digits[3:6] == "555" and 100 <= int(digits[6:]) <= 199
            if r.website:
                host = normalize_domain(r.website)
                assert host is not None and host.endswith(".example")
    for firm in WORLD.firms:
        assert firm.phone[3:6] == "555"
        assert firm.domain is None or firm.domain.endswith(".example")


def test_records_and_truth_are_consistent() -> None:
    ids = [r.record_id for feed in FEEDS for r in WORLD.records[feed]]
    assert len(ids) == len(set(ids)) == len(WORLD.truth)
    assert set(WORLD.truth.values()) == {f.firm_id for f in WORLD.firms}  # every firm is visible
    assert WORLD.firm(WORLD.firms[0].firm_id) is WORLD.firms[0]
    with pytest.raises(KeyError):
        WORLD.firm("F999")


def test_hard_negatives_are_planted() -> None:
    by_name: dict[str, set[str]] = {}
    by_core_town: dict[tuple[str, str], set[str]] = {}
    by_phone: dict[str, set[str]] = {}
    for f in WORLD.firms:
        by_name.setdefault(f.name, set()).add(f.state)
        by_core_town.setdefault((f.core, f.city), set()).add(f.trade)
        by_phone.setdefault(f.phone, set()).add(f.core)
    assert any(len(states) > 1 for states in by_name.values())  # same name, different state
    assert any(len(trades) > 1 for trades in by_core_town.values())  # same core and town
    assert any(len(cores) > 1 for cores in by_phone.values())  # unrelated firms sharing a line


def test_capacity_is_checked_up_front() -> None:
    limit = max_firms()
    assert limit == max_firms(WorldConfig()) and limit >= 200
    with pytest.raises(CapacityError, match=f"capacity of {limit}"):
        build_world(SyntheticSettings(n_firms=limit + 1))
    assert len(build_world(SyntheticSettings(seed=3, n_firms=limit)).firms) > limit


def test_mess_helpers() -> None:
    draws = Draws(np.random.default_rng(0))
    damaged = typo("Quenholt Fire Protection", draws)
    assert damaged != "Quenholt Fire Protection" and len(damaged.split()) == 3
    assert typo("Ab Cd", draws) == "Ab Cd"
    assert (
        abbreviate("Braxmoor Fire Protection Services", draws)
        != "Braxmoor Fire Protection Services"
    )
    assert abbreviate("Braxmoor", draws) == "Braxmoor"
    assert abbreviate("Braxmoor & Alarm", draws, max_words=1) == "Braxmoor and Alarm"
    assert with_suffix("Braxmoor Sprinkler Co", draws).split()[-1] not in ("Co.", "Company")
    styles = {"(217) 555-0142", "217-555-0142", "217.555.0142", "+1 217 555 0142", "1-217-555-0142"}
    assert format_phone("2175550142", draws) in {*styles, "2175550142"}
    assert band_label(30, draws, noise=0.0) == "20-49"
    assert band_label(700, draws, noise=0.0) == "500+"
    assert band_label(5000, draws, noise=0.0) == "500+"


def test_adapter_and_presence_factory(demo_thesis: Thesis) -> None:
    with pytest.raises(ConfigError, match="synthetic feed"):
        SyntheticFeedAdapter("no_such_feed")
    adapter = SyntheticFeedAdapter("web_listing", 0.6)
    assert adapter.synthetic and adapter.ground_truth() is None and adapter.entity_truth() is None
    records = adapter.fetch(demo_thesis)
    truth, facts = adapter.ground_truth(), adapter.entity_truth()
    assert truth is not None and set(truth) == {r.record_id for r in records}
    assert facts is not None and set(truth.values()) <= set(facts)
    with pytest.raises(ConfigError, match="synthetic database"):
        synthetic_presence_checker(demo_thesis, PresenceSpec("synthetic", "no_such_db", 0.1))
    checker = synthetic_presence_checker(
        demo_thesis, PresenceSpec("synthetic", "investor_db", 0.25)
    )
    assert checker.database == "investor_db"
