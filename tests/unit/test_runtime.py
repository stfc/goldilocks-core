from __future__ import annotations

import gc
import hashlib
import weakref
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    ComputeRequest,
    Dispatcher,
    InMemoryStructureSource,
    PathStructureSource,
    PresetSelection,
    RecordSelection,
    Runtime,
)
from goldilocks_core.assets import AssetFile, AssetSpec, AssetStore
from goldilocks_core.contracts import (
    CalculationIntent,
    GeneratedFiles,
    KPointSelection,
    ParameterAdvice,
    Provenance,
    PseudoCutoffs,
    PseudoMetadata,
    PseudopotentialRequirements,
    SelectionRecord,
    StructureAnalysisRecord,
    resolve_output_types,
)
from goldilocks_core.contracts.registry import (
    RECORD_TYPE_IDS,
    register_record_types,
)
from goldilocks_core.pseudo.installed import write_table_manifest
from goldilocks_core.pseudo.registry import PseudoTable
from goldilocks_core.pseudo.source import (
    PseudoTableMismatch,
    select_compatible_table,
)
from goldilocks_core.runtime import (
    GraphHandler,
    Preset,
    Stage,
    TaskGraph,
)


@pytest.fixture
def isolated_record_registry():
    registered = dict(RECORD_TYPE_IDS)
    yield
    RECORD_TYPE_IDS.clear()
    RECORD_TYPE_IDS.update(registered)


def make_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def make_metadata() -> PseudoMetadata:
    return PseudoMetadata(
        filepath="/pseudo/Si.UPF",
        filename="Si.UPF",
        header_format="attr",
        provider="sssp",
        accuracy="efficiency",
        element="Si",
        pseudo_type="NC",
        functional="PBEsol",
        relativistic="scalar",
        cutoffs=PseudoCutoffs(
            ecutwfc_ry=35,
            ecutrho_ry=140,
        ),
        source_identifier="synthetic/Si.UPF",
    )


def installed_pseudo_table(tmp_path) -> tuple[AssetStore, PseudoTable]:
    source = tmp_path / "source.bin"
    source.write_bytes(b"source")
    spec = AssetSpec(
        "pseudopotentials/sssp-fixture",
        "1",
        (AssetFile("source", "source.bin", source.as_uri()),),
    )
    table = PseudoTable(
        id=spec.id,
        provider="sssp",
        upstream_table="fixture",
        version=spec.version,
        functional="PBEsol",
        relativistic="scalar",
        accuracy="efficiency",
        licence="fixture licence",
        citation="fixture citation",
        elements=("Si",),
        asset=spec,
    )

    def prepare(sources, destination):
        del sources
        pseudos = destination / "pseudos"
        pseudos.mkdir()
        upf = pseudos / "Si.upf"
        payload = (
            '<UPF><PP_HEADER element="Si" pseudo_type="NC" '
            'functional="PBEsol" relativistic="scalar" '
            'z_valence="4.0"/></UPF>'
        )
        upf.write_text(payload)
        write_table_manifest(
            destination,
            table,
            [
                {
                    "element": "Si",
                    "path": "pseudos/Si.upf",
                    "md5": hashlib.md5(payload.encode()).hexdigest(),
                    "header_format": "attr",
                    "upf_relativistic": "scalar",
                    "pseudo_type": "NC",
                    "z_valence": 4.0,
                    "ecutwfc_ry": 35.0,
                    "ecutrho_ry": 140.0,
                    "source_identifier": "fixture/Si.upf",
                    "frozen_4f_core": False,
                }
            ],
        )

    store = AssetStore(tmp_path / "store")
    store.install(spec, prepare)
    return store, table


def table_fixture(
    table_id: str,
    *,
    provider: str,
    functional: str,
    accuracy: str,
    elements: tuple[str, ...],
) -> PseudoTable:
    spec = AssetSpec(
        table_id,
        "1",
        (
            AssetFile(
                "pseudopotentials",
                "source/table.tar.gz",
                f"https://example.invalid/{table_id}.tar.gz",
            ),
        ),
    )
    return PseudoTable(
        id=table_id,
        provider=provider,
        upstream_table=f"{table_id}-upstream",
        version=spec.version,
        functional=functional,
        relativistic="scalar",
        accuracy=accuracy,
        licence="fixture licence",
        citation="fixture citation",
        elements=elements,
        asset=spec,
    )


