import hashlib
import json
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    CalculationDraft,
    CalculationHints,
    ComputeRequest,
    InlineStructureSource,
    InMemoryStructureSource,
    PathStructureSource,
    RecordSelection,
    Service,
    StructureInspection,
)
from goldilocks_core.contracts import KPointSelection
from goldilocks_core.io.structures import StructureInputError


def make_si_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Si"], [[0.0, 0.0, 0.0]])


def test_inline_cif_inspection_preserves_source_and_canonical_structure() -> None:
    content = make_si_structure().to(fmt="cif")
    source = InlineStructureSource(name="silicon.cif", content=content)

    with Service() as service:
        inspection = service.inspect_structure(source)

    assert isinstance(inspection, StructureInspection)
    assert inspection.source.origin == "inline"
    assert inspection.source.name == "silicon.cif"
    assert inspection.source.format == "cif"
    assert inspection.source.content == content
    assert inspection.source.sha256 == hashlib.sha256(content.encode()).hexdigest()
    assert inspection.source.size_bytes == len(content.encode())
    assert inspection.structure.reduced_formula == "Si"
    assert inspection.structure.site_count == 1
    canonical = Structure.from_str(inspection.canonical_cif, fmt="cif")
    assert canonical.matches(make_si_structure())
    assert isinstance(json.dumps(inspection.to_dict()), str)
    assert "pymatgen.core.structure" not in str(inspection.to_dict())


def test_inline_cif_without_extension_or_hint_resolves_from_content() -> None:
    source = InlineStructureSource(
        name="structure",
        content=make_si_structure().to(fmt="cif"),
    )

    with Service() as service:
        inspection = service.inspect_structure(source)

    assert inspection.source.format == "cif"
    assert inspection.structure.reduced_formula == "Si"


def test_path_inspection_reads_once_without_serializing_the_host_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = make_si_structure().to(fmt="poscar")
    path = tmp_path / "POSCAR"
    path.write_text(content, encoding="utf-8")
    original_read_text = Path.read_text
    reads = 0

    def counted_read_text(self: Path, *args, **kwargs) -> str:
        nonlocal reads
        if self == path:
            reads += 1
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read_text)

    with Service() as service:
        inspection = service.inspect_structure(PathStructureSource(path))

    assert reads == 1
    assert inspection.source.origin == "path"
    assert inspection.source.name == "POSCAR"
    assert inspection.source.format == "poscar"
    assert inspection.source.content == content
    assert str(tmp_path) not in str(inspection.to_dict())


def test_path_inspection_rejects_non_utf8_content(tmp_path: Path) -> None:
    path = tmp_path / "Si.cif"
    path.write_bytes(b"\xff\xfe")

    with Service() as service, pytest.raises(StructureInputError, match="UTF-8 text"):
        service.inspect_structure(PathStructureSource(path))


def test_in_memory_inspection_has_truthful_generated_source_metadata() -> None:
    structure = make_si_structure()

    with Service() as service:
        inspection = service.inspect_structure(InMemoryStructureSource(structure))

    assert inspection.source.to_dict() == {
        "origin": "generated",
        "name": "generated-structure",
        "format": "pymatgen",
        "content": None,
        "sha256": None,
        "size_bytes": None,
    }
    assert inspection.structure.reduced_formula == "Si"


def test_inspection_and_compute_each_parse_inline_content_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = InlineStructureSource(
        name="Si.cif", content=make_si_structure().to(fmt="cif")
    )
    original_from_str = Structure.from_str
    calls = 0

    def counted_from_str(cls, content: str, fmt: str, **kwargs) -> Structure:
        nonlocal calls
        calls += 1
        return original_from_str(content, fmt, **kwargs)

    monkeypatch.setattr(Structure, "from_str", classmethod(counted_from_str))

    request = ComputeRequest(
        draft=CalculationDraft(
            structure=source,
            hints=CalculationHints(k_grid=(2, 2, 2)),
        ),
        selection=RecordSelection((KPointSelection,)),
    )
    with Service() as service:
        service.inspect_structure(source)
        assert calls == 1
        service.compute(request)

    assert calls == 2


def test_compute_retains_the_same_normalized_structure_snapshot_as_inspection() -> None:
    source = InlineStructureSource(
        name="Si.cif", content=make_si_structure().to(fmt="cif")
    )
    request = ComputeRequest(
        draft=CalculationDraft(
            structure=source,
            hints=CalculationHints(k_grid=(2, 2, 2)),
        ),
        selection=RecordSelection((KPointSelection,)),
    )

    with Service() as service:
        inspection = service.inspect_structure(source)
        result = service.compute(request)

    assert result.draft.structure == inspection
    assert result.records[KPointSelection].grid == (2, 2, 2)


def test_scf_load_stage_describes_consuming_the_normalized_structure() -> None:
    with Service() as service:
        task = service.describe_tasks()[0]

    load_stage = next(stage for stage in task.stages if stage.id == "load_structure")
    assert "normalized" in load_stage.description.lower()
    assert "parse" not in load_stage.description.lower()


def test_contracts_expose_only_explicit_structure_source_variants() -> None:
    import goldilocks_core.contracts as contracts

    assert not hasattr(contracts, "StructureInput")


def test_structure_source_variants_have_explicit_serialized_shapes() -> None:
    structure = make_si_structure()

    assert InlineStructureSource(
        name="Si.cif", content="data_Si", format="cif"
    ).to_dict() == {
        "kind": "inline",
        "name": "Si.cif",
        "content": "data_Si",
        "format": "cif",
    }
    assert PathStructureSource(Path("structures/Si.cif")).to_dict() == {
        "kind": "path",
        "path": "structures/Si.cif",
    }
    assert InMemoryStructureSource(structure).to_dict() == {
        "kind": "in_memory",
        "structure": structure.as_dict(),
    }


@pytest.mark.parametrize("format_hint", ["cif", "poscar"])
def test_inspection_rejects_invalid_supported_structure_content(
    format_hint: str,
) -> None:
    source = InlineStructureSource(
        name=f"broken.{format_hint}",
        content="not a crystal structure",
        format=format_hint,
    )

    with (
        Service() as service,
        pytest.raises(
            ValueError,
            match=f"Could not parse structure content as {format_hint.upper()}",
        ),
    ):
        service.inspect_structure(source)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            lambda: InlineStructureSource(name="", content="data_Si"),
            "InlineStructureSource.name",
        ),
        (
            lambda: InlineStructureSource(name="  ", content="data_Si"),
            "InlineStructureSource.name",
        ),
        (
            lambda: InlineStructureSource(name="Si.xyz", content="Si", format="xyz"),
            "Unsupported structure format",
        ),
        (lambda: PathStructureSource(""), "PathStructureSource.path"),
        (lambda: PathStructureSource("  "), "PathStructureSource.path"),
        (
            lambda: InMemoryStructureSource(object()),
            "InMemoryStructureSource.structure",
        ),
    ],
)
def test_structure_source_variants_reject_invalid_shapes(source, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        source()
