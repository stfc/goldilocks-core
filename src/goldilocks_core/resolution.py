"""The v2 field-resolution primitive: three independent axes per field.

    source axis   human > ml > llm > heuristic     which knowledge the
                                                    value came from
    scope axis    per-step > global                which steps the
                                                    value governs
    status axis   resolved / unavailable / blocked whether the value
                                                    exists at all

This module owns the source and status axes (``Provenance``/``Source``
and ``Resolved``/``Unavailable``/``Blocked``); the scope axis has no
code yet, it shows up once per-step settings exist (v2 epic 6).

Kept as one top-level module, not a package: ``Provenance`` needed a
fresh v2-only shape (``Source`` is the clean four-tier list, not v1's
six-value, two-concerns-conflated ``ProvenanceSource``) and couldn't
reuse v1's existing ``goldilocks_core.provenance`` module without
breaking the v1 code that constructed the old shape -- but a type that
every ``Resolved`` field must carry is exactly the kind of genuinely
cross-cutting primitive that belongs at top level, next to
``kmesh.py``/``functionals.py``/``units.py``, not inside any one
``analysis/``/``advisors/`` module (goldilocks-core-design.md S13:
three named top-level files, no ``utils/``). v1's ``provenance.py``
was left untouched until v1's own advisors -- and the module itself --
were deleted along with the rest of the v1 tree (v2 epic 9, commit
d64f46b).

``Resolved``/``Unavailable``/``Blocked`` are core's *internal*
representation, used inside analysis/ and advisors/. They are
deliberately not pydantic models and never appear directly on a
settings/facts class: goldilocks-core-design.md's "day-one blocker"
section requires those classes to store the serializable *projection*
(``ResolvedField``, below) instead. This is not v1's abandoned
dual-projection design come back (``to_jsonable``/``to_portable`` were
two projections of *one* type) -- it is two type *families*, the same
technique already used for "public records vs local handles".

No ``contracts/`` package here, on purpose: v1 already tried
centralizing every record into one hub (``goldilocks_core.contracts``,
deleted 2026-09-02, "records and serialization merge into the
behavioral modules that own them") and reversed it after it caused
import cycles and organizational drift -- see the ruff ``banned-api``
entry for ``goldilocks_core.contracts``. The v2 design doc's proposed
``contracts/`` tree didn't know about that history when it was
written; per-domain contract classes (e.g. ``analysis/is_metal.py``
defining its own Fact model) is the resolution, decided with the user
2026-09-14. Only ``Provenance``/``Source`` and the tri-state itself are
exempt, for the reason above: they have no single owning domain.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal, get_args

from pydantic import BaseModel, ConfigDict, JsonValue

from goldilocks_core.serialization import to_portable

if TYPE_CHECKING:
    from goldilocks_core.inputs.overrides import HumanInput

Status = Literal["resolved", "unavailable", "blocked"]

Source = Literal["human", "ml", "llm", "heuristic"]
"""Order is priority, highest first: a human-set value always wins
over one an ml model, llm, or heuristic would have chosen; likewise ml
over llm over heuristic."""

_TIERS: tuple[Source, ...] = get_args(Source)

WarningLevel = Literal["info", "warning", "error"]


class Warning(BaseModel):
    """A machine-actionable warning an advisor's decision can carry
    alongside its value (goldilocks-agent-design.md: the tool-response
    ``warnings`` array must be structured, not prose-only, so an agent
    can relay/filter/group it without parsing text).

    ``code`` is a stable identifier (``"<record>.<slug>"``, e.g.
    ``"job.walltime_defaulted"``) an advisor commits not to rename once
    shipped -- callers may match on it. ``category`` is the same record
    name used throughout ``Advice.records()``/``capabilities()``
    (``"job"``, ``"hubbard"``, ...): reusing that existing, already
    -stable vocabulary instead of inventing a second one a frontend
    would need a separate legend for. ``message`` is the text a user
    reads, verbatim (the Workbench, the CLI and the MCP tools show it
    as is), with any per-occurrence values (an element, a number)
    already interpolated in: it names settings by their keys and values,
    with no module names, internal literals or design-document ids
    (#151). The whole reason this array exists is so a caller never has
    to parse the text to know what happened."""

    code: str
    level: WarningLevel
    category: str
    message: str


class ModelEvidence(BaseModel):
    """What a registered ML model returned for the record it decided, as
    ``ml.predict`` received it from goldilocks-ml (whose ``ModelPrediction``
    says ``details`` and ``warnings`` are opaque provenance, to be recorded
    verbatim, #156). ``details`` and ``value`` have passed a strict JSON round
    trip, so they publish unchanged."""

    model_id: str
    """goldilocks-ml's id for the model and its feature contract, e.g.
    ``metallicity.is_metal.cgcnn@crystal_graph.v1``."""
    asset: str
    """The registered asset the model was loaded from, ``<id>@<version>``
    (``models/is-metal-classifier@1``), as ``ml/registry.toml`` pins it."""
    target_contract: str
    """The contract the model's value answers, e.g.
    ``goldilocks.is_metal.dft_band_gap_zero.v1``."""
    value: JsonValue
    """The model's own value, before the record maps it (``False``, not
    ``non_metal``; QRF95's median k-distance in 1/angstrom)."""
    details: dict[str, JsonValue]
    """The model's details as returned: a classifier's ``score`` and
    ``threshold``, QRF95's own ``interval`` (not ``k_sampling``'s
    ``k_distance_interval``, the rung's, #116)."""
    warnings: tuple[Warning, ...] = ()
    """Each of the model's warnings, its text the ``message`` of the
    catalogued ``<record>.model_warning`` (``ml.predict.WARNING_CATALOGUE``).
    ``collect_warnings`` lists them with the record's own."""


class Provenance(BaseModel):
    """Where a resolved value came from. ``ResolvedField`` publishes every
    field: one added here needs a twin of the same name there, or every
    projection fails instead of dropping it (#156). Unknown keywords are
    refused, so a misspelt field cannot be dropped at construction either.

    An advisor whose decision applies several settings builds its
    provenance with ``from_field_sources`` over ``field_sources_from``, from
    the inputs it consumed, so a setting the request set reads ``human``
    exactly when the decision applied it (#173)."""

    model_config = ConfigDict(extra="forbid")

    source: Source
    source_note: str | None = None
    """Free-text detail v1's split ``ProvenanceSource`` values used to
    carry structurally (e.g. "derived from structure analysis" vs
    "package default, nothing else applied") -- now just prose here
    instead of a family of source literals."""
    field_sources: dict[str, Source] | None = None
    """One source per setting a compound decision applied, keyed by its
    override field name (``ConvergenceDecision``'s ``conv_thr``/
    ``mixing_beta``/...; ``magnetic``'s ``spin_orbit_coupling``): ``human``
    or ``llm`` for a value that tier set, otherwise the tier that decided
    it. A setting the decision did not apply (a smearing width under fixed
    occupations, a smearing function under tetrahedra) has no entry.
    ``source`` is then the highest tier among them (``from_field_sources``).
    ``None`` for a decision that applies no setting of its own (an analysis
    fact, the selected pseudopotentials), and for those still labelled as a
    whole (``cutoffs``, ``job``, ``nbnd``, ``parallelisation``, ``vdw``)."""
    derived_from: tuple[str, ...] = ()
    """The records whose answers this record's own rule followed, by
    record name: ``("is_metal",)`` for occupations chosen from the
    metallicity fact, ``("magnetic",)`` for the relativistic treatment
    spin-orbit coupling asks for. ``source`` stays the tier that applied
    the rule (``heuristic``), never the upstream record's, so the link is
    how a reader finds what decided it (#173)."""
    model: ModelEvidence | None = None
    """The model that decided the value, or its ``ml`` field
    (``field_sources``), and what it returned
    (``ml.predict.MlPrediction.provenance``)."""
    citations: tuple[str, ...] = ()
    """What to cite for the value: the registry citation of the model that
    decided it, or of the pseudopotential table selected. A bundle's
    ``CITATIONS.md`` lists every record's (``collect_citations``)."""

    @classmethod
    def from_field_sources(
        cls, field_sources: Mapping[str, Source], **provenance: Any
    ) -> Provenance:
        """The provenance of a decision whose applied settings came from
        ``field_sources`` (at least one): ``source`` is the highest tier
        among them, in ``Source``'s order, so a decision with one
        request-set setting reads ``human``. ``provenance`` sets the other
        fields (``derived_from``, ``model``, ``citations``)."""
        return cls(
            source=min(field_sources.values(), key=_TIERS.index),
            field_sources=dict(field_sources),
            **provenance,
        )


def field_sources_from(
    human: HumanInput | None,
    llm: HumanInput | None = None,
    *,
    fields: Iterable[str],
    decided: Mapping[str, Source] | None = None,
) -> dict[str, Source]:
    """One source per setting in ``fields``, the settings a decision
    applied: ``"human"`` when ``human`` set it, else ``"llm"`` when ``llm``
    set it, else its tier in ``decided`` (the tier that chose it, such as
    QRF95's ``"ml"`` k_distance), else ``"heuristic"``. A field is set when
    the input has it and its value is not ``None``.

    The caller passes only the fields its decision applied and only the
    inputs it read -- ``None`` for an input a higher tier overrode -- so a
    request-set setting reads ``human`` exactly when its value is in the
    decision (#173)."""
    decided = decided or {}
    return {
        name: (
            "human"
            if getattr(human, name, None) is not None
            else "llm"
            if getattr(llm, name, None) is not None
            else decided.get(name, "heuristic")
        )
        for name in fields
    }


class BlockedValueError(Exception):
    """Raised by touching any attribute of a ``Blocked`` field other
    than ``by``/``ok``/``status``. Getting this exception where a value
    was expected means a caller forgot to check ``.ok`` before using a
    field -- the whole point of the poison-object design is that this
    is a loud, immediate crash instead of a silently-wrong number."""


@dataclass(frozen=True, slots=True)
class Resolved[T]:
    """A field that has a real value. Falling back to a lower source
    tier (e.g. no ml model installed, heuristic decided instead) is
    still ``Resolved`` -- source and status are independent axes;
    degrading tiers is not the same thing as not having a value."""

    value: T
    provenance: Provenance
    ok: ClassVar[bool] = True
    status: ClassVar[Status] = "resolved"

    @property
    def source(self) -> str:
        return self.provenance.source


@dataclass(frozen=True, slots=True)
class Unavailable:
    """A field genuinely not determinable after trying every source
    tier. Not an error: ``advise()`` must still return a result with
    this field explicitly unavailable and why, per the "diagnosis is
    always available" promise."""

    reason: str
    ok: ClassVar[bool] = False
    status: ClassVar[Status] = "unavailable"


@dataclass(frozen=True, slots=True)
class Blocked:
    """A field that cannot even be computed because something it
    depends on already failed. ``by`` is the upstream ``FieldState``
    (usually another ``Blocked``) that caused this, so walking ``.by``
    repeatedly reaches the root cause without a separate error-message
    system -- see ``root_cause``.

    Any attribute access other than ``by``/``ok``/``status`` raises
    ``BlockedValueError`` instead of returning a normal-looking value.
    This is deliberate: propagation is hand-written
    (``if not x.ok: return Blocked(by=x)``), not automatic, because
    automatic propagation is a framework with no cheap fallback for its
    own bugs. The poison object is that fallback for the hand-written
    version -- forgetting a check crashes immediately instead of
    computing a silently-wrong number.
    """

    by: Blocked | str
    ok: ClassVar[bool] = False
    status: ClassVar[Status] = "blocked"

    def __getattr__(self, name: str) -> None:
        raise BlockedValueError(
            f"{self.root_cause()!r} is missing, {name!r} is not available"
        )

    def root_cause(self) -> str:
        """Walk the ``by`` chain to the original string reason."""
        cause = self.by
        while isinstance(cause, Blocked):
            cause = cause.by
        return cause


type FieldState[T] = Resolved[T] | Unavailable | Blocked
"""``Resolved[T] | Unavailable | Blocked``. Written out as a plain
union rather than a generic alias class: matches the design doc's own
notation and keeps ``isinstance``/``match`` working directly on the
three real classes above, with no extra indirection."""


def blocked_by(state: Unavailable | Blocked) -> Blocked | str:
    """Turn a failed upstream ``FieldState`` into a value ``Blocked.by``
    accepts, for functions that depend on another analysis/advisors fact
    rather than only on raw input (v2 epic 4, #1's ``needs_soc`` reading
    ``composition`` is the first real case). ``Blocked.by``'s type is
    ``Blocked | str``, not ``FieldState`` -- passing an ``Unavailable``
    straight through would silently break ``root_cause()``'s walk, since it
    stops at the first non-``Blocked`` value and returns it as-is, whatever
    it is. This function is the one place that distinction gets handled:
    an ``Unavailable``'s ``reason`` becomes the string cause, and a
    ``Blocked`` passes through unchanged so the chain stays walkable."""
    if isinstance(state, Blocked):
        return state
    return state.reason


class ResolvedField[T](BaseModel):
    """The serializable projection of a ``FieldState[T]``, for storage
    on a settings/facts class -- this answers the design doc's
    "day-one blocker" directly: a contract field's declared type is
    ``ResolvedField[SomeType]``, never ``FieldState[SomeType]``.
    Because this is an ordinary pydantic model, ``model_dump()``,
    OpenAPI schema generation, and the ``capabilities`` auto-generation
    all see a plain, already-supported shape -- never the poison
    object. Build one with ``ResolvedField.from_state``, not the
    constructor directly, so the fields below can't be filled in an
    inconsistent combination (e.g. a ``status`` of ``"blocked"`` next
    to a non-``None`` ``value``). ``from_state`` keeps the value as
    resolved, a ``T``; ``records_document`` publishes the field as
    ``serialization.to_portable`` projects it: plain JSON, without
    host-local fields.

    A resolved field carries every ``Provenance`` field under its own name
    (``source``, ``source_note``, ``field_sources``, ``derived_from``,
    ``model``, ``citations``). Extra keys are forbidden and ``from_state`` passes the
    whole provenance, so a ``Provenance`` field without a twin here fails
    projection rather than being dropped from every published record
    (#156)."""

    model_config = ConfigDict(extra="forbid")

    status: Status
    value: T | None = None
    source: Source | None = None
    source_note: str | None = None
    field_sources: dict[str, Source] | None = None
    derived_from: tuple[str, ...] = ()
    model: ModelEvidence | None = None
    citations: tuple[str, ...] = ()
    reason: str | None = None
    blocked_by: str | None = None

    @classmethod
    def from_state(cls, state: FieldState[T]) -> ResolvedField[T]:
        if isinstance(state, Resolved):
            return cls(
                status=state.status,
                value=state.value,
                **dict(state.provenance),
            )
        if isinstance(state, Unavailable):
            return cls(status=state.status, reason=state.reason)
        return cls(status=state.status, blocked_by=state.root_cause())


def records_document(
    records: Mapping[str, FieldState[object]],
) -> dict[str, dict[str, Any]]:
    """The published form of a records mapping (``Advice.records()``), in
    record-name order: each record's ``ResolvedField`` as
    ``serialization.to_portable`` projects it, a plain dict. The one
    projection the HTTP/MCP responses, CLI ``--json`` and ``goldilocks.json``
    share (#152).

    Plain dicts, because HTTP returns these documents as ``JSONResponse``,
    which encodes with ``json.dumps`` and knows nothing of pydantic
    models. Floats stay as they are: the document is strict JSON only
    because no record holds a non-finite float, and ``JSONResponse``, CLI
    ``--json`` and ``goldilocks.json`` all raise on one (#137). Sequences
    are lists, as JSON reads them back."""
    return {
        name: to_portable(ResolvedField.from_state(state))
        for name, state in sorted(records.items())
    }


def collect_warnings(
    records: Mapping[str, FieldState[object]],
) -> list[dict[str, object]]:
    """Every ``Warning`` the resolved records carry, in record-name order,
    each as ``{"code", "level", "category", "message", "record"}``:
    ``record`` names the record it came from, which tells apart the same
    code raised by two records (a ``dos`` task's ``parallelisation`` and
    ``nscf_parallelisation``).

    Reads the ``warnings`` tuple of each resolved value, before any
    projection, so every record shape is collected alike (#152), then the
    warnings of the model that decided it (``Provenance.model``, #156).
    Values without one (composition, symmetry, the pseudopotentials tuple,
    plain strings) and unresolved records contribute nothing."""
    return [
        {**warning.model_dump(), "record": name}
        for name, state in sorted(records.items())
        if isinstance(state, Resolved)
        for warning in _record_warnings(state)
    ]


def _record_warnings(state: Resolved[object]) -> tuple[Warning, ...]:
    model = state.provenance.model
    return (*getattr(state.value, "warnings", ()), *(model.warnings if model else ()))


def collect_citations(records: Mapping[str, FieldState[object]]) -> list[str]:
    """Every distinct citation the resolved records' provenance carries
    (``Provenance.citations``), sorted: what a bundle's ``CITATIONS.md`` and
    its manifest's ``citations`` list (#156)."""
    return sorted(
        {
            citation
            for state in records.values()
            if isinstance(state, Resolved)
            for citation in state.provenance.citations
        }
    )
