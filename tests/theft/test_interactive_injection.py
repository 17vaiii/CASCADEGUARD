"""Regression coverage for the dashboard's pinned synthetic feeder injection."""

from __future__ import annotations

from cascadeguard.theft import load_config
from cascadeguard.theft.feeder_sim import simulate_distribution


def test_targeted_injection_uses_selected_feeder_type_and_window():
    cfg = load_config()
    sim = cfg["simulation"]
    substation = "PEENYA"
    sim.update({
        "days": 28, "history_days": 14, "min_event_days": 7,
        "feeders_per_substation": {substation: 1},
        "area_by_substation": {substation: sim["area_by_substation"][substation]},
        "dts_per_feeder": [2, 2], "consumers_per_dt": [12, 12],
        "dt_metered_fraction": 1.0, "theft_fraction": 0.0, "lookalike_fraction": 0.0,
        "comm_failure_fraction": 0.0, "new_connection_feeder_fraction": 0.0,
    })

    ds = simulate_distribution(cfg, seed=17, injection={
        "feeder_id": "PEENYA_F04", "substation": substation,
        "theft_type": "meter_stop", "intensity": 1.0, "duration_days": 7,
        "affected_consumers": 2, "start_idx": 15 * 24,
    })

    assert ds.feeders.feeder_id.tolist() == ["PEENYA_F04"]
    affected = ds.consumers[ds.consumers.is_theft]
    assert len(affected) == 2
    assert affected.feeder_id.eq("PEENYA_F04").all()
    assert affected.theft_type.eq("meter_stop").all()
    row = int(affected.row.iloc[0])
    start, end = int(affected.event_start.iloc[0]), int(affected.event_end.iloc[0])
    assert end - start == 7 * 24
    assert (ds.metered_kwh[row, start:end] == 0).all()
