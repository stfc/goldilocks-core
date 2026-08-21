from __future__ import annotations

import math
import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from pymatgen.core import Element

from goldilocks_core.assets import AssetFile, AssetSpec
from goldilocks_core.contracts import PathLike, PseudoAccuracy, RelativisticTreatment
from goldilocks_core.functionals import normalize_functional_label

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
        provider = _required_string(entry, "provider")
        if provider not in _PROVIDERS:
            raise ValueError(f"unsupported provider {provider!r}")
        upstream_table = _required_string(entry, "upstream_table")
        version = _required_string(entry, "version")
        functional = normalize_functional_label(_required_string(entry, "functional"))
        if functional is None:
            raise ValueError("functional cannot be empty")
        relativistic_raw = _required_string(entry, "relativistic")
        try:
            relativistic = _RELATIVISTIC[relativistic_raw]
        except KeyError as error:
            raise ValueError(
                f"unsupported relativistic treatment {relativistic_raw!r}"
            ) from error
        accuracy = _required_string(entry, "accuracy")
        if accuracy not in {"efficiency", "precision"}:
            raise ValueError(f"unsupported accuracy {accuracy!r}")
        licence = _required_string(entry, "licence")
        citation = _required_string(entry, "citation")

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
        invalid_elements = [
            element for element in elements if not Element.is_valid_symbol(element)
        ]
        if invalid_elements:
            raise ValueError(
                "invalid element symbols: " + ", ".join(sorted(invalid_elements))
            )

        raw_files = entry["files"]
        if not isinstance(raw_files, list) or not raw_files:
            raise ValueError("files must be a non-empty array")
        files = tuple(AssetFile(**raw_file) for raw_file in raw_files)
        roles = {file.role for file in files}
        required_roles = {"pseudopotentials", "metadata"}
        if provider == "sssp":
            required_roles.add("licence")
        if not required_roles.issubset(roles):
            names = ", ".join(sorted(required_roles))
            raise ValueError(f"files must declare roles: {names}")

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
        if provider == "pseudodojo" and dual is None:
            raise ValueError("PseudoDojo tables require charge_density_dual")

        asset = AssetSpec(
            f"pseudopotentials/{table_id}",
            version,
            files,
            preparation_revision=_PREPARATION_REVISIONS[provider],
        )
        return PseudoTable(
            id=table_id,
            provider=provider,
            upstream_table=upstream_table,
            version=version,
            functional=functional,
            relativistic=relativistic,
            accuracy=accuracy,
            licence=licence,
            citation=citation,
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
