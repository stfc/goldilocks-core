"""pseudo_selection: which registered pseudopotential table to use, and
matching a made selection back to its verified metadata -- as tri-state
results with provenance, not exceptions.

Ported as content from v1's `pseudo/source.py` (v2 epic 5, #5): the table
ranking/eligibility logic (`_table_problems`, `_automatic_table`,
`is_table_eligible_for_elements`) and the lanthanide/actinide-must-use-SSSP
rule (`_requires_sssp`) are correct scientific content, reused unchanged;
only their failure shape changes.

**Scope note**: this ports the *selection* decision only, not
`PseudoResolution`'s full `materialize()` orchestration (reading actual UPF
bytes off an `AssetStore`, building `InputArtifact`s, licence-file handling).
That is file-assembly, not a settings decision, the line every other
advisor in this epic draws: `service/_pseudo.py`'s `pseudo_artifacts`
reads the UPFs and the table's licence for the bundle (#157). v1's
`pseudo/source.py` stayed untouched until it was deleted along with the
rest of the v1 tree at cutover (v2 epic 9); this is a fresh, standalone
port, tested on its own, same as every prior epic's deliverable.

Two v1 bugs fixed here, per this epic's Section (c):

- **`PseudoTableMismatch` raise-on-failure**
  (`pseudo/source.py:159-161,172-175,200-203`) -- an unknown table id, a
  table that doesn't cover the requested elements, or no compatible table
  at all now returns `Unavailable`, not a raised exception on the
  happy-adjacent path. `_refusal` builds both the pinned and the automatic
  refusal from `_table_problems`, so it names the constraint that rejected
  each table;
  v1's automatic-path text named only the request and the elements (#182).
- **`materialize()`'s `StopIteration`-prone round-trip**
  (`pseudo/source.py:114-129`) -- matching each selected pseudopotential
  back to its metadata used a bare `next(... for ... if ...)` with no
  default, an opaque `StopIteration` on any miss.
  `select_metadata_for_elements` below builds a lookup once instead of
  re-scanning per selection, and returns `Unavailable` with which element
  failed to match, not an undiagnosable crash.

`_requires_sssp` (a private helper called from three separate places in v1)
is `requires_sssp` here: one explicit, named, directly-testable policy.

**`match_selected_metadata` (this port's first attempt at the above,
v2 epic 5) removed (v2 epic 9, #9).** It matched a v1 `SelectionRecord`
-shaped dict back to metadata -- a genuine v1 dependency that would have
outlived v1's own deletion with nothing left able to construct its input
type. `select_metadata_for_elements` (v2 epic 8, #8) is the real
production path (`service/_pseudo.py`) and was already a full,
independent replacement, never built on top of this one; it was simply
never deleted once its predecessor stopped being used. Confirmed unused
outside its own module and tests before removal.
"""

from __future__ import annotations

from dataclasses import dataclass

from pymatgen.core.periodic_table import Element

from goldilocks_core.assets.pseudopotentials.registry import PseudoTable
from goldilocks_core.assets.pseudopotentials.upf import PseudoMetadata
from goldilocks_core.resolution import FieldState, Provenance, Resolved, Unavailable
from goldilocks_core.types import PseudoAccuracy, RelativisticTreatment


@dataclass(frozen=True, slots=True)
class PseudoRequirements:
    functional: str
    accuracy: PseudoAccuracy
    relativistic: RelativisticTreatment


def pseudo_requirements(
    functional: str,
    *,
    spin_orbit_enabled: bool,
    accuracy: PseudoAccuracy = "efficiency",
) -> PseudoRequirements:
    """`relativistic` follows `magnetic_config`'s `spin_orbit_enabled`
    (this epic), not v1's `spin_orbit["enabled"]` bool from the same-shaped
    but now-superseded `advice/parameters.py` cascade -- same rule, new
    source."""
    return PseudoRequirements(
        functional=functional,
        accuracy=accuracy,
        relativistic="full" if spin_orbit_enabled else "scalar",
    )


def requires_sssp(elements: set[str]) -> bool:
    """Lanthanides and actinides only have reliable pseudopotential
    coverage in the SSSP tables today; PseudoDojo's coverage for these
    elements is incomplete/unreliable for automatic selection."""
    return any(
        Element(symbol).is_lanthanoid or Element(symbol).is_actinoid
        for symbol in elements
    )


def select_pseudopotential_table(
    tables: dict[str, PseudoTable],
    *,
    table_id: str | None,
    elements: set[str],
    requirements: PseudoRequirements,
) -> FieldState[PseudoTable]:
    if table_id is not None:
        return _select_explicit_table(tables, table_id, elements, requirements)
    return _select_automatic_table(tables, elements, requirements)


def _select_explicit_table(
    tables: dict[str, PseudoTable],
    table_id: str,
    elements: set[str],
    requirements: PseudoRequirements,
) -> FieldState[PseudoTable]:
    table = tables.get(table_id)
    if table is None:
        choices = ", ".join(sorted(tables))
        return Unavailable(
            reason=f"unknown pseudopotential table {table_id!r}; available: {choices}"
        )
    if not _table_problems(table, elements, requirements):
        return _selected(table, pinned=True)
    return _refusal(tables, elements, requirements, pinned=table)


def _select_automatic_table(
    tables: dict[str, PseudoTable],
    elements: set[str],
    requirements: PseudoRequirements,
) -> FieldState[PseudoTable]:
    matches = [
        table
        for table in tables.values()
        if not _table_problems(table, elements, requirements)
    ]
    if not matches:
        return _refusal(tables, elements, requirements, pinned=None)
    provider = "sssp" if requires_sssp(elements) else "pseudodojo"
    table = min(
        matches, key=lambda candidate: (candidate.provider != provider, candidate.id)
    )
    return _selected(table, pinned=False)


