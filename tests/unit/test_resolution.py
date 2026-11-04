from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

import pytest
from pydantic import BaseModel
from pymatgen.core import Lattice, Structure

from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.resolution import (
    Blocked,
    BlockedValueError,
    FieldState,
    ModelEvidence,
    Provenance,
    Resolved,
    ResolvedField,
    Unavailable,
    Warning,
    blocked_by,
    collect_citations,
    collect_warnings,
    field_sources_from,
    records_document,
)
from goldilocks_core.serialization import Portable


def test_resolved_carries_value_and_source() -> None:
    state = Resolved(0.4, Provenance(source="heuristic"))

    assert state.ok is True
    assert state.status == "resolved"
    assert state.value == 0.4
    assert state.source == "heuristic"


def test_unavailable_is_not_ok_but_readable() -> None:
    state = Unavailable(reason="no ml model installed")

    assert state.ok is False
    assert state.status == "unavailable"
    assert state.reason == "no ml model installed"


def test_blocked_by_is_safe_but_every_other_attribute_poisons() -> None:
    state = Blocked(by="pseudopotential selection failed")

    assert state.ok is False
    assert state.status == "blocked"
    assert state.by == "pseudopotential selection failed"

    with pytest.raises(BlockedValueError, match="pseudopotential selection failed"):
        state.value  # noqa: B018 - deliberately accessing to trigger the poison


def test_blocked_chain_walks_to_the_original_root_cause() -> None:
    root = Blocked(by="Ce has no fully-relativistic pseudopotential")
    downstream = Blocked(by=root)
    further_downstream = Blocked(by=downstream)

    assert downstream.root_cause() == "Ce has no fully-relativistic pseudopotential"
    assert further_downstream.root_cause() == (
        "Ce has no fully-relativistic pseudopotential"
    )


def test_blocked_by_extracts_the_reason_from_an_unavailable_upstream() -> None:
    """v2 epic 4 (#1): the first real fact-depends-on-fact case
    (analysis/needs_soc.py reading analysis/composition.py) found that
    stuffing an Unavailable straight into Blocked.by breaks root_cause()'s
    walk, since Blocked.by's type is Blocked | str, not FieldState."""
    upstream = Unavailable(reason="composition could not be determined")

    result = blocked_by(upstream)

    assert result == "composition could not be determined"
    assert Blocked(by=result).root_cause() == "composition could not be determined"


def test_blocked_by_passes_a_blocked_upstream_through_unchanged() -> None:
    upstream = Blocked(by="Ce has no fully-relativistic pseudopotential")

    result = blocked_by(upstream)

    assert result is upstream
    assert Blocked(by=result).root_cause() == (
        "Ce has no fully-relativistic pseudopotential"
    )


def _double_if_resolved(state: FieldState[float]) -> FieldState[float]:
    """A toy advisor-shaped function following the mandatory hand-written
    propagation pattern (goldilocks-core-design.md S4.2 SS2): check ``.ok``
    first, return ``Blocked`` if not, otherwise compute normally."""
    if not state.ok:
        return Blocked(by=state)
    return Resolved(state.value * 2, state.provenance)


def _double_without_checking(state: FieldState[float]) -> FieldState[float]:
    """The bug this whole design exists to catch: forgot the ``.ok`` check."""
    return Resolved(state.value * 2, state.provenance)


class TestPoisonObjectPropagation:
    """The design doc's own mandatory test: swap any advisor's upstream for
    ``Blocked``, it must either return ``Blocked`` or raise
    ``BlockedValueError`` -- never a normal value."""

    def test_a_correct_advisor_propagates_blocked(self) -> None:
        upstream = Blocked(by="pseudopotential selection failed")

        result = _double_if_resolved(upstream)

        assert isinstance(result, Blocked)
        assert result.root_cause() == "pseudopotential selection failed"

    def test_a_buggy_advisor_that_skips_the_check_crashes_instead_of_computing(
        self,
    ) -> None:
        upstream = Blocked(by="pseudopotential selection failed")

        with pytest.raises(BlockedValueError):
            _double_without_checking(upstream)

    def test_a_correct_advisor_still_computes_on_a_resolved_upstream(self) -> None:
        upstream = Resolved(3.0, Provenance(source="heuristic"))

        result = _double_if_resolved(upstream)

        assert isinstance(result, Resolved)
        assert result.value == 6.0


