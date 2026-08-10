"""The registry of pseudopotential tables Core knows about.

The registry declares tables; it contains none. An entry records what a table
covers, what it costs to fetch, and under what terms -- enough for Core to
choose one, to explain why an element cannot be resolved, and to say what would
resolve it, all without downloading anything.

Not to be confused with ``pseudo.pp_registry``, which reads UPF files already on
disk.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from goldilocks_core.contracts import PathLike

PSEUDO_REGISTRY_ENV = "GOLDILOCKS_PSEUDO_REGISTRY"
"""Environment variable pointing at a replacement registry file."""

_REGISTRY_RESOURCE = "pseudo_registry.toml"

LANTHANIDES = frozenset("La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu".split())
ACTINIDES = frozenset("Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr".split())


@dataclass(frozen=True, slots=True)
class PseudoTable:
    """One registered pseudopotential table.

    Attributes:
        name: our identifier, e.g. ``pseudodojo-pbesol-efficiency-sr``. Always
            ends in ``-sr``, ``-fr``, or ``-nr``, matching ``relativistic``.
        provider: which upstream serves it -- ``pseudodojo`` or
            ``materialscloud``. Core never redistributes a table; it fetches
            from the provider on the user's behalf.
        upstream_table: what the provider calls it. The download URL is built
            from this, not from ``name``.
        record: provider record identifier, where the provider addresses tables
            that way rather than by name.
        version: upstream table version.
        functional: exchange-correlation functional the table was generated for.
        relativistic: ``SR``, ``FR``, or ``NR``. Only ``FR`` can satisfy
            spin-orbit coupling. No table is registered ``NR`` today -- SSSP's
            per-element non-relativistic pseudopotentials (B, Be, Li) sit
            inside an ``SR`` table, since a task selects one table, not a
            relativistic mode per element.
        accuracy: ``efficiency`` or ``precision``. One vocabulary across
            libraries; it selects a table, never a cutoff level.
        licence: licence of the pseudopotentials themselves. Not always a
            single one: an SSSP table is assembled from sources with different
            terms, some of them GPL.
        upstream_url: where the table comes from.
        citation: what a user should cite for having used it.
        elements: element symbols the table covers.
        transfer_bytes: bytes crossing the network, where known.
        note: what a user has to know before choosing it.
        default: whether this is the table Core reaches for unprompted.
    """

    name: str
    provider: str
    upstream_table: str
    version: str
    functional: str
    relativistic: str
    accuracy: str
    licence: str
    upstream_url: str
    citation: str
    elements: tuple[str, ...]
    record: str | None = None
    transfer_bytes: int | None = None
    note: str = ""
    default: bool = False

    @property
    def lanthanides(self) -> tuple[str, ...]:
        """Covered lanthanides, in table order."""
        return tuple(e for e in self.elements if e in LANTHANIDES)

    @property
    def actinides(self) -> tuple[str, ...]:
        """Covered actinides, in table order."""
        return tuple(e for e in self.elements if e in ACTINIDES)

    def covers(self, element: str) -> bool:
        """Whether the table contains a pseudopotential for ``element``."""
        return element in self.elements

    def missing_from(self, elements: tuple[str, ...]) -> tuple[str, ...]:
        """Return those of ``elements`` this table does not cover."""
        return tuple(e for e in elements if e not in self.elements)


def load_tables(path: PathLike | None = None) -> dict[str, PseudoTable]:
    """Load the pseudopotential table registry.

    Resolution order: ``path``, then ``GOLDILOCKS_PSEUDO_REGISTRY``, then the
    file packaged with Core.
    """
    document = tomllib.loads(_registry_text(path))

    return {
        name: PseudoTable(
            name=name,
            provider=entry["provider"],
            upstream_table=entry["upstream_table"],
            version=entry["version"],
            functional=entry["functional"],
            relativistic=entry["relativistic"],
            accuracy=entry["accuracy"],
            licence=entry["licence"],
            upstream_url=entry["upstream_url"],
            citation=entry["citation"],
            elements=tuple(entry["elements"]),
            record=entry.get("record"),
            transfer_bytes=entry.get("transfer_bytes"),
            note=entry.get("note", "").strip(),
            default=entry.get("default", False),
        )
        for name, entry in document["tables"].items()
    }


def default_table(tables: dict[str, PseudoTable] | None = None) -> PseudoTable:
    """Return the table Core uses when the caller expresses no preference.

    Raises:
        LookupError: no entry is marked as the default, or several are.
    """
    registry = tables if tables is not None else load_tables()
    defaults = [table for table in registry.values() if table.default]

    if len(defaults) != 1:
        found = ", ".join(t.name for t in defaults) or "none"
        raise LookupError(
            f"the registry must mark exactly one table as default; found: {found}"
        )

    return defaults[0]


def tables_covering(
    element: str,
    tables: dict[str, PseudoTable] | None = None,
) -> tuple[PseudoTable, ...]:
    """Return every registered table containing ``element``.

    This is what lets a coverage failure name a remedy rather than report an
    empty match: an element absent everywhere is a different problem from one
    available only under another functional, or only in a table we cannot fetch.
    """
    registry = tables if tables is not None else load_tables()
    return tuple(table for table in registry.values() if table.covers(element))


def _registry_text(path: PathLike | None) -> str:
    """Return the registry document, from ``path``, the environment, or the package."""
    override = path or os.environ.get(PSEUDO_REGISTRY_ENV)
    if override:
        return Path(override).read_text(encoding="utf-8")

    return (
        resources.files("goldilocks_core")
        .joinpath(_REGISTRY_RESOURCE)
        .read_text(encoding="utf-8")
    )
