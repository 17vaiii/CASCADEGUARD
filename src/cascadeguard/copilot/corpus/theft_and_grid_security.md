---
title: Hidden theft load and cascade risk
tags: [theft, hidden load, ntl, cascade, scada]
status: project document
---
# Hidden theft load and cascade risk

## Why theft matters for security
Unmetered (stolen) load is real demand on the network even though no meter records it. Line loadings therefore run higher than a model built only from metered demand predicts. Close to a limit, a few megawatts of hidden load can turn a contingency that looks safe into a cascade.

## Using theft estimates in operations
The theft analytics module estimates hidden load per substation from feeder energy balances. Adding that estimate to the operating state lets cascade screening and mitigation planning see the real loading; plans computed on the metered-only view can fail on the real system.
