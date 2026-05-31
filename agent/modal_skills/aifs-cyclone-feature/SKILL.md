---
name: aifs-cyclone-feature
description: Modal-only. AIFS MSLP minima + 850hPa vorticity → cyclone_feature point signals with cross-horizon tracking.
version: 0.1.0
---

# aifs-cyclone-feature

Detects model-derived cyclone centers from ECMWF AIFS (+0/+24/+48/+72h). Vorticity at 850 hPa is computed from wind components (AIFS Open Data has no direct `vo` field).

- `source`: `aifs`
- `signal_type`: `cyclone_feature`
- Schedule: **05:00 and 17:00 UTC**

```bash
python -m modal run agent/modal_skills/aifs-cyclone-feature/app.py
python -m modal deploy agent/modal_skills/aifs-cyclone-feature/app.py
```