def make_request(*, preset: str = "recommend") -> ComputeRequest:
    return ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(make_structure()),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        ),
        selection=PresetSelection(preset),
    )


def make_query_request(outputs, **kw) -> ComputeRequest:
    request = ComputeRequest(
        draft=CalculationDraft(
            structure=kw.pop("structure", InMemoryStructureSource(make_structure())),
            intent=kw.pop("intent", CalculationIntent()),
            hints=kw.pop("hints", CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC")),
            pseudo_metadata=kw.pop("pseudo_metadata", (make_metadata(),)),
            pseudo_root=kw.pop("pseudo_root", None),
            pseudo_table=kw.pop("pseudo_table", None),
            kmesh_model=kw.pop("kmesh_model", None),
        ),
        selection=RecordSelection(outputs),
    )
    if kw:
        raise TypeError(f"unsupported test request fields: {sorted(kw)}")
    return request


class TrackingBackend:
    def __init__(self, *, raise_on_call: bool = False) -> None:
        self.calls = 0
        self.resets = 0
        self.closes = 0
        self.raise_on_call = raise_on_call

    def __call__(self, structure: Structure) -> KPointSelection:
        self.calls += 1
        if self.raise_on_call:
            raise AssertionError("kmesh backend must not be called")
        return KPointSelection(
            grid=(2, 2, 2),
            shift=(0, 0, 0),
            mesh_type="monkhorst-pack",
            provenance=Provenance(source="model", reason="test backend"),
        )

    def reset(self) -> None:
        self.resets += 1

    def close(self) -> None:
        self.closes += 1


def test_recommendation_preset_returns_complete_selected_records() -> None:
    with Runtime() as runtime:
        result = Dispatcher(runtime).compute(make_request())

    assert isinstance(result.records[StructureAnalysisRecord], StructureAnalysisRecord)
    assert isinstance(result.records[ParameterAdvice], ParameterAdvice)
    assert isinstance(result.records[KPointSelection], KPointSelection)
    assert isinstance(result.records[SelectionRecord], SelectionRecord)
    assert GeneratedFiles not in result.records


def test_analyze_uses_heuristic_without_configured_metallicity_model(
    monkeypatch,
) -> None:

    with Runtime() as runtime:
        dispatcher = Dispatcher(runtime)
        result = dispatcher.compute(make_query_request((StructureAnalysisRecord,)))

    analysis = result.records[StructureAnalysisRecord]
    assert analysis.electronic_character == "unknown"
    assert analysis.electronic_character_source == "heuristic"
    assert analysis.electronic_character_confidence is None


def test_analyze_uses_configured_metallicity_model(monkeypatch) -> None:
    from goldilocks_core.ml.qrf import metallicity

    model = object()
    calls = []
    monkeypatch.setattr(metallicity, "load_metallicity_model", lambda path: model)

    def classify(structure, actual_model, atom_init, **settings):
        calls.append((structure, actual_model, atom_init, settings))
        return "metal", 0.92

    monkeypatch.setattr(metallicity, "classify_metallicity", classify)

    with Runtime(
        metallicity_checkpoint="metal.ckpt",
        metallicity_atom_init="atom-init.json",
    ) as runtime:
        dispatcher = Dispatcher(runtime)
        result = dispatcher.compute(make_query_request((StructureAnalysisRecord,)))

    analysis = result.records[StructureAnalysisRecord]
    assert analysis.electronic_character == "metal"
    assert analysis.electronic_character_source == "model"
    assert analysis.electronic_character_confidence == 0.92
    assert len(calls) == 1
    assert calls[0][1:3] == (model, "atom-init.json")


def test_generation_preset_returns_generated_files() -> None:
    with Runtime() as runtime:
        result = Dispatcher(runtime).compute(make_request(preset="generate"))

    assert result.records[GeneratedFiles]
    assert result.records[GeneratedFiles][0].path == "inputs/qe.in"


@pytest.mark.parametrize(
    "record_type",
    (
        StructureAnalysisRecord,
        KPointSelection,
        ParameterAdvice,
        SelectionRecord,
    ),
)
def test_compute_returns_each_requested_record_type(record_type: type) -> None:
    with Runtime() as runtime:
        dispatcher = Dispatcher(runtime)
        result = dispatcher.compute(make_query_request((record_type,)))

    assert tuple(result.records) == (record_type,)
    assert isinstance(result.records[record_type], record_type)


def test_select_only_compute_does_not_invoke_kmesh(monkeypatch) -> None:
    backend = TrackingBackend(raise_on_call=True)

    with Runtime(kmesh_service=backend) as runtime:
        dispatcher = Dispatcher(runtime)
        result = dispatcher.compute(make_query_request((SelectionRecord,)))

    assert isinstance(result.records[SelectionRecord], SelectionRecord)
    assert backend.calls == 0


def test_analysis_query_does_not_resolve_pseudopotential_source(tmp_path) -> None:
    request = make_query_request(
        (StructureAnalysisRecord,),
        pseudo_metadata=None,
        pseudo_table="not-a-real-table",
    )

    with Runtime(asset_store=AssetStore(tmp_path / "empty")) as runtime:
        result = Dispatcher(runtime).compute(request)

    assert result.records[StructureAnalysisRecord].reduced_formula == "Si"


def test_explicit_metadata_selection_does_not_read_registry(
    monkeypatch,
) -> None:
    from goldilocks_core.pseudo import source

    monkeypatch.setattr(
        source,
        "load_tables",
        lambda path: pytest.fail("explicit metadata must not read the registry"),
    )

    with Runtime() as runtime:
        result = Dispatcher(runtime).compute(make_query_request((SelectionRecord,)))

    assert result.records[SelectionRecord].pseudopotentials[0].filename == "Si.UPF"


def test_runtime_resolves_one_explicit_installed_table(
    tmp_path,
    monkeypatch,
) -> None:
    from goldilocks_core.pseudo import source

    store, table = installed_pseudo_table(tmp_path)
    monkeypatch.setattr(source, "load_tables", lambda path: {table.id: table})
    request = ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(make_structure()),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_table=table.id,
        ),
        selection=PresetSelection("recommend"),
    )

    with Runtime(asset_store=store) as runtime:
        result = Dispatcher(runtime).compute(request)

    selected = result.records[SelectionRecord].pseudopotentials[0]
    assert selected.filename == "Si.upf"
    assert selected.provenance.data_source == table.id


