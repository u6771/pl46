from __future__ import annotations

from types import MappingProxyType
from typing import Callable, Mapping

from .errors import AssemblyError


SstyNamer = Callable[[str], str]


def _append_suffix(suffix: str) -> SstyNamer:
    def rename(source_name: str) -> str:
        return f"{source_name}.{suffix}"

    return rename


SSTY_NAMERS: Mapping[str, SstyNamer] = MappingProxyType({
    "st": _append_suffix("st"),
    "sts": _append_suffix("sts"),
})


def get_ssty_namer(name: str) -> SstyNamer:
    namer = SSTY_NAMERS.get(name)
    if namer is None:
        raise AssemblyError(
            f"Unknown ssty namer {name!r}. Known namers: "
            f"{sorted(SSTY_NAMERS)}"
        )
    return namer
