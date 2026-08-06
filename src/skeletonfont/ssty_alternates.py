from __future__ import annotations

from types import MappingProxyType
from typing import Callable, Mapping

from .errors import AssemblyError


SstyAlternateNamer = Callable[[str], str]


def _append_suffix(suffix: str) -> SstyAlternateNamer:
    def rename(source_name: str) -> str:
        return f"{source_name}.{suffix}"

    return rename


SSTY_ALTERNATE_NAMERS: Mapping[str, SstyAlternateNamer] = MappingProxyType({
    "st": _append_suffix("st"),
    "sts": _append_suffix("sts"),
})


def get_ssty_alternate_namer(name: str) -> SstyAlternateNamer:
    namer = SSTY_ALTERNATE_NAMERS.get(name)
    if namer is None:
        raise AssemblyError(
            f"Unknown ssty alternate name {name!r}. Known names: "
            f"{sorted(SSTY_ALTERNATE_NAMERS)}"
        )
    return namer