def test_explicit_table_must_satisfy_scientific_requirements(
    tmp_path,
    monkeypatch,
) -> None:
    from goldilocks_core.pseudo import source

    store, table = installed_pseudo_table(tmp_path)
    monkeypatch.setattr(source, "load_tables", lambda path: {table.id: table})
    request = ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(make_structure()),
            intent=CalculationIntent(functional="PBE"),
            hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
            pseudo_table=table.id,
        ),
        selection=PresetSelection("recommend"),
    )

    with (
        Runtime(asset_store=store) as runtime,
        pytest.raises(PseudoTableMismatch, match="functional is PBEsol"),
    ):
        Dispatcher(runtime).compute(request)


def test_automatic_table_selection_prefers_pseudodojo_for_ordinary_elements() -> None:
    dojo = table_fixture(
        "pseudodojo-pbe-precision-sr",
        provider="pseudodojo",
        functional="PBE",
        accuracy="precision",
        elements=("Si",),
    )
    sssp = table_fixture(
        "sssp-pbe-precision-sr",
        provider="sssp",
        functional="PBE",
        accuracy="precision",
        elements=("Si",),
    )
    requirements = PseudopotentialRequirements(
        functional="PBE",
        accuracy="precision",
        pseudo_type=None,
        relativistic="scalar",
        provenance=Provenance(source="test", reason="test"),
    )

    selected = select_compatible_table(
        {dojo.id: dojo, sssp.id: sssp},
        table_id=None,
        elements={"Si"},
        requirements=requirements,
    )

    assert selected is dojo


