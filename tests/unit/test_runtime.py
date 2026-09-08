from __future__ import annotations

import gc
import hashlib
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from threading import Barrier, Event
from types import SimpleNamespace
from typing import Any

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
from goldilocks_core.advice.parameters import ParameterAdvice
from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.assets.records import AssetFile, AssetSpec
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.calculation import CalculationIntent
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.ml.models import ModelSpec
from goldilocks_core.provenance import Provenance
from goldilocks_core.pseudo.installed import write_table_manifest
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.pseudo.registry import PseudoTable
from goldilocks_core.pseudo.source import (
    PseudoTableMismatch,
    select_compatible_table,
)
from goldilocks_core.runtime.dispatch import GraphHandler
from goldilocks_core.runtime.graph import Preset, Stage, TaskGraph
from goldilocks_core.runtime.registry import (
    RECORD_TYPE_IDS,
    register_record_types,
    resolve_output_types,
)
from goldilocks_core.selection import SelectionRecord
from goldilocks_core.serialization import to_portable


@pytest.fixture
def isolated_record_registry():
    registered = dict(RECORD_TYPE_IDS)
    yield
    RECORD_TYPE_IDS.clear()
    RECORD_TYPE_IDS.update(registered)


def make_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def make_metallicity_model() -> ModelSpec:
    return ModelSpec(
        name="operator-metallicity",
        version="1",
        model_type="cgcnn",
        target="metallicity",
        feature_set="test-features",
        source="local",
        location="metal.ckpt",
    )


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
        cutoffs={"ecutwfc_ry": 35, "ecutrho_ry": 140},
        source_identifier="synthetic/Si.UPF",
        pseudo_info={
            "licence": "CC-BY-4.0",
            "licence_text": "Synthetic fixture licence\n",
            "citation": "Synthetic fixture pseudopotential.",
        },
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
        f"pseudopotentials/{table_id}",
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


def make_query_request(outputs, **kw) -> ComputeRequest:
    draft = CalculationDraft(
        structure=InMemoryStructureSource(make_structure()),
        hints=CalculationHints(k_grid=(2, 2, 1), pseudo_type="NC"),
        pseudo_metadata=(make_metadata(),),
    )
    return ComputeRequest(
        draft=replace(draft, **kw),
        selection=RecordSelection(outputs),
    )


class TrackingBackend:
    def __init__(self, *, raise_on_call: bool = False) -> None:
        self.calls = 0
        self.resets = 0
        self.closes = 0
        self.raise_on_call = raise_on_call

    def __call__(self, structure: Structure) -> dict[str, Any]:
        self.calls += 1
        if self.raise_on_call:
            raise AssertionError("kmesh backend must not be called")
        return {
            "grid": [2, 2, 2],
            "shift": [0, 0, 0],
            "mesh_type": "monkhorst-pack",
            "provenance": Provenance(source="model", reason="test backend"),
        }

    def reset(self) -> None:
        self.resets += 1

    def close(self) -> None:
        self.closes += 1


def test_analyze_uses_heuristic_without_an_installed_metallicity_model(
    tmp_path,
) -> None:
    with Runtime(asset_store=AssetStore(tmp_path / "empty-assets")) as runtime:
        dispatcher = Dispatcher(runtime)
        result = dispatcher.compute(make_query_request((StructureAnalysisRecord,)))

    analysis = result.records[StructureAnalysisRecord]
    assert analysis["electronic_character"] == "unknown"
    assert analysis["electronic_character_source"] == "heuristic"
    assert analysis["electronic_character_confidence"] is None


def test_analyze_uses_the_installed_default_metallicity_model(
    tmp_path, monkeypatch
) -> None:
    from importlib.resources import files

    from goldilocks_core.ml.qrf import metallicity

    checkpoint = tmp_path / "checkpoint-source"
    checkpoint.write_bytes(b"checkpoint")
    atom_init = tmp_path / "atom-init-source"
    atom_init.write_text("{}", encoding="utf-8")
    licence = tmp_path / "licence-source"
    licence.write_text("Model terms\n", encoding="utf-8")
    spec = AssetSpec(
        id="models/metallicity-fixture",
        version="1",
        files=(
            AssetFile("checkpoint", "is_metal.ckpt", checkpoint.as_uri()),
            AssetFile("atom_init", "atom_init.json", atom_init.as_uri()),
            AssetFile("licence", "MODEL_CARD.md", licence.as_uri()),
        ),
    )
    store = AssetStore(tmp_path / "assets")
    store.install(spec)
    template = files("goldilocks_core.ml").joinpath("registry.toml").read_text()
    registry = tmp_path / "models.toml"
    registry.write_text(
        template.split("[defaults.kpoints.metallicity.asset]", 1)[0]
        + f"\n[defaults.kpoints.metallicity.asset]\nid = {spec.id!r}\n"
        + f"version = {spec.version!r}\n"
        + "".join(
            "\n[[defaults.kpoints.metallicity.asset.files]]\n"
            f"role = {asset.role!r}\npath = {asset.path!r}\nurl = {asset.url!r}\n"
            for asset in spec.files
        )
    )
    monkeypatch.setattr(metallicity, "load_metallicity_model", lambda path: object())
    monkeypatch.setattr(
        metallicity, "classify_metallicity", lambda *args, **kwargs: ("insulator", 0.94)
    )
    with Runtime(asset_store=store, registry_path=registry) as runtime:
        result = Dispatcher(runtime).compute(
            make_query_request((StructureAnalysisRecord,))
        )
    analysis = result.records[StructureAnalysisRecord]
    assert analysis["electronic_character"] == "insulator"
    assert analysis["electronic_character_source"] == "model"
    assert analysis["electronic_character_confidence"] == 0.94


