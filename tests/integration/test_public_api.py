import hashlib
import subprocess
import sys
from pathlib import Path

from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    ArchiveOutput,
    CalculationDraft,
    CalculationHints,
    ComputationResult,
    ComputeRequest,
    DftInputData,
    DirectoryOutput,
    GeneratedFile,
    GeneratedFiles,
    InlineStructureSource,
    InMemoryStructureSource,
    OutputTarget,
    PathStructureSource,
    PresetSelection,
    Records,
    RecordSelection,
    Service,
    StructureSource,
    compute,
)
from goldilocks_core.advice.parameters import ParameterAdvice
from goldilocks_core.analysis import StructureAnalysisRecord
from goldilocks_core.kmesh.resolve import KPointSelection
from goldilocks_core.pseudo.metadata import PseudoMetadata
from goldilocks_core.selection import SelectionRecord
from goldilocks_core.serialization import to_portable


def _make_si_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def _make_si_metadata(root: Path = Path("/pseudo")) -> PseudoMetadata:
    path = root / "Si.UPF"
    content = b"<UPF version='2.0.1'>Si fixture</UPF>\n"
    materialized = root != Path("/pseudo")
    if materialized:
        path.write_bytes(content)
    return PseudoMetadata(
        filepath=str(path),
        filename="Si.UPF",
        header_format="attr",
        provider="sssp",
        accuracy="efficiency",
        element="Si",
        pseudo_type="NC",
        functional="PBEsol",
        relativistic="scalar",
        cutoffs={"ecutwfc_ry": 30, "ecutrho_ry": 120},
        source_identifier="synthetic/Si.UPF",
        content_sha256=(hashlib.sha256(content).hexdigest() if materialized else None),
        content_size_bytes=len(content) if materialized else None,
        pseudo_info={
            "licence": "CC-BY-4.0",
            "licence_text": "Synthetic fixture licence\n",
            "citation": "Synthetic fixture pseudopotential.",
        },
    )


def _request(selection, pseudo_root: Path = Path("/pseudo")) -> ComputeRequest:
    return ComputeRequest(
        draft=CalculationDraft(
            structure=InMemoryStructureSource(_make_si_structure()),
            hints=CalculationHints(k_grid=(3, 3, 3), pseudo_type="NC"),
            pseudo_metadata=(_make_si_metadata(pseudo_root),),
        ),
        selection=selection,
    )


def test_root_interface_exposes_three_operations_and_their_contracts() -> None:
    assert Service.capabilities.__annotations__["return"] == "dict[str, Any]"
    assert Service.inspect_structure.__annotations__["return"] == "dict[str, Any]"
    assert Service.compute.__annotations__["return"] == "ComputationResult"
    assert StructureSource is not None
    assert ComputationResult is not None
    assert StructureSource is not None
    assert OutputTarget is not None
    assert not any(
        hasattr(Service, name)
        for name in (
            "recommend",
            "generate",
            "describe_tasks",
            "describe_codes",
            "describe_models",
        )
    )
    assert {
        InlineStructureSource,
        PathStructureSource,
        InMemoryStructureSource,
        ComputeRequest,
        DirectoryOutput,
        ArchiveOutput,
        DftInputData,
        GeneratedFile,
        GeneratedFiles,
        Records,
    }


def test_root_import_does_not_require_optional_transports() -> None:
    script = """
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'fastapi', 'mcp'}:
        raise ImportError(f'blocked optional import: {name}')
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
import goldilocks_core
assert goldilocks_core.Service
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_service_capabilities_and_inspection_share_the_root_interface() -> None:
    source = InMemoryStructureSource(_make_si_structure())

    with Service() as core:
        capabilities = core.capabilities()
        inspection = core.inspect_structure(source)

    assert capabilities["tasks"][0]["id"] == "scf_single_point"
    assert {preset["id"] for preset in capabilities["tasks"][0]["presets"]} == {
        "recommend",
        "generate",
    }
    assert inspection["structure"]["reduced_formula"] == "Si"


def test_recommendation_preset_runs_staged_core_pipeline() -> None:
    result = compute(_request(PresetSelection("recommend")))

    assert result.records[StructureAnalysisRecord]["reduced_formula"] == "Si"
    assert result.records[KPointSelection]["grid"] == [3, 3, 3]
    assert (
        result.records[SelectionRecord]["pseudopotentials"][0]["filename"] == "Si.UPF"
    )
    assert GeneratedFiles not in result.records


def test_generation_preset_runs_pipeline_through_generated_files(
    tmp_path: Path,
) -> None:
    result = compute(_request(PresetSelection("generate"), tmp_path))

    assert result.records[GeneratedFiles][0].path == "inputs/qe.in"
    assert "3  3  3  0  0  0" in result.records[GeneratedFiles][0].content


def test_explicit_record_selection_returns_one_generic_result() -> None:
    result = compute(
        _request(RecordSelection((StructureAnalysisRecord, ParameterAdvice)))
    )

    assert tuple(result.records) == (StructureAnalysisRecord, ParameterAdvice)
    assert to_portable(result)["selection"] == {"records": ["analysis", "advice"]}


def test_computation_result_serializes_stable_record_ids() -> None:
    iodine = Structure(Lattice.cubic(4.0), ["I"], [[0.0, 0.0, 0.0]])
    result = compute(
        ComputeRequest(
            draft=CalculationDraft(
                structure=InMemoryStructureSource(iodine),
                hints=CalculationHints(k_grid=(8, 8, 8)),
                pseudo_metadata=(),
            ),
            selection=PresetSelection("recommend"),
        )
    )
    document = to_portable(result)

    assert document["records"]["analysis"]["heavy_elements"] == ["I"]
    assert document["records"]["advice"]["spin_orbit"]["consider"] is True
    assert document["records"]["k_points"]["grid"] == [8, 8, 8]