def test_automatic_table_selection_routes_f_block_elements_to_sssp() -> None:
    dojo = table_fixture(
        "pseudodojo-pbesol-efficiency-sr",
        provider="pseudodojo",
        functional="PBEsol",
        accuracy="efficiency",
        elements=("La",),
    )
    sssp = table_fixture(
        "sssp-pbesol-efficiency-sr",
        provider="sssp",
        functional="PBEsol",
        accuracy="efficiency",
        elements=("La",),
    )
    requirements = PseudopotentialRequirements(
        functional="PBEsol",
        accuracy="efficiency",
        pseudo_type=None,
        relativistic="scalar",
        provenance=Provenance(source="test", reason="test"),
    )

    selected = select_compatible_table(
        {dojo.id: dojo, sssp.id: sssp},
        table_id=None,
        elements={"La"},
        requirements=requirements,
    )

    assert selected is sssp


def test_reset_close_and_context_manager_delegate_to_backend(monkeypatch) -> None:
    backend = TrackingBackend()

    with Runtime(kmesh_service=backend) as runtime:
        runtime.reset()
        assert runtime.is_closed is False

    assert runtime.is_closed is True
    assert backend.resets == 1
    assert backend.closes == 1

    runtime.close()
    assert backend.closes == 1


def test_runtime_reuses_resets_and_closes_owned_models(monkeypatch) -> None:
    from goldilocks_core.ml.qrf import metallicity

    backend = TrackingBackend()
    model_loads = 0
    model_refs = []
    classifications = 0

    class StubMetallicityModel:
        pass

    def load(path):
        nonlocal model_loads
        model_loads += 1
        model = StubMetallicityModel()
        model_refs.append(weakref.ref(model))
        return model

    def classify(structure, model, atom_init, **settings):
        nonlocal classifications
        classifications += 1
        return "metal", 0.9

    monkeypatch.setattr(metallicity, "load_metallicity_model", load)
    monkeypatch.setattr(metallicity, "classify_metallicity", classify)
    request = ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(make_structure()),
            hints=CalculationHints(pseudo_type="NC"),
            pseudo_metadata=(make_metadata(),),
        ),
        selection=PresetSelection("recommend"),
    )
    runtime = Runtime(
        kmesh_service=backend,
        metallicity_checkpoint="metal.ckpt",
        metallicity_atom_init="atom-init.json",
    )
    dispatcher = Dispatcher(runtime)

    first = dispatcher.compute(request)
    second = dispatcher.compute(request)

    assert first.records[KPointSelection] == second.records[KPointSelection]
    assert first.records[StructureAnalysisRecord].electronic_character == "metal"
    assert second.records[StructureAnalysisRecord].electronic_character == "metal"
    assert backend.calls == 2
    assert model_loads == 1
    assert classifications == 2
    assert model_refs[0]() is not None

    runtime.reset()
    gc.collect()
    assert backend.resets == 1
    assert model_refs[0]() is None

    dispatcher.compute(request)
    assert backend.calls == 3
    assert model_loads == 2
    assert classifications == 3
    assert model_refs[1]() is not None

    runtime.close()
    gc.collect()
    assert backend.closes == 1
    assert model_refs[1]() is None
    assert runtime.is_closed is True
    with pytest.raises(RuntimeError, match="Runtime is closed"):
        dispatcher.compute(request)


def test_record_registration_is_atomic_when_an_id_conflicts() -> None:
    @dataclass
    class FirstRecord:
        value: str = "first"

    @dataclass
    class ConflictingRecord:
        value: str = "conflict"

    registered = dict(RECORD_TYPE_IDS)
    with pytest.raises(ValueError, match="'analysis' is already registered"):
        register_record_types(
            (
                (FirstRecord, "atomic_fixture"),
                (ConflictingRecord, "analysis"),
            )
        )

    assert RECORD_TYPE_IDS == registered


