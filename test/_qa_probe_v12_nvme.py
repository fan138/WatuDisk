# -*- coding: utf-8 -*-
"""QA 探针：打印真机 NVMe 直读原始值，用于校准参考值容差。只读。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))

from core import nvme_health  # noqa: E402

for n in (0, 1, 99):
    h = nvme_health.query_nvme_health(n)
    print(f"PD{n}: {h}")
    if h:
        print(
            f"  poh={h['power_on_hours']} cycles={h['power_cycles']} "
            f"unsafe={h['unsafe_shutdowns']} media={h['media_errors']} "
            f"written={nvme_health.format_data_units(h['data_units_written'])} "
            f"read={nvme_health.format_data_units(h['data_units_read'])} "
            f"spare={h['available_spare_pct']}/{h['spare_threshold']} pct={h['percentage_used']} "
            f"temp={h['temperature_c']} crit={h['critical_warning']}"
        )
