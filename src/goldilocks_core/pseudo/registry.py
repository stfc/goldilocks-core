from __future__ import annotations

import math
import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from pymatgen.core import Element

from goldilocks_core.assets.records import AssetFile, AssetSpec
from goldilocks_core.functionals import normalize_functional_label
from goldilocks_core.types import PathLike, PseudoAccuracy, RelativisticTreatment

PSEUDO_REGISTRY_ENV = "GOLDILOCKS_PSEUDO_REGISTRY"
_REGISTRY_RESOURCE = "registry.toml"
_PROVIDERS = frozenset({"pseudodojo", "sssp"})
_PREPARATION_REVISIONS = {"pseudodojo": "2", "sssp": "1"}
_RELATIVISTIC = {
    "SR": "scalar",
    "FR": "full",
    "NR": "non-relativistic",
    "scalar": "scalar",
    "full": "full",
    "non-relativistic": "non-relativistic",
}
_REQUIRED_TABLE_FIELDS = frozenset(
    {
        "provider",
        "upstream_table",
        "version",
        "functional",
        "relativistic",
        "accuracy",
        "licence",
        "citation",
        "elements",
        "files",
    }
)
_OPTIONAL_TABLE_FIELDS = frozenset(
    {
        "upstream_url",
        "transfer_bytes",
        "installed_bytes",
        "record",
        "note",
        "charge_density_dual",
        "default",
    }
)


class InvalidPseudoRegistry(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PseudoTable:
    id: str
    provider: str
    upstream_table: str
    version: str
    functional: str
    relativistic: RelativisticTreatment
    accuracy: PseudoAccuracy
    licence: str
    citation: str
    elements: tuple[str, ...]
    asset: AssetSpec
    charge_density_dual: float | None = None
    default: bool = False


def load_tables(path: PathLike | None = None) -> dict[str, PseudoTable]:
    registry_path = path or os.environ.get(PSEUDO_REGISTRY_ENV)
    try:
        if registry_path:
            with Path(registry_path).open("rb") as source:
                data = tomllib.load(source)
        else:
            registry = resources.files("goldilocks_core.pseudo").joinpath(
                _REGISTRY_RESOURCE
            )
            with registry.open("rb") as source:
                data = tomllib.load(source)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise InvalidPseudoRegistry(f"cannot read pseudo registry: {error}") from error

    raw_tables = data.get("tables")
    if not isinstance(raw_tables, dict) or not raw_tables:
        raise InvalidPseudoRegistry("registry must contain a non-empty tables mapping")
    tables = {
        table_id: _parse_table(table_id, entry)
        for table_id, entry in raw_tables.items()
    }
    defaults = [table.id for table in tables.values() if table.default]
    if len(defaults) != 1:
        names = ", ".join(defaults) or "none"
        raise InvalidPseudoRegistry(
            f"registry must have exactly one default table; found {names}"
        )
    return tables


def default_table(tables: dict[str, PseudoTable] | None = None) -> PseudoTable:
    loaded = tables or load_tables()
    defaults = [table for table in loaded.values() if table.default]
    if len(defaults) != 1:
        names = ", ".join(table.id for table in defaults) or "none"
        raise InvalidPseudoRegistry(
            f"registry must have exactly one default table; found {names}"
        )
    return defaults[0]


def table_asset_specs(path: PathLike | None = None) -> tuple[AssetSpec, ...]:
    return tuple(table.asset for table in load_tables(path).values())


def _table_payload(
    table_id: str, entry: dict[str, Any]
) -> tuple[tuple[str, ...], AssetSpec]:
    raw_elements = entry["elements"]
    if (
        not isinstance(raw_elements, list)
        or not raw_elements
        or any(not isinstance(element, str) for element in raw_elements)
    ):
        raise ValueError("elements must be a non-empty string list")
    elements = tuple(raw_elements)
    if len(elements) != len(set(elements)):
        raise ValueError("elements must be unique")
    invalid = [element for element in elements if not Element.is_valid_symbol(element)]
    if invalid:
        raise ValueError("invalid element symbols: " + ", ".join(sorted(invalid)))
    raw_files = entry["files"]
    if not isinstance(raw_files, list) or not raw_files:
        raise ValueError("files must be a non-empty array")
    files = tuple(AssetFile(**raw_file) for raw_file in raw_files)
    required_roles = {
        "pseudodojo": {"pseudopotentials", "metadata"},
        "sssp": {"pseudopotentials", "metadata", "licence"},
    }[entry["provider"]]
    if not required_roles.issubset(file.role for file in files):
        raise ValueError(
            f"files must declare roles: {', '.join(sorted(required_roles))}"
        )
    return elements, AssetSpec(
        f"pseudopotentials/{table_id}",
        entry["version"],
        files,
        preparation_revision=_PREPARATION_REVISIONS[entry["provider"]],
    )


def _parse_table(table_id: str, entry: Any) -> PseudoTable:
    if not isinstance(table_id, str) or not isinstance(entry, dict):
        raise InvalidPseudoRegistry(
            "table identifiers and declarations must be objects"
        )
    fields = set(entry)
    missing = _REQUIRED_TABLE_FIELDS - fields
    extra = fields - (_REQUIRED_TABLE_FIELDS | _OPTIONAL_TABLE_FIELDS)
    if missing or extra:
        missing_names = ", ".join(sorted(missing)) or "none"
        extra_names = ", ".join(sorted(extra)) or "none"
        raise InvalidPseudoRegistry(
            f"invalid table {table_id!r}: fields mismatch; "
            f"missing: {missing_names}; extra: {extra_names}"
        )
    try:
        entry = dict(entry)
        for field in (
            "provider",
            "upstream_table",
            "version",
            "functional",
            "relativistic",
            "accuracy",
            "licence",
            "citation",
        ):
            entry[field] = _required_string(entry, field)
        for field, allowed, label in (
            ("provider", _PROVIDERS, "provider"),
            ("relativistic", _RELATIVISTIC, "relativistic treatment"),
            ("accuracy", {"efficiency", "precision"}, "accuracy"),
        ):
            if entry[field] not in allowed:
                raise ValueError(f"unsupported {label} {entry[field]!r}")
        entry["functional"] = normalize_functional_label(entry["functional"])
        entry["relativistic"] = _RELATIVISTIC[entry["relativistic"]]
        elements, asset = _table_payload(table_id, entry)

        default = entry.get("default", False)
        if not isinstance(default, bool):
            raise ValueError("default must be a boolean")
        dual = entry.get("charge_density_dual")
        if dual is not None and (
            isinstance(dual, bool)
            or not isinstance(dual, int | float)
            or not math.isfinite(dual)
            or dual <= 0
        ):
            raise ValueError("charge_density_dual must be finite and positive")
        if entry["provider"] == "pseudodojo" and dual is None:
            raise ValueError("PseudoDojo tables require charge_density_dual")

        return PseudoTable(
            id=table_id,
            **{
                field: entry[field]
                for field in (
                    "provider",
                    "upstream_table",
                    "version",
                    "functional",
                    "relativistic",
                    "accuracy",
                    "licence",
                    "citation",
                )
            },
            elements=elements,
            asset=asset,
            charge_density_dual=float(dual) if dual is not None else None,
            default=default,
        )
    except (KeyError, TypeError, ValueError) as error:
        raise InvalidPseudoRegistry(f"invalid table {table_id!r}: {error}") from error


def _required_string(entry: dict[str, Any], name: str) -> str:
    value = entry[name]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()