def test_task_registration_rejects_empty_stage_ids(monkeypatch) -> None:
    monkeypatch.setattr(Runtime, "_build_backend", lambda self: TrackingBackend())
    handler = GraphHandler(
        spec=TaskGraph(
            task="stub_task",
            stages=(
                Stage(
                    StructureAnalysisRecord,
                    (),
                    lambda *, ctx: None,
                    id=" ",
                ),
            ),
            presets=(),
        ),
        build_context=lambda request, runtime: SimpleNamespace(),
    )

    with (
        Runtime() as runtime,
        pytest.raises(
            ValueError,
            match="stage ids must be non-empty strings",
        ),
    ):
        Dispatcher(runtime).register(handler)


def test_task_registration_rejects_duplicate_stage_ids(monkeypatch) -> None:
    monkeypatch.setattr(Runtime, "_build_backend", lambda self: TrackingBackend())
    handler = GraphHandler(
        spec=TaskGraph(
            task="stub_task",
            stages=(
                Stage(
                    StructureAnalysisRecord,
                    (),
                    lambda *, ctx: None,
                    id="duplicate",
                ),
                Stage(
                    ParameterAdvice,
                    (),
                    lambda *, ctx: None,
                    id="duplicate",
                ),
            ),
            presets=(),
        ),
        build_context=lambda request, runtime: SimpleNamespace(),
    )

    with (
        Runtime() as runtime,
        pytest.raises(
            ValueError,
            match="stage ids must be unique",
        ),
    ):
        Dispatcher(runtime).register(handler)


def test_task_registration_rejects_empty_preset_names(monkeypatch) -> None:
    monkeypatch.setattr(Runtime, "_build_backend", lambda self: TrackingBackend())
    handler = GraphHandler(
        spec=TaskGraph(
            task="stub_task",
            stages=(),
            presets=(Preset(" ", (StructureAnalysisRecord,)),),
        ),
        build_context=lambda request, runtime: SimpleNamespace(),
    )

    with (
        Runtime() as runtime,
        pytest.raises(
            ValueError,
            match="preset names must be non-empty strings",
        ),
    ):
        Dispatcher(runtime).register(handler)


def test_task_registration_rejects_duplicate_preset_names(monkeypatch) -> None:
    monkeypatch.setattr(Runtime, "_build_backend", lambda self: TrackingBackend())
    handler = GraphHandler(
        spec=TaskGraph(
            task="stub_task",
            stages=(),
            presets=(
                Preset("duplicate", (StructureAnalysisRecord,)),
                Preset("duplicate", (ParameterAdvice,)),
            ),
        ),
        build_context=lambda request, runtime: SimpleNamespace(),
    )

    with (
        Runtime() as runtime,
        pytest.raises(
            ValueError,
            match="preset names must be unique",
        ),
    ):
        Dispatcher(runtime).register(handler)


@pytest.mark.parametrize("field", ("task", "revision"))
def test_task_registration_rejects_empty_task_identity(
    monkeypatch,
    field: str,
) -> None:
    monkeypatch.setattr(Runtime, "_build_backend", lambda self: TrackingBackend())
    identity = {"task": "stub_task", "revision": "1"}
    identity[field] = " "
    handler = GraphHandler(
        spec=TaskGraph(
            **identity,
            stages=(),
            presets=(),
        ),
        build_context=lambda request, runtime: SimpleNamespace(),
    )

    with (
        Runtime() as runtime,
        pytest.raises(
            ValueError,
            match=f"{field} must be a non-empty string",
        ),
    ):
        Dispatcher(runtime).register(handler)


def test_task_registration_rejects_duplicate_record_ids() -> None:
    @dataclass
    class FirstRecord:
        value: str = "first"

    @dataclass
    class SecondRecord:
        value: str = "second"

    with pytest.raises(ValueError, match="record ids must be unique"):
        TaskGraph(
            task="stub_task",
            stages=(
                Stage(FirstRecord, (), lambda *, ctx: FirstRecord()),
                Stage(SecondRecord, (), lambda *, ctx: SecondRecord()),
            ),
            presets=(Preset("both", (FirstRecord, SecondRecord)),),
            record_ids=((FirstRecord, "duplicate"), (SecondRecord, "duplicate")),
        )