@pytest.mark.parametrize(
    "configuration",
    (
        {
            "metallicity_checkpoint": "metal.ckpt",
            "metallicity_atom_init": "atom-init.json",
        },
        {"metallicity_model": make_metallicity_model()},
    ),
)
def test_runtime_rejects_incomplete_metallicity_configuration(configuration) -> None:
    with pytest.raises(ValueError):
        Runtime(**configuration)


def test_metallicity_model_loads_once_for_concurrent_first_calls(
    monkeypatch,
) -> None:
    from goldilocks_core.ml.qrf import metallicity

    model = object()
    load_started = Event()
    release_load = Event()
    inference = Barrier(2)
    loads = []

    def load(path):
        loads.append(model)
        load_started.set()
        assert release_load.wait(timeout=2)
        return model

    def classify(structure, actual_model, atom_init, **settings):
        del structure, atom_init, settings
        assert actual_model is model
        inference.wait(timeout=2)
        return "metal", 0.92

    monkeypatch.setattr(metallicity, "load_metallicity_model", load)
    monkeypatch.setattr(metallicity, "classify_metallicity", classify)

    with Runtime(
        metallicity_checkpoint="metal.ckpt",
        metallicity_atom_init="atom-init.json",
        metallicity_model=make_metallicity_model(),
    ) as runtime:
        structure = make_structure()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(runtime.metallicity, structure)
            try:
                assert load_started.wait(timeout=2)
                second = pool.submit(runtime.metallicity, structure)
                with pytest.raises(TimeoutError):
                    second.result(timeout=0.1)
            finally:
                release_load.set()
            first_result = first.result(timeout=2)
            second_result = second.result(timeout=2)

    assert first_result == second_result == ("metal", "model", 0.92)
    assert len(loads) == 1


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
    assert isinstance(result.records[record_type], dict)


def test_select_only_compute_does_not_invoke_kmesh() -> None:
    backend = TrackingBackend(raise_on_call=True)

    with Runtime(kmesh_service=backend) as runtime:
        dispatcher = Dispatcher(runtime)
        result = dispatcher.compute(make_query_request((SelectionRecord,)))

    assert isinstance(result.records[SelectionRecord], dict)
    assert backend.calls == 0


def test_analysis_query_does_not_resolve_pseudopotential_source(tmp_path) -> None:
    request = make_query_request(
        (StructureAnalysisRecord,),
        pseudo_metadata=None,
        pseudo_table="not-a-real-table",
    )

    with Runtime(asset_store=AssetStore(tmp_path / "empty")) as runtime:
        result = Dispatcher(runtime).compute(request)

    assert result.records[StructureAnalysisRecord]["reduced_formula"] == "Si"


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

    assert (
        result.records[SelectionRecord]["pseudopotentials"][0]["filename"] == "Si.UPF"
    )


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

    selected = result.records[SelectionRecord]["pseudopotentials"][0]
    assert selected["filename"] == "Si.upf"
    assert selected["provenance"].data_source == table.id


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


@pytest.mark.parametrize(
    "element,functional,accuracy,provider",
    (("Si", "PBE", "precision", "pseudodojo"), ("La", "PBEsol", "efficiency", "sssp")),
)
def test_automatic_table_selection_routes_by_element(
    element, functional, accuracy, provider
) -> None:
    tables = {
        name: table_fixture(
            f"{name}-{functional}-{accuracy}-sr",
            provider=name,
            functional=functional,
            accuracy=accuracy,
            elements=(element,),
        )
        for name in ("pseudodojo", "sssp")
    }
    requirements = {
        "functional": functional,
        "accuracy": accuracy,
        "pseudo_type": None,
        "relativistic": "scalar",
        "provenance": Provenance(source="test", reason="test"),
    }
    assert (
        select_compatible_table(
            tables, table_id=None, elements={element}, requirements=requirements
        )
        is tables[provider]
    )


