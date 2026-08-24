from dataclasses import FrozenInstanceError, dataclass
from importlib import resources
from importlib.metadata import version
from pathlib import Path

import pytest

from goldilocks_core import Service
from goldilocks_core.contracts import (
    CalculationHints,
    CalculationIntent,
    CalculationTaskCapability,
    Capabilities,
    ModelCapability,
    PresetCapability,
    PseudopotentialSetCapability,
    StageCapability,
)
from goldilocks_core.contracts.registry import RECORD_TYPE_IDS
from goldilocks_core.runtime import GraphHandler, Preset, Runtime, Stage, TaskGraph


@pytest.fixture
def isolated_record_registry():
    registered = dict(RECORD_TYPE_IDS)
    yield
    RECORD_TYPE_IDS.clear()
    RECORD_TYPE_IDS.update(registered)


def test_capabilities_contract_is_an_immutable_serializable_domain_value() -> None:
    capabilities = Capabilities(
        core_version="1.2.3",
        tasks=(
            CalculationTaskCapability(
                id="future_task",
                revision="2",
                name="Future task",
                description="Produce a future scientific Record.",
                stages=(
                    StageCapability(
                        id="inspect",
                        name="Inspect",
                        description="Inspect the structure.",
                        input_record_ids=("structure",),
                        output_record_id="inspection",
                    ),
                ),
                presets=(
                    PresetCapability(
                        id="review",
                        name="review",
                        output_record_ids=("inspection",),
                    ),
                ),
                selectable_record_ids=("inspection",),
            ),
        ),
        target_codes=("quantum_espresso",),
        models=(
            ModelCapability(
                id="fixture-model",
                name="Fixture model",
                version="1",
                role="structure_classification",
                model_type="cgcnn",
                target="metallicity",
                feature_set="fixture_features",
                source="local",
                revision="abc123",
            ),
        ),
        pseudopotential_sets=(
            PseudopotentialSetCapability(
                id="fixture-pseudos",
                version="1",
                provider="fixture",
                upstream_name="Fixture Set",
                functional="PBEsol",
                accuracy="efficiency",
                relativistic_treatment="scalar",
                supported_elements=("Si",),
                licence="CC-BY-4.0",
                citation="Fixture et al. (2026)",
                default=True,
            ),
        ),
        default_intent=CalculationIntent(),
        default_hints=CalculationHints(),
    )

    assert capabilities.to_dict() == {
        "core_version": "1.2.3",
        "tasks": [
            {
                "id": "future_task",
                "revision": "2",
                "name": "Future task",
                "description": "Produce a future scientific Record.",
                "stages": [
                    {
                        "id": "inspect",
                        "name": "Inspect",
                        "description": "Inspect the structure.",
                        "input_record_ids": ["structure"],
                        "output_record_id": "inspection",
                    }
                ],
                "presets": [
                    {
                        "id": "review",
                        "name": "review",
                        "output_record_ids": ["inspection"],
                    }
                ],
                "selectable_record_ids": ["inspection"],
            }
        ],
        "target_codes": ["quantum_espresso"],
        "models": [
            {
                "id": "fixture-model",
                "name": "Fixture model",
                "version": "1",
                "role": "structure_classification",
                "model_type": "cgcnn",
                "target": "metallicity",
                "feature_set": "fixture_features",
                "source": "local",
                "revision": "abc123",
            }
        ],
        "pseudopotential_sets": [
            {
                "id": "fixture-pseudos",
                "version": "1",
                "provider": "fixture",
                "upstream_name": "Fixture Set",
                "functional": "PBEsol",
                "accuracy": "efficiency",
                "relativistic_treatment": "scalar",
                "supported_elements": ["Si"],
                "licence": "CC-BY-4.0",
                "citation": "Fixture et al. (2026)",
                "default": True,
            }
        ],
        "default_intent": {
            "code": "quantum_espresso",
            "task": "scf_single_point",
            "functional": "PBEsol",
            "pseudo_accuracy": "efficiency",
        },
        "default_hints": {
            "k_spacing": None,
            "k_grid": None,
            "smearing_type": None,
            "smearing_width_ry": None,
            "spin_polarized": None,
            "spin_orbit_coupling": None,
            "pseudo_accuracy": None,
            "pseudo_type": None,
            "relativistic_mode": None,
            "conv_thr": None,
            "mixing_beta": None,
            "electron_maxstep": None,
            "use_vdw": None,
            "vdw_method": None,
        },
    }
    with pytest.raises(FrozenInstanceError):
        capabilities.core_version = "changed"


