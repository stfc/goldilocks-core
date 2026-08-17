from __future__ import annotations

import gc
import hashlib
import json
import weakref
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationHints,
    Dispatcher,
    PresetRequest,
    QueryRequest,
    Runtime,
)
from goldilocks_core.assets import AssetFile, AssetSpec, AssetStore
from goldilocks_core.contracts import (
    CalculationIntent,
    KPointSelection,
    ParameterAdvice,
    Provenance,
    PseudoCutoffs,
    PseudoMetadata,
    Result,
    SelectionRecord,
    StructureAnalysisRecord,
)
from goldilocks_core.pseudo.installed import write_table_manifest
from goldilocks_core.pseudo.registry import PseudoTable
from goldilocks_core.pseudo.source import PseudoTableMismatch
from goldilocks_core.runtime import (
    GraphHandler,
    Preset,
    Stage,
    TaskGraph,
)


def make_structure() -> Structure:
    """Build a simple silicon structure."""
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def make_metadata() -> PseudoMetadata:
    """Build synthetic pseudopotential metadata with complete cutoffs."""
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
    """Install one normalized table for runtime source-resolution tests."""
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


def make_request(*, mode: str = "recommend") -> PresetRequest:
    """Build a request that avoids loading external model artifacts."""
    return PresetRequest(
        structure=make_structure(),
        hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
        pseudo_metadata=(make_metadata(),),
        mode=mode,
    )