def _selected(table: PseudoTable, *, pinned: bool) -> Resolved[PseudoTable]:
    """``table`` as the selection, citing it: a bundle cites what its records
    cite (#156). A pinned ``pseudo_table_id`` is the request's choice
    (``human``); an automatic one is the heuristic's, from requirements set
    by the ``functional`` and ``magnetic`` records (``pseudo_requirements``:
    the spin-orbit switch picks the relativistic treatment), which it names
    (#173)."""
    citations = (table.citation,)
    if pinned:
        return Resolved(
            table,
            Provenance.from_field_sources(
                {"pseudo_table_id": "human"}, citations=citations
            ),
        )
    provenance = Provenance(
        source="heuristic", derived_from=("functional", "magnetic"), citations=citations
    )
    return Resolved(table, provenance)


def _refusal(
    tables: dict[str, PseudoTable],
    elements: set[str],
    requirements: PseudoRequirements,
    *,
    pinned: PseudoTable | None,
) -> Unavailable:
    """Return the refusal for a request no registered table satisfies, built
    from `_table_problems` in table-id order.

    A pinned table reports its own problems and the tables that would satisfy
    the request. Otherwise each near-miss table (functional and accuracy match
    the request) reports its problems, or the reason says no table has that
    functional and accuracy (#182).
    """
    ordered = sorted(tables.values(), key=lambda table: table.id)
    problems = {
        table.id: _table_problems(table, elements, requirements) for table in ordered
    }
    if pinned is not None:
        matching = ", ".join(key for key, found in problems.items() if not found)
        return Unavailable(
            reason=(
                f"pseudopotential table {pinned.id!r} does not satisfy the request: "
                f"{'; '.join(problems[pinned.id])}; matching tables: "
                f"{matching or 'none'}"
            )
        )
    near_misses = "; ".join(
        f"{table.id}: {' and '.join(problems[table.id])}"
        for table in ordered
        if table.functional == requirements.functional
        and table.accuracy == requirements.accuracy
    )
    rejections = near_misses or (
        f"no registered table has functional {requirements.functional} "
        f"and accuracy {requirements.accuracy}"
    )
    requested = (
        f"{requirements.functional} {requirements.accuracy} {requirements.relativistic}"
    )
    return Unavailable(
        reason=(
            f"no pseudopotential table satisfies {requested} for "
            f"{', '.join(sorted(elements))}: {rejections}"
        )
    )


def is_table_eligible(table: PseudoTable, elements: set[str]) -> bool:
    """Return whether a table may serve every element under Core policy."""
    return all(element in table.elements for element in elements) and (
        not requires_sssp(elements) or table.provider == "sssp"
    )


def _table_problems(
    table: PseudoTable,
    elements: set[str],
    requirements: PseudoRequirements,
) -> list[str]:
    problems: list[str] = []
    if table.functional != requirements.functional:
        problems.append(
            f"functional is {table.functional}, requested {requirements.functional}"
        )
    if table.accuracy != requirements.accuracy:
        problems.append(
            f"accuracy is {table.accuracy}, requested {requirements.accuracy}"
        )
    if table.relativistic != requirements.relativistic:
        problems.append(
            f"relativistic treatment is {table.relativistic}, "
            f"requested {requirements.relativistic}"
        )
    if requires_sssp(elements) and table.provider != "sssp":
        problems.append("lanthanide and actinide elements require an SSSP table")
    missing = sorted(elements - set(table.elements))
    if missing:
        problems.append("missing elements " + ", ".join(missing))
    return problems


def select_metadata_for_elements(
    metadata: tuple[PseudoMetadata, ...], elements: set[str]
) -> FieldState[tuple[PseudoMetadata, ...]]:
    """Narrow one already-chosen table's full metadata down to exactly the
    requested elements (v2 epic 8, #8).

    This is deliberately not a port of v1's `selection.py` cross-table
    `_select_for_element`/`_candidate_rank` ranking machinery: that exists to
    rank candidates drawn from *multiple* tables/functionals/accuracies at
    once -- the problem v1 had because it never committed to one table
    before picking per-element files. v2's `select_pseudopotential_table`
    already commits to one table first, and `_table_problems` there already
    confirmed that table's functional/accuracy/relativistic and element
    coverage satisfy the request. Every entry in `metadata` (one table's
    installed manifest, loaded via
    `assets.pseudopotentials.importers.load_installed_table`) therefore
    already satisfies the request -- there is nothing left to rank, only to
    look up by element and confirm the table gives exactly one file per
    element (not zero, not several). The selection follows the table, so it
    names the ``pseudo_table`` record (#173)."""
    by_element: dict[str, list[PseudoMetadata]] = {}
    for item in metadata:
        if item.element is not None:
            by_element.setdefault(item.element, []).append(item)
    selected: list[PseudoMetadata] = []
    for element in sorted(elements):
        candidates = by_element.get(element, [])
        if not candidates:
            return Unavailable(
                reason=f"no pseudopotential for {element!r} in the selected table"
            )
        if len(candidates) > 1:
            return Unavailable(
                reason=(
                    f"selected table has {len(candidates)} pseudopotentials for "
                    f"{element!r}; expected exactly one per element"
                )
            )
        selected.append(candidates[0])
    return Resolved(
        tuple(selected), Provenance(source="heuristic", derived_from=("pseudo_table",))
    )