def test_runtime_reuses_resets_and_closes_owned_models(monkeypatch) -> None:
    from goldilocks_core.ml.qrf import metallicity

    backend = TrackingBackend()
    model_loads = 0
    model_refs = []

    class StubMetallicityModel:
        pass

    def load(path):
        nonlocal model_loads
        model_loads += 1
        model = StubMetallicityModel()
        model_refs.append(weakref.ref(model))
        return model

    def classify(structure, model, atom_init, **settings):
        del structure, model, atom_init, settings
        return "metal", 0.9

    monkeypatch.setattr(metallicity, "load_metallicity_model", load)
    monkeypatch.setattr(metallicity, "classify_metallicity", classify)
    request = make_query_request(
        (StructureAnalysisRecord, KPointSelection),
        hints=CalculationHints(pseudo_type="NC"),
    )
    runtime = Runtime(
        kmesh_service=backend,
        metallicity_checkpoint="metal.ckpt",
        metallicity_atom_init="atom-init.json",
        metallicity_model=make_metallicity_model(),
    )
    dispatcher = Dispatcher(runtime)

    first = dispatcher.compute(request)
    second = dispatcher.compute(request)

    assert first.records[KPointSelection] == second.records[KPointSelection]
    for result in (first, second):
        analysis = result.records[StructureAnalysisRecord]
        assert analysis["electronic_character"] == "metal"
        assert analysis["electronic_character_source"] == "model"
        assert analysis["electronic_character_confidence"] == 0.9
    assert backend.calls == 2
    assert model_loads == 1
    assert model_refs[0]() is not None

    runtime.reset()
    gc.collect()
    assert backend.resets == 1
    assert model_refs[0]() is None

    dispatcher.compute(request)
    assert backend.calls == 3
    assert model_loads == 2
    assert model_refs[1]() is not None

    runtime.close()
    runtime.close()
    gc.collect()
    assert backend.closes == 1
    assert model_refs[1]() is None
    assert runtime.is_closed is True
    with pytest.raises(RuntimeError):
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


@pytest.mark.parametrize(
    "changes",
    (
        {"task": " "},
        {"revision": " "},
        {"stages": (Stage(StructureAnalysisRecord, (), lambda *, ctx: None, id=" "),)},
        {
            "stages": (
                Stage(StructureAnalysisRecord, (), lambda *, ctx: None, id="duplicate"),
                Stage(ParameterAdvice, (), lambda *, ctx: None, id="duplicate"),
            )
        },
        {"presets": (Preset(" ", (StructureAnalysisRecord,)),)},
        {
            "presets": (
                Preset("duplicate", (StructureAnalysisRecord,)),
                Preset("duplicate", (ParameterAdvice,)),
            )
        },
    ),
)
def test_task_registration_rejects_invalid_identifiers(changes) -> None:
    fields = {"task": "stub_task", "stages": (), "presets": ()} | changes
    handler = GraphHandler(
        spec=TaskGraph(**fields),
        build_context=lambda request, normalized, runtime: SimpleNamespace(),
    )
    with Runtime() as runtime, pytest.raises(ValueError):
        Dispatcher(runtime).register(handler)


@pytest.mark.parametrize("ids", (("duplicate", "duplicate"), (" ", "second")))
def test_task_graph_rejects_invalid_record_ids(ids) -> None:
    @dataclass
    class FirstRecord:
        value: str = "first"

    @dataclass
    class SecondRecord:
        value: str = "second"

    with pytest.raises(ValueError):
        TaskGraph(
            task="stub_task",
            stages=(
                Stage(FirstRecord, (), lambda *, ctx: FirstRecord()),
                Stage(SecondRecord, (), lambda *, ctx: SecondRecord()),
            ),
            presets=(Preset("both", (FirstRecord, SecondRecord)),),
            record_ids=((FirstRecord, ids[0]), (SecondRecord, ids[1])),
        )


@pytest.mark.parametrize("preset", (False, True))
def test_registered_task_requires_stable_ids_and_dispatches(
    isolated_record_registry,
    tmp_path,
    preset,
) -> None:
    @dataclass
    class StubRecord:
        value: str

    graph = TaskGraph(
        task="stub_task",
        stages=(
            Stage(
                StubRecord,
                (),
                lambda *, ctx: StubRecord(ctx.formula),
                id="produce_stub",
            ),
        ),
        presets=(Preset("only", (StubRecord,)),),
        selectable_outputs=(StubRecord,),
    )
    handler = GraphHandler(
        spec=graph,
        build_context=lambda request, normalized, runtime: SimpleNamespace(
            formula=normalized.inspection["structure"]["reduced_formula"]
        ),
    )
    structure_path = tmp_path / "Si.cif"
    make_structure().to(filename=structure_path)
    request = ComputeRequest(
        draft=CalculationDraft(
            PathStructureSource(structure_path),
            intent=CalculationIntent(task="stub_task"),
        ),
        selection=PresetSelection("only") if preset else RecordSelection((StubRecord,)),
    )
    with Runtime() as runtime:
        dispatcher = Dispatcher(runtime)
        with pytest.raises(ValueError):
            dispatcher.register(handler)
        dispatcher.register(
            replace(handler, spec=replace(graph, record_ids=((StubRecord, "stub"),)))
        )
        result = dispatcher.compute(request)

    if not preset:
        assert to_portable(request)["selection"] == {"records": ["stub"]}
    assert resolve_output_types(["stub"]) == (StubRecord,)
    assert result.draft.structure["source"]["origin"] == "path"
    assert to_portable(result)["records"] == {"stub": {"value": "Si"}}