def test_task_registration_rejects_empty_record_ids() -> None:
    @dataclass
    class StubRecord:
        value: str = "stub"

    with pytest.raises(ValueError, match="record ids must be non-empty strings"):
        TaskGraph(
            task="stub_task",
            stages=(Stage(StubRecord, (), lambda *, ctx: StubRecord()),),
            presets=(Preset("only", (StubRecord,)),),
            record_ids=((StubRecord, " "),),
        )


def test_task_registration_requires_stable_ids_for_custom_records(
    monkeypatch,
) -> None:
    monkeypatch.setattr(Runtime, "_build_backend", lambda self: TrackingBackend())

    @dataclass
    class StubRecord:
        value: str = "stub"

    handler = GraphHandler(
        spec=TaskGraph(
            task="stub_task",
            stages=(
                Stage(
                    StubRecord,
                    (),
                    lambda *, ctx: StubRecord(),
                    id="produce_stub",
                ),
            ),
            presets=(Preset("only", (StubRecord,)),),
            selectable_outputs=(StubRecord,),
        ),
        build_context=lambda request, normalized, runtime: SimpleNamespace(),
    )

    with (
        Runtime() as runtime,
        pytest.raises(
            ValueError,
            match="stable record id.*StubRecord",
        ),
    ):
        Dispatcher(runtime).register(handler)


def test_runtime_dispatches_a_registered_task_via_compute(
    monkeypatch,
    isolated_record_registry,
    tmp_path,
) -> None:
    monkeypatch.setattr(Runtime, "_build_backend", lambda self: TrackingBackend())

    @dataclass
    class StubRecord:
        value: str = "stub"

    def make_stub(*, ctx) -> StubRecord:
        return StubRecord("ran")

    handler = GraphHandler(
        spec=TaskGraph(
            task="stub_task",
            stages=(Stage(StubRecord, (), make_stub, id="produce_stub"),),
            presets=(Preset("only", (StubRecord,)),),
            selectable_outputs=(StubRecord,),
            record_ids=((StubRecord, "stub"),),
        ),
        build_context=lambda request, normalized, runtime: SimpleNamespace(),
    )

    structure_path = tmp_path / "Si.cif"
    make_structure().to(filename=structure_path)
    request = ComputeRequest(
        draft=CalculationDraft(
            PathStructureSource(structure_path),
            intent=CalculationIntent(task="stub_task"),
        ),
        selection=RecordSelection((StubRecord,)),
    )
    with Runtime() as runtime:
        dispatcher = Dispatcher(runtime)
        dispatcher.register(handler)
        document = request.to_dict()
        result = dispatcher.compute(request)

    assert document["selection"] == {"records": ["stub"]}
    assert resolve_output_types(["stub"]) == (StubRecord,)
    assert result.draft.structure.source.origin == "path"
    assert isinstance(result.records[StubRecord], StubRecord)
    assert result.records[StubRecord].value == "ran"
    assert result.to_dict()["records"] == {"stub": {"value": "ran"}}


def test_runtime_recommend_dispatches_a_registered_task_preset(
    monkeypatch,
    isolated_record_registry,
) -> None:
    monkeypatch.setattr(Runtime, "_build_backend", lambda self: TrackingBackend())

    @dataclass
    class StubRecord:
        value: str = "stub"

    def make_stub(*, ctx) -> StubRecord:
        return StubRecord("ran")

    handler = GraphHandler(
        spec=TaskGraph(
            task="stub_task",
            stages=(Stage(StubRecord, (), make_stub, id="produce_stub"),),
            presets=(Preset("recommend", (StubRecord,)),),
            record_ids=((StubRecord, "stub_preset"),),
        ),
        build_context=lambda request, normalized, runtime: SimpleNamespace(),
    )

    with Runtime() as runtime:
        dispatcher = Dispatcher(runtime)
        dispatcher.register(handler)
        result = dispatcher.compute(
            ComputeRequest(
                draft=CalculationDraft(
                    InMemoryStructureSource(make_structure()),
                    intent=CalculationIntent(task="stub_task"),
                ),
                selection=PresetSelection("recommend"),
            )
        )

    assert result.records[StubRecord] == StubRecord("ran")