class TestResolvedFieldBoundaryProjection:
    """The day-one blocker's actual answer: settings/facts classes never hold FieldState
    directly."""

    def test_resolved_projects_to_a_plain_serializable_shape(self) -> None:
        projection = ResolvedField[float].from_state(
            Resolved(0.4, Provenance(source="heuristic"))
        )

        assert projection.model_dump() == {
            "status": "resolved",
            "value": 0.4,
            "source": "heuristic",
            "field_sources": None,
            "derived_from": (),
            "source_note": None,
            "model": None,
            "citations": (),
            "reason": None,
            "blocked_by": None,
        }

    def test_unavailable_projects_with_a_reason_and_no_value(self) -> None:
        projection = ResolvedField[float].from_state(
            Unavailable(reason="no ml model installed")
        )

        assert projection.status == "unavailable"
        assert projection.value is None
        assert projection.reason == "no ml model installed"

    def test_blocked_projects_with_blocked_by_and_no_value(self) -> None:
        projection = ResolvedField[float].from_state(
            Blocked(by="pseudopotential selection failed")
        )

        assert projection.status == "blocked"
        assert projection.value is None
        assert projection.blocked_by == "pseudopotential selection failed"

    def test_projection_is_json_serializable(self) -> None:
        projection = ResolvedField[float].from_state(
            Resolved(0.4, Provenance(source="heuristic"))
        )

        assert projection.model_dump_json()

    def test_a_typed_field_keeps_the_value_it_declares(self) -> None:
        """The value is the ``T`` the field declares; only publication
        (``records_document``) projects it, dropping host-local fields."""
        window = _Window(low=-5.0, host_path="/home/someone/run")
        state = Resolved(window, Provenance(source="heuristic"))

        projection = ResolvedField[_Window].from_state(state)

        assert projection.value == window
        assert records_document({"window": state})["window"]["value"] == {"low": -5.0}


@dataclass(frozen=True, slots=True)
class _Window:
    low: float
    host_path: Annotated[str | None, Portable()] = None


_UNVALIDATED = (
    "magnetism.is_magnetic.mace_mlp@mace_probe_embedding.v1 has not been "
    "externally validated (MP-ALOE external validation has not been run.)"
)
_IS_MAGNETIC_EVIDENCE = ModelEvidence(
    model_id="magnetism.is_magnetic.mace_mlp@mace_probe_embedding.v1",
    asset="models/is-magnetic-classifier@1",
    target_contract="goldilocks.is_magnetic.dft_max_site_magmom_0p5ub.v1",
    value=True,
    details={"score": 0.3598, "threshold": 0.3239, "label": "magnetic"},
    warnings=(
        Warning(
            code="is_magnetic.model_warning",
            level="warning",
            category="is_magnetic",
            message=_UNVALIDATED,
        ),
    ),
)
"""TiNi (MC3D mc3d-31340) as the is_magnetic model classified it (#156)."""


class TestResolvedFieldPublishesTheWholeProvenance:
    """#156: ``ResolvedField`` copied only ``source`` and ``field_sources``,
    so the model behind an ``ml`` record and every advisor's rationale never
    reached ``/explain``, ``/run`` or ``goldilocks.json``."""

    def test_every_provenance_field_has_a_resolved_field_of_its_name(self) -> None:
        assert set(Provenance.model_fields) <= set(ResolvedField.model_fields)

    def test_from_state_round_trips_every_provenance_field(self) -> None:
        provenance = Provenance(
            source="ml",
            source_note="classified by the published mMACE + MLP classifier",
            field_sources={"is_magnetic": "ml"},
            derived_from=("composition",),
            model=_IS_MAGNETIC_EVIDENCE,
            citations=("Goldilocks mMACE + MLP magnetism classifier.",),
        )
        unset = [
            name
            for name, field in Provenance.model_fields.items()
            if getattr(provenance, name) == field.get_default(call_default_factory=True)
        ]
        assert unset == [], "the round trip must set every Provenance field"

        projection = ResolvedField.from_state(Resolved("magnetic", provenance))

        published = projection.model_dump(include=set(Provenance.model_fields))
        assert Provenance.model_validate(published) == provenance