def test_service_capabilities_describes_the_complete_core_catalog() -> None:
    with Service() as service:
        capabilities = service.capabilities()

    assert capabilities.core_version == version("goldilocks-core")
    assert capabilities.target_codes == ("quantum_espresso",)
    assert capabilities.default_intent == CalculationIntent()
    assert capabilities.default_hints == CalculationHints()

    assert len(capabilities.tasks) == 1
    task = capabilities.tasks[0]
    assert (task.id, task.revision) == ("scf_single_point", "1")
    assert tuple(stage.id for stage in task.stages) == (
        "load_structure",
        "analyze",
        "resolve_k_points",
        "advise",
        "select_pseudopotentials",
        "generate_inputs",
        "assemble_dft_input_data",
    )
    assert {preset.id: preset.output_record_ids for preset in task.presets} == {
        "recommend": ("analysis", "advice", "k_points", "selection"),
        "generate": (
            "analysis",
            "advice",
            "k_points",
            "selection",
            "generated_files",
            "dft_input_data",
        ),
    }
    assert task.selectable_record_ids == (
        "analysis",
        "advice",
        "k_points",
        "selection",
        "generated_files",
        "dft_input_data",
    )

    assert {
        (model.id, model.role, model.name, model.target)
        for model in capabilities.models
    } == {
        (
            "qrf-kpoints",
            "k_point_advisor",
            "kpoints-goldilocks-QRF",
            "k_distance",
        ),
        (
            "metallicity-cgcnn",
            "metallicity_classifier",
            "metallicity-goldilocks-CGCNN",
            "metallicity",
        ),
    }

    assert len(capabilities.pseudopotential_sets) == 15
    default_set = next(
        item for item in capabilities.pseudopotential_sets if item.default
    )
    set_metadata = default_set.to_dict()
    supported_elements = set_metadata.pop("supported_elements")
    assert set_metadata == {
        "id": "pseudodojo-pbesol-efficiency-sr",
        "version": "0.4",
        "provider": "pseudodojo",
        "upstream_name": "nc-sr-04_pbesol_standard",
        "functional": "PBEsol",
        "accuracy": "efficiency",
        "relativistic_treatment": "scalar",
        "licence": "CC-BY-4.0",
        "citation": "van Setten et al., Comput. Phys. Commun. 226, 39 (2018)",
        "default": True,
    }
    assert len(supported_elements) == 72
    assert {"H", "Si", "Pt"}.issubset(supported_elements)

    serialized = capabilities.to_dict()
    forbidden_fields = {
        "availability",
        "component",
        "control_dependency_graph",
        "enabled",
        "installed",
        "label",
        "layout",
        "location",
        "path",
        "ready",
        "root",
        "validation_message",
    }

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(*(keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(item) for item in value), set())
        return set()

    def strings(value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, dict):
            return sum((strings(item) for item in value.values()), ())
        if isinstance(value, list):
            return sum((strings(item) for item in value), ())
        return ()

    assert keys(serialized).isdisjoint(forbidden_fields)
    assert all(not value.startswith("/") for value in strings(serialized))


def test_custom_model_registry_rejects_path_like_source_labels(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "models.toml"
    packaged_registry = (
        resources.files("goldilocks_core.ml")
        .joinpath("registry.toml")
        .read_text(encoding="utf-8")
    )
    registry.write_text(
        packaged_registry.replace(
            'model_type = "random_forest"',
            'model_type = "random_forest"\nsource = "/home/operator/model"',
            1,
        ),
        encoding="utf-8",
    )

    with Runtime(registry_path=registry) as runtime:
        with pytest.raises(ValueError, match="model source must be one of"):
            Service(runtime).capabilities()


def test_duplicate_record_producers_are_rejected_at_task_declaration() -> None:
    @dataclass(frozen=True, slots=True)
    class DuplicateRecord:
        value: str

    with pytest.raises(
        ValueError,
        match="exactly one producer.*DuplicateRecord",
    ):
        TaskGraph(
            task="duplicate_producers",
            stages=(
                Stage(
                    output=DuplicateRecord,
                    inputs=(),
                    call=lambda *, ctx: DuplicateRecord("first"),
                    id="first",
                ),
                Stage(
                    output=DuplicateRecord,
                    inputs=(),
                    call=lambda *, ctx: DuplicateRecord("second"),
                    id="second",
                ),
            ),
            presets=(Preset("review", (DuplicateRecord,)),),
            selectable_outputs=(DuplicateRecord,),
            record_ids=((DuplicateRecord, "duplicate"),),
        )


def test_registered_future_task_appears_without_a_new_service_method(
    isolated_record_registry,
) -> None:
    @dataclass(frozen=True, slots=True)
    class FutureRecord:
        value: str

    handler = GraphHandler(
        spec=TaskGraph(
            task="future_task",
            revision="7",
            name="Future task",
            description="Exercise capability discovery for a future task.",
            stages=(
                Stage(
                    output=FutureRecord,
                    inputs=(),
                    call=lambda *, ctx: FutureRecord("future"),
                    id="produce_future",
                    name="Produce future Record",
                    description="Produce the future task Record.",
                ),
            ),
            presets=(Preset("review", (FutureRecord,)),),
            selectable_outputs=(FutureRecord,),
            record_ids=((FutureRecord, "future_record"),),
        ),
        build_context=lambda request, normalized, runtime: object(),
    )

    with Service(task_handlers=(handler,)) as service:
        tasks = {task.id: task for task in service.capabilities().tasks}

    assert set(tasks) == {"scf_single_point", "future_task"}
    assert tasks["future_task"].revision == "7"
    assert tasks["future_task"].presets[0].output_record_ids == ("future_record",)
    assert tasks["future_task"].selectable_record_ids == ("future_record",)


def test_capability_catalogs_use_deterministic_identity_order() -> None:
    future_handler = GraphHandler(
        spec=TaskGraph(
            task="zzz_future_task",
            revision="1",
            stages=(),
            presets=(),
        ),
        build_context=lambda request, runtime: object(),
    )
    with Service(task_handlers=(future_handler,)) as service:
        capabilities = service.capabilities()

    task_ids = tuple(task.id for task in capabilities.tasks)
    model_ids = tuple(model.id for model in capabilities.models)
    set_ids = tuple(item.id for item in capabilities.pseudopotential_sets)

    assert task_ids == ("scf_single_point", "zzz_future_task")
    assert capabilities.target_codes == tuple(sorted(capabilities.target_codes))
    assert model_ids == tuple(sorted(model_ids))
    assert set_ids == tuple(sorted(set_ids))
    assert all(
        item.supported_elements == tuple(sorted(item.supported_elements))
        for item in capabilities.pseudopotential_sets
    )
