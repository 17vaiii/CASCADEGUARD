# Theft-aware load vector contract

**Producer:** Person 4 loss intelligence. **Consumers:** Persons 1 and 2,
with Person 3 responsible for end-to-end integration. This represents
suspected unmetered demand, not confirmed theft.

Each vector item contains:

| Field | Type | Meaning |
|---|---|---|
| `scenario_id` | string | Operating point / theft estimate identity. |
| `bus_id` or `tap_km` | string or number | Exactly one target location identifier. |
| `hidden_load_mw` | float | Estimated extra real-power demand; non-negative. |
| `power_factor` | float or null | Optional assumed PF used to derive reactive demand. |
| `confidence` | float or null | Suspicion confidence in [0, 1], not a truth label. |
| `source` | string | `suspected_unmetered_load`. |

Person 1 maps the target to a model tap and injects a real pandapower load. The
producer must not edit meter readings to represent this load. Person 2 uses the
same vector to compare theft-unaware and theft-aware predictions. Preserve the
baseline state and label the run with whether hidden demand was included.

## Changelog

- v1: Initial suspected hidden-load handoff contract.
