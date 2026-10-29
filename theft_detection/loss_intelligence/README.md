# Loss Intelligence - Person 4

Person 4 owns feeder energy balance, consumer interval profiles, anomaly
scoring, reason codes, inspection ranking, and the T9 hidden-load estimate in
this work area. Existing theft detection and tap localization remain under
`ml/` and the existing theft scenario pipeline remains under `simdata/`.

Use `contracts/THEFT_LOAD_VECTOR.md` for the interface to Persons 1 and 2.
Do not edit `grid/` or `cascade_ml/`; coordinate any changes through the
contract and the path owner.
