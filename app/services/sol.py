"""Nascer e por do sol (algoritmo do NOAA, erro de 1 a 2 min). So calculo."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple


def nascer_por(lat: float, lon: float, dia: date) -> Optional[Tuple[datetime, datetime]]:
    """(nascer, por) em UTC; None perto dos polos, onde o sol nao nasce ou nao se poe."""
    n = dia.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                   - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    dec = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
           + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    cos_h = math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(dec)) - math.tan(la) * math.tan(dec)
    if not -1 <= cos_h <= 1:
        return None
    h = math.degrees(math.acos(cos_h))
    meia_noite = datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc)
    nascer = 720 - 4 * (lon + h) - eq
    por = 720 - 4 * (lon - h) - eq
    return meia_noite + timedelta(minutes=nascer), meia_noite + timedelta(minutes=por)
