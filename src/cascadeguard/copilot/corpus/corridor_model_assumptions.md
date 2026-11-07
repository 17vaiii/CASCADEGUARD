---
title: Sharavathi-Bengaluru corridor model and mitigation assumptions
tags: [assumptions, corridor, tie, model, sharavathi, nelamangala, peenya]
status: project document
---
# Sharavathi-Bengaluru corridor model and mitigation assumptions

## Model
The corridor is a simulated 361 km, 220 kV dual-circuit chain from Sharavathi through Shimoga, Sira and Nelamangala to Peenya (Bengaluru), with tap buses every 10 km. Each section has two parallel circuits; when one trips, its flow moves to the other, which can overload and trip in turn. Parameters are assumptions, not verified utility data.

## Mitigation resources
For mitigation studies the model adds an equivalent state-grid interconnection at Nelamangala with an assumed import limit. Raising the import reduces the power that must travel from Sharavathi, so Sharavathi hydro output falls by about the same amount. Hydro output stays within the seasonal ramp, capacity and daily energy limits. Controlled load shedding is available at each substation.

## Verification
Every recommendation is re-simulated with the project's AC cascade simulator. A plan is marked verified only if no further line trips, no automatic load shedding, no voltage violation and no overload remain.
