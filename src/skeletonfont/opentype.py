from __future__ import annotations


FWORD_MIN = -(1 << 15)
FWORD_MAX = (1 << 15) - 1
UFWORD_MAX = (1 << 16) - 1
UNITS_PER_EM_MIN = 16
UNITS_PER_EM_MAX = 16384


__all__ = [
    "FWORD_MAX",
    "FWORD_MIN",
    "UFWORD_MAX",
    "UNITS_PER_EM_MAX",
    "UNITS_PER_EM_MIN",
]