class _MixingHumanInput(HumanInput):
    conv_thr: float | None = None
    mixing_beta: float | None = None
    mixing_mode: str | None = None


class _MixingLlmInput(LlmInput):
    mixing_beta: float | None = None
    mixing_mode: str | None = None


class TestFieldSources:
    """#173: a record's provenance follows what its advisor consumed, so a
    field the request set reads ``human`` exactly when the decision applied
    it, and ``source`` is the highest tier among the fields."""

    def test_each_applied_field_reads_the_tier_that_set_it(self) -> None:
        sources = field_sources_from(
            _MixingHumanInput(mixing_beta=0.3),
            _MixingLlmInput(mixing_beta=0.2, mixing_mode="local-TF"),
            fields=("conv_thr", "mixing_beta", "mixing_mode"),
        )

        assert sources == {
            "conv_thr": "heuristic",
            "mixing_beta": "human",
            "mixing_mode": "llm",
        }

    def test_a_field_the_decision_did_not_apply_gets_no_entry(self) -> None:
        sources = field_sources_from(
            _MixingHumanInput(conv_thr=1e-9, mixing_mode="plain"),
            None,
            fields=("mixing_beta",),
        )

        assert sources == {"mixing_beta": "heuristic"}

    def test_a_decided_tier_names_who_chose_a_field_the_request_left_unset(
        self,
    ) -> None:
        """An advisor passes the tier that decided a field (QRF95's
        k_distance, the spin decision); a request-set field stays human."""
        sources = field_sources_from(
            _MixingHumanInput(mixing_mode="plain"),
            _MixingLlmInput(mixing_beta=0.2),
            fields=("conv_thr", "mixing_beta", "mixing_mode"),
            decided={"conv_thr": "ml", "mixing_mode": "ml"},
        )

        assert sources == {
            "conv_thr": "ml",
            "mixing_beta": "llm",
            "mixing_mode": "human",
        }

    @pytest.mark.parametrize(
        ("field_sources", "source"),
        [
            ({"a": "heuristic"}, "heuristic"),
            ({"a": "heuristic", "b": "llm"}, "llm"),
            ({"a": "llm", "b": "ml", "c": "heuristic"}, "ml"),
            ({"a": "ml", "b": "human", "c": "llm"}, "human"),
        ],
    )
    def test_the_record_source_is_the_highest_tier_among_its_fields(
        self, field_sources: dict, source: str
    ) -> None:
        provenance = Provenance.from_field_sources(
            field_sources, derived_from=("is_metal",), citations=("A paper.",)
        )

        assert provenance == Provenance(
            source=source,
            field_sources=field_sources,
            derived_from=("is_metal",),
            citations=("A paper.",),
        )

    def test_derived_from_is_published_with_the_record(self) -> None:
        records = {
            "occupations": Resolved(
                "smearing",
                Provenance.from_field_sources(
                    {"occupations": "heuristic"}, derived_from=("is_metal",)
                ),
            )
        }

        document = records_document(records)

        assert document["occupations"]["source"] == "heuristic"
        assert document["occupations"]["field_sources"] == {"occupations": "heuristic"}
        assert document["occupations"]["derived_from"] == ["is_metal"]


@dataclass(frozen=True, slots=True)
class _Decision:
    """A record value shaped like every advisor decision: a frozen
    dataclass carrying its own ``warnings`` tuple."""

    value: float
    cell: Structure | None = None
    host_path: Annotated[str | None, Portable()] = None
    warnings: tuple[Warning, ...] = ()


def _notice(code: str, message: str) -> Warning:
    return Warning(
        code=code, level="info", category=code.split(".")[0], message=message
    )