def make_query_request(outputs, **kw) -> QueryRequest:
    """Build a query request with explicit outputs and the same defaults."""
    request = QueryRequest(
        structure=kw.pop("structure", make_structure()),
        outputs=outputs,
        intent=kw.pop("intent", CalculationIntent()),
        hints=kw.pop("hints", CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC")),
        pseudo_metadata=kw.pop("pseudo_metadata", (make_metadata(),)),
        pseudo_root=kw.pop("pseudo_root", None),
        pseudo_table=kw.pop("pseudo_table", None),
        kmesh_model=kw.pop("kmesh_model", None),
    )
    if kw:
        raise TypeError(f"unsupported test request fields: {sorted(kw)}")
    return request


class TrackingBackend:
    """Record lifecycle and inference calls for runtime tests."""

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


def test_recommend_returns_complete_result_without_generated_files() -> None:
    with Runtime() as runtime:
        dispatcher = Dispatcher(runtime)
        result = dispatcher.recommend(make_request())

    assert isinstance(result, Result)
    assert isinstance(result.analysis, StructureAnalysisRecord)
    assert isinstance(result.advice, ParameterAdvice)
    assert isinstance(result.k_points, KPointSelection)
    assert isinstance(result.selection, SelectionRecord)
    assert result.generated_files == ()


def test_analyze_uses_heuristic_without_configured_metallicity_model(
    monkeypatch,
) -> None:
    """Use the runtime heuristic service when no model artifacts are configured."""

    with Runtime() as runtime:
        dispatcher = Dispatcher(runtime)
        records = dispatcher.compute(make_query_request((StructureAnalysisRecord,)))

    analysis = records[StructureAnalysisRecord]
    assert analysis.electronic_character == "unknown"
    assert analysis.electronic_character_source == "heuristic"
    assert analysis.electronic_character_confidence is None


def test_analyze_uses_configured_metallicity_model(monkeypatch) -> None:
    """Lazy-load and invoke the model-backed classifier through the run context."""
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
        records = dispatcher.compute(make_query_request((StructureAnalysisRecord,)))

    analysis = records[StructureAnalysisRecord]
    assert analysis.electronic_character == "metal"
    assert analysis.electronic_character_source == "model"
    assert analysis.electronic_character_confidence == 0.92
    assert len(calls) == 1
    assert calls[0][1:3] == (model, "atom-init.json")


def test_generate_returns_generated_files() -> None:
    with Runtime() as runtime:
        dispatcher = Dispatcher(runtime)
        result = dispatcher.generate(make_request(mode="generate"))

    assert result.generated_files
    assert result.generated_files[0].path == "inputs/qe.in"


def test_generate_with_output_dir_writes_bundle(tmp_path) -> None:
    output_dir = tmp_path / "bundle"

    with Runtime() as runtime:
        dispatcher = Dispatcher(runtime)
        result = dispatcher.generate(
            make_request(mode="generate"), output_dir=str(output_dir)
        )

    assert result.bundle is not None
    assert result.bundle.path == str(output_dir)
    assert (output_dir / "inputs" / "qe.in").is_file()
    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert manifest == result.bundle.manifest


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
    """Query every public SCF intermediate as an isolated output."""
    with Runtime() as runtime:
        dispatcher = Dispatcher(runtime)
        records = dispatcher.compute(make_query_request((record_type,)))

    assert tuple(records) == (record_type,)
    assert isinstance(records[record_type], record_type)


def test_select_only_compute_does_not_invoke_kmesh(monkeypatch) -> None:
    backend = TrackingBackend(raise_on_call=True)

    with Runtime(kmesh_service=backend) as runtime:
        dispatcher = Dispatcher(runtime)
        records = dispatcher.compute(make_query_request((SelectionRecord,)))

    assert isinstance(records[SelectionRecord], SelectionRecord)
    assert backend.calls == 0


def test_analysis_query_does_not_resolve_pseudopotential_source(tmp_path) -> None:
    """An analysis-only query never reads the pseudo registry or asset store."""
    request = make_query_request(
        (StructureAnalysisRecord,),
        pseudo_metadata=None,
        pseudo_table="not-a-real-table",
    )

    with Runtime(asset_store=AssetStore(tmp_path / "empty")) as runtime:
        records = Dispatcher(runtime).compute(request)

    assert records[StructureAnalysisRecord].reduced_formula == "Si"


def test_explicit_metadata_selection_does_not_read_registry(
    monkeypatch,
) -> None:
    """The explicit source adapter keeps Select independent of registries."""
    from goldilocks_core.pseudo import source

    monkeypatch.setattr(
        source,
        "load_tables",
        lambda path: pytest.fail("explicit metadata must not read the registry"),
    )

    with Runtime() as runtime:
        records = Dispatcher(runtime).compute(make_query_request((SelectionRecord,)))

    assert records[SelectionRecord].pseudopotentials[0].filename == "Si.UPF"


def test_runtime_resolves_one_explicit_installed_table(
    tmp_path,
    monkeypatch,
) -> None:
    """Resolve the requested table ID and its normalized installed manifest."""
    from goldilocks_core.pseudo import source

    store, table = installed_pseudo_table(tmp_path)
    monkeypatch.setattr(source, "load_tables", lambda path: {table.id: table})
    request = PresetRequest(
        structure=make_structure(),
        hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
        pseudo_table=table.id,
    )

    with Runtime(asset_store=store) as runtime:
        result = Dispatcher(runtime).recommend(request)

    selected = result.selection.pseudopotentials[0]
    assert selected.filename == "Si.upf"
    assert selected.provenance.data_source == table.id


def test_explicit_table_must_satisfy_scientific_requirements(
    tmp_path,
    monkeypatch,
) -> None:
    """Reject an exact installed table rather than weakening the request."""
    from goldilocks_core.pseudo import source

    store, table = installed_pseudo_table(tmp_path)
    monkeypatch.setattr(source, "load_tables", lambda path: {table.id: table})
    request = PresetRequest(
        structure=make_structure(),
        intent=CalculationIntent(functional="PBE"),
        hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
        pseudo_table=table.id,
    )

    with (
        Runtime(asset_store=store) as runtime,
        pytest.raises(PseudoTableMismatch, match="functional is PBEsol"),
    ):
        Dispatcher(runtime).recommend(request)


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
    """Exercise model lifecycle across jobs through one runtime."""
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
    request = PresetRequest(
        structure=make_structure(),
        hints=CalculationHints(pseudo_type="NC"),
        pseudo_metadata=(make_metadata(),),
    )
    runtime = Runtime(
        kmesh_service=backend,
        metallicity_checkpoint="metal.ckpt",
        metallicity_atom_init="atom-init.json",
    )
    dispatcher = Dispatcher(runtime)

    first = dispatcher.recommend(request)
    second = dispatcher.recommend(request)

    assert first.k_points == second.k_points
    assert first.analysis.electronic_character == "metal"
    assert second.analysis.electronic_character == "metal"
    assert backend.calls == 2
    assert model_loads == 1
    assert classifications == 2
    assert model_refs[0]() is not None

    runtime.reset()
    gc.collect()
    assert backend.resets == 1
    assert model_refs[0]() is None

    dispatcher.recommend(request)
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
        dispatcher.recommend(request)


def test_runtime_dispatches_a_registered_task_via_compute(monkeypatch) -> None:
    """A registered task dispatches by intent.task through compute."""
    monkeypatch.setattr(Runtime, "_build_backend", lambda self: TrackingBackend())

    @dataclass
    class StubRecord:
        value: str = "stub"

    def make_stub(*, ctx) -> StubRecord:
        return StubRecord("ran")

    handler = GraphHandler(
        spec=TaskGraph(
            task="stub_task",
            stages=(Stage(StubRecord, (), make_stub),),
            presets=(Preset("only", (StubRecord,)),),
        ),
        build_context=lambda request, runtime: SimpleNamespace(),
        assemble_result=lambda request, records: records,
    )

    with Runtime() as runtime:
        dispatcher = Dispatcher(runtime)
        dispatcher.register(handler)
        records = dispatcher.compute(
            QueryRequest(
                structure=make_structure(),
                outputs=(StubRecord,),
                intent=CalculationIntent(task="stub_task"),
            ),
        )

    assert isinstance(records[StubRecord], StubRecord)
    assert records[StubRecord].value == "ran"


def test_runtime_recommend_dispatches_a_registered_task_preset(monkeypatch) -> None:
    """recommend runs the task's recommend preset and the task's own assembler."""
    monkeypatch.setattr(Runtime, "_build_backend", lambda self: TrackingBackend())

    @dataclass
    class StubRecord:
        value: str = "stub"

    def make_stub(*, ctx) -> StubRecord:
        return StubRecord("ran")

    assembled = object()
    handler = GraphHandler(
        spec=TaskGraph(
            task="stub_task",
            stages=(Stage(StubRecord, (), make_stub),),
            presets=(Preset("recommend", (StubRecord,)),),
        ),
        build_context=lambda request, runtime: SimpleNamespace(),
        assemble_result=lambda request, records: assembled,
    )

    with Runtime() as runtime:
        dispatcher = Dispatcher(runtime)
        dispatcher.register(handler)
        result = dispatcher.recommend(
            PresetRequest(
                structure=make_structure(),
                intent=CalculationIntent(task="stub_task"),
            )
        )

    assert result is assembled
