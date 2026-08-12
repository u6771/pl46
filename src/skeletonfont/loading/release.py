from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping, cast
from urllib.parse import urlsplit

from ..errors import ProjectDataError
from ..model import EmbeddingPermissions, FontLicense, ReleaseInfo
from ._json import (
    _object,
    _reject_unknown_fields,
    _string,
    normalize_json_filename,
    read_json,
)


_RELEASE_INFO_FIELDS = {
    "version",
    "copyright",
    "designer",
    "designer_url",
    "manufacturer",
    "manufacturer_url",
    "description",
    "trademark",
    "vendor_id",
    "license",
    "embedding_permissions",
}
_LICENSE_FIELDS = {"identifier", "url"}
_REQUIRED_LICENSE_FIELDS = {"identifier"}
_VERSION_RE = re.compile(r"(0|[1-9][0-9]*)\.([0-9]{3})")
_VENDOR_ID_RE = re.compile(r"[A-Za-z0-9]{4}")
_EMBEDDING_PERMISSIONS = {
    "installable",
    "restricted",
    "preview_and_print",
    "editable",
}
_LICENSE_DESCRIPTIONS = {
    "OFL-1.1": (
        "This Font Software is licensed under the SIL Open Font License, "
        "Version 1.1."
    ),
}


def _required_fields(
    data: Mapping[str, object],
    required: set[str],
    *,
    location: str,
) -> None:
    missing = required - set(data)
    if missing:
        raise ProjectDataError(
            f"{location} is missing required fields: {sorted(missing)}"
        )


def _url(value: object, *, location: str) -> str:
    result = _string(value, location=location)
    parsed = urlsplit(result)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProjectDataError(
            f"{location} must be an absolute HTTP or HTTPS URL."
        )
    return result


def _parse_version(value: object, *, location: str) -> tuple[str, int, int]:
    version = _string(value, location=location)
    match = _VERSION_RE.fullmatch(version)
    if match is None:
        raise ProjectDataError(
            f"{location} must use <major>.<three-digit minor>, "
            "for example '1.000'."
        )
    major = int(match.group(1))
    if major > 32767:
        raise ProjectDataError(
            f"{location} major version must be at most 32767."
        )
    return version, major, int(match.group(2))


def _parse_license(value: object, *, location: str) -> FontLicense:
    data = _object(value, location=location)
    _reject_unknown_fields(data, _LICENSE_FIELDS, location=location)
    _required_fields(data, _REQUIRED_LICENSE_FIELDS, location=location)

    identifier = _string(
        data["identifier"],
        location=f"{location}.identifier",
    )
    description = _LICENSE_DESCRIPTIONS.get(identifier)
    if description is None:
        raise ProjectDataError(
            f"{location}.identifier uses unsupported license {identifier!r}; "
            f"supported licenses: {sorted(_LICENSE_DESCRIPTIONS)}"
        )

    return FontLicense(
        identifier=identifier,
        description=description,
        url=(
            None
            if "url" not in data
            else _url(data["url"], location=f"{location}.url")
        ),
    )


def parse_release_info(value: object, *, source_path: Path) -> ReleaseInfo:
    """Parse one non-empty collection of optional publication metadata."""

    location = str(source_path)
    data = _object(value, location=location)
    _reject_unknown_fields(data, _RELEASE_INFO_FIELDS, location=location)
    if not data:
        raise ProjectDataError(f"{location} cannot be empty.")

    version_data = (
        (None, None, None)
        if "version" not in data
        else _parse_version(
            data["version"],
            location=f"{location}.version",
        )
    )
    version, version_major, version_minor = version_data

    embedding_permissions_value = (
        None
        if "embedding_permissions" not in data
        else _string(
            data["embedding_permissions"],
            location=f"{location}.embedding_permissions",
        )
    )
    if (
        embedding_permissions_value is not None
        and embedding_permissions_value not in _EMBEDDING_PERMISSIONS
    ):
        raise ProjectDataError(
            f"{location}.embedding_permissions must be one of "
            f"{sorted(_EMBEDDING_PERMISSIONS)}."
        )
    embedding_permissions = cast(
        EmbeddingPermissions | None,
        embedding_permissions_value,
    )

    vendor_id = (
        None
        if "vendor_id" not in data
        else _string(data["vendor_id"], location=f"{location}.vendor_id")
    )
    if vendor_id is not None and _VENDOR_ID_RE.fullmatch(vendor_id) is None:
        raise ProjectDataError(
            f"{location}.vendor_id must contain exactly four ASCII "
            "letters or digits."
        )

    license_info = (
        None
        if "license" not in data
        else _parse_license(
            data["license"],
            location=f"{location}.license",
        )
    )
    if (
        license_info is not None
        and license_info.identifier == "OFL-1.1"
        and embedding_permissions != "installable"
    ):
        raise ProjectDataError(
            f"{location}.embedding_permissions must be explicitly set to "
            "'installable' for OFL-1.1."
        )

    return ReleaseInfo(
        source_path=source_path,
        version=version,
        version_major=version_major,
        version_minor=version_minor,
        copyright=(
            None
            if "copyright" not in data
            else _string(
                data["copyright"],
                location=f"{location}.copyright",
            )
        ),
        designer=(
            None
            if "designer" not in data
            else _string(
                data["designer"],
                location=f"{location}.designer",
            )
        ),
        designer_url=(
            None
            if "designer_url" not in data
            else _url(
                data["designer_url"],
                location=f"{location}.designer_url",
            )
        ),
        manufacturer=(
            None
            if "manufacturer" not in data
            else _string(
                data["manufacturer"],
                location=f"{location}.manufacturer",
            )
        ),
        manufacturer_url=(
            None
            if "manufacturer_url" not in data
            else _url(
                data["manufacturer_url"],
                location=f"{location}.manufacturer_url",
            )
        ),
        description=(
            None
            if "description" not in data
            else _string(
                data["description"],
                location=f"{location}.description",
            )
        ),
        trademark=(
            None
            if "trademark" not in data
            else _string(
                data["trademark"],
                location=f"{location}.trademark",
            )
        ),
        vendor_id=vendor_id,
        license=license_info,
        embedding_permissions=embedding_permissions,
    )


def load_release_info(
    project_directory: Path,
    filename: object,
) -> ReleaseInfo:
    """Load one release-info file relative to the project data directory."""

    normalized = normalize_json_filename(
        filename,
        location="Release-info filename",
    )
    path = project_directory / "data" / "release_info" / normalized
    return parse_release_info(read_json(path), source_path=path)