class TestRecordsDocument:
    """#152: the one projection of a records mapping, shared by the
    responses, the CLI and goldilocks.json."""

    def test_publishes_the_model_rationale_and_citations_of_a_record(self) -> None:
        """#156: an ``ml`` record names its model and keeps what it returned,
        and any record keeps its rationale and citations."""
        records = {
            "is_magnetic": Resolved(
                "magnetic",
                Provenance(
                    source="ml",
                    model=_IS_MAGNETIC_EVIDENCE,
                    citations=("Goldilocks mMACE + MLP magnetism classifier.",),
                ),
            ),
            "boundary": Resolved(
                "molecule",
                Provenance(
                    source="heuristic",
                    source_note="molecule structure in a periodic cell",
                ),
            ),
        }

        document = records_document(records)

        assert document["is_magnetic"]["model"] == {
            "model_id": "magnetism.is_magnetic.mace_mlp@mace_probe_embedding.v1",
            "asset": "models/is-magnetic-classifier@1",
            "target_contract": "goldilocks.is_magnetic.dft_max_site_magmom_0p5ub.v1",
            "value": True,
            "details": {"score": 0.3598, "threshold": 0.3239, "label": "magnetic"},
            "warnings": [
                {
                    "code": "is_magnetic.model_warning",
                    "level": "warning",
                    "category": "is_magnetic",
                    "message": _UNVALIDATED,
                }
            ],
        }
        assert document["is_magnetic"]["citations"] == [
            "Goldilocks mMACE + MLP magnetism classifier."
        ]
        assert document["boundary"]["source_note"] == (
            "molecule structure in a periodic cell"
        )
        assert document["boundary"]["model"] is None

    def test_projects_each_record_value_for_publication_in_name_order(self) -> None:
        cell = Structure(
            Lattice.cubic(5.43), ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]]
        )
        records = {
            "vdw": Blocked(by="geometry blocked upstream"),
            "decision": Resolved(
                _Decision(0.5, cell=cell, host_path="/home/someone/run"),
                Provenance(source="heuristic"),
            ),
            "hubbard": Unavailable(reason="no correlated elements"),
        }

        document = records_document(records)

        assert list(document) == ["decision", "hubbard", "vdw"]
        assert document["decision"] == {
            "status": "resolved",
            "value": {
                "value": 0.5,
                "cell": {"formula": "Si2", "nat": 2},
                "warnings": [],
            },
            "source": "heuristic",
            "field_sources": None,
            "derived_from": [],
            "source_note": None,
            "model": None,
            "citations": [],
            "reason": None,
            "blocked_by": None,
        }
        assert document["hubbard"]["reason"] == "no correlated elements"
        assert document["vdw"]["blocked_by"] == "geometry blocked upstream"


class TestCollectWarnings:
    """#152: one collector over the typed records, so no record shape can
    slip past it."""

    def test_includes_the_warnings_a_model_returned_with_its_record(self) -> None:
        """#156: the caveats a model returns with a prediction reach the
        top-level list, tagged with the record the model decided."""
        records = {
            "is_magnetic": Resolved(
                "magnetic",
                Provenance(source="ml", model=_IS_MAGNETIC_EVIDENCE),
            ),
        }

        assert collect_warnings(records) == [
            {
                "code": "is_magnetic.model_warning",
                "level": "warning",
                "category": "is_magnetic",
                "message": _UNVALIDATED,
                "record": "is_magnetic",
            }
        ]

    def test_tags_every_warning_with_its_record_in_record_name_order(self) -> None:
        scf = _notice("parallelisation.npool_load_imbalance", "npool=32 ...")
        nscf = _notice("parallelisation.npool_load_imbalance", "npool=64 ...")
        job = _notice("job.walltime_defaulted", "walltime not specified.")
        records = {
            "parallelisation": Resolved(
                _Decision(1.0, warnings=(scf,)), Provenance(source="heuristic")
            ),
            "nscf_parallelisation": Resolved(
                _Decision(2.0, warnings=(nscf,)), Provenance(source="heuristic")
            ),
            "job": Resolved(
                _Decision(3.0, warnings=(job,)), Provenance(source="human")
            ),
        }

        assert collect_warnings(records) == [
            {**job.model_dump(), "record": "job"},
            {**nscf.model_dump(), "record": "nscf_parallelisation"},
            {**scf.model_dump(), "record": "parallelisation"},
        ]

    def test_skips_values_without_warnings_and_unresolved_records(self) -> None:
        records = {
            "is_metal": Resolved("metal", Provenance(source="heuristic")),
            "pseudopotentials": Resolved((), Provenance(source="heuristic")),
            "vdw": Blocked(by="geometry blocked upstream"),
            "hubbard": Unavailable(reason="no correlated elements"),
        }

        assert collect_warnings(records) == []


