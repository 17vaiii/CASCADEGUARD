# Sharavathi corridor model: scope and provenance

The reduced model in `config/topology.yaml` represents a 361 km, 220 kV,
five-substation corridor with virtual tap buses. `grid.cascade` expands it to
parallel circuits for contingency simulation. It is a research abstraction,
not an operator-grade or verified KPTCL single-line model.

Public KPTCL planning and RTI records list Bengaluru transmission assets and
projects, including Nelamangala and Peenya/Nelamangala corridor references.
Those records do not provide the complete bus connectivity, branch impedances,
ratings, breaker states, hydro dispatch limits, or Bengaluru load allocation
needed to reproduce a validated single-line model. Parameters marked `assumed`
remain assumptions pending operator data.

References:

- [KPTCL RTI: CEETZ Bengaluru 2024–25](https://kptcl.karnataka.gov.in/storage/pdf-files/RTI%20KPTCL/RTI_4-1A_CEETZ_blr_2024-25.pdf)
- [KPTCL Annual Programme of Works 2023–24](https://kptcl.karnataka.gov.in/storage/pdf-files/RTI%20KPTCL/APW-2023-24_Kan_RTI_4-1B.pdf)

`python -m grid.benchmarks` runs pandapower AC power flow on built-in IEEE
14-, 39-, and 118-bus systems. These validate the power-flow toolchain, not
the corridor assumptions. Generated corridor variants, weather outage weights,
and renewable profiles are synthetic scenario inputs, not measured topology,
calibrated failure rates, or forecasts.