class TestCollectCitations:
    """#156: a bundle cites what its records cite, so every model and table
    that shaped the input is listed, each once."""

    def test_lists_every_resolved_record_s_citations_once_in_sorted_order(
        self,
    ) -> None:
        paper = "Patyukova et al., Digital Discovery (2026)."
        records = {
            "pseudo_table": Resolved(
                "pseudodojo", Provenance(source="heuristic", citations=("van Setten",))
            ),
            "is_metal": Resolved("metal", Provenance(source="ml", citations=(paper,))),
            "k_sampling": Resolved(0.2, Provenance(source="ml", citations=(paper,))),
            "functional": Resolved("PBEsol", Provenance(source="heuristic")),
            "hubbard": Unavailable(reason="no correlated elements"),
        }

        assert collect_citations(records) == [paper, "van Setten"]


# --- Worked example: contract declaration -> resolution -> pydantic serialization ---
# Lives here, not in src/, because it exists to prove resolution.py's design works
# inside a real settings-shaped class, not to be a real advisor -- no consumer exists
# for a "convergence settings" contract until v2 epic 6 builds advisors/convergence.py.

HEURISTIC_MIXING_BETA = 0.4
"""v1's ``DEFAULT_MIXING_BETA`` (``advice/parameters.py``), unchanged."""


class _ConvergenceHumanInput(HumanInput):
    mixing_beta: float | None = None


def _resolve_mixing_beta(human: _ConvergenceHumanInput) -> FieldState[float]:
    """The source-axis pattern (goldilocks-core-design.md S4.2): one
    if/elif per tier, highest priority first. ml/llm are stubbed to "not
    available yet" rather than omitted, so this starts from a real
    4-branch shape instead of silently forgetting a tier -- matching how
    v2 epics 4-6 stub the ml branch everywhere until v2 epic 11 wires it
    up for real."""
    if human.mixing_beta is not None:
        return Resolved(
            human.mixing_beta,
            Provenance(source="human", source_note="operator override"),
        )
    ml_value: float | None = None  # no ml model for mixing_beta; stubbed until epic 11
    if ml_value is not None:
        return Resolved(ml_value, Provenance(source="ml"))
    llm_value: float | None = None  # no agent wiring yet; stubbed until epic 11
    if llm_value is not None:
        return Resolved(llm_value, Provenance(source="llm"))
    return Resolved(
        HEURISTIC_MIXING_BETA,
        Provenance(source="heuristic", source_note="package default"),
    )


class _ConvergenceSettings(BaseModel):
    mixing_beta: ResolvedField[float]

    @classmethod
    def from_human_input(cls, human: _ConvergenceHumanInput) -> _ConvergenceSettings:
        return cls(mixing_beta=ResolvedField.from_state(_resolve_mixing_beta(human)))


class TestWorkedExample:
    def test_human_override_resolves_and_serializes_end_to_end(self) -> None:
        settings = _ConvergenceSettings.from_human_input(
            _ConvergenceHumanInput(mixing_beta=0.25)
        )

        assert settings.mixing_beta.status == "resolved"
        assert settings.mixing_beta.value == 0.25
        assert settings.mixing_beta.source == "human"
        assert settings.model_dump_json()
        assert "mixing_beta" in _ConvergenceSettings.model_json_schema()["properties"]

    def test_falls_back_to_the_heuristic_default(self) -> None:
        settings = _ConvergenceSettings.from_human_input(_ConvergenceHumanInput())

        assert settings.mixing_beta.status == "resolved"
        assert settings.mixing_beta.value == 0.4
        assert settings.mixing_beta.source == "heuristic"

    def test_blocked_upstream_produces_a_blocked_settings_field(self) -> None:
        settings = _ConvergenceSettings(
            mixing_beta=ResolvedField.from_state(
                Blocked(by="pseudopotential selection failed")
            )
        )

        assert settings.mixing_beta.status == "blocked"
        assert settings.mixing_beta.value is None
        assert settings.mixing_beta.blocked_by == "pseudopotential selection failed"
        # still an ordinary pydantic model even when every field is blocked -- this is
        # the whole point of storing the projection, not the poison object, on the class
        assert settings.model_dump_json()
