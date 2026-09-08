import hashlib
import json
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core import (
    InlineStructureSource,
    InMemoryStructureSource,
    PathStructureSource,
    Service,
)
from goldilocks_core.io.structures import StructureInputError


@pytest.fixture
def service():
    with Service() as service:
        yield service


@pytest.mark.parametrize("format", ["cif", "poscar"])
def test_sources_preserve_structure_and_source_provenance(
    service, silicon_structure, tmp_path: Path, format: str
) -> None:
    content = silicon_structure.to(fmt=format)
    path = tmp_path / f"silicon.{format}"
    path.write_text(content, encoding="utf-8")
    sources = (
        InlineStructureSource(path.name, content),
        PathStructureSource(path),
        InMemoryStructureSource(silicon_structure),
    )
    inspections = [service.inspect_structure(source) for source in sources]
    for inspection, origin in zip(inspections, ("inline", "path", "generated")):
        canonical = Structure.from_str(inspection.canonical_cif, fmt="cif")
        assert canonical.matches(silicon_structure)
        assert inspection.source.origin == origin
        document = json.loads(json.dumps(inspection.to_dict()))
        assert str(tmp_path) not in str(document)
        assert "pymatgen.core.structure" not in str(document)
        if origin == "generated":
            assert inspection.source.content is None
            assert inspection.source.sha256 is None
            assert inspection.source.size_bytes is None
        else:
            assert inspection.source.name == path.name
            assert inspection.source.format == format
            assert inspection.source.content == content
            assert (
                inspection.source.sha256 == hashlib.sha256(content.encode()).hexdigest()
            )
            assert inspection.source.size_bytes == len(content.encode())


@pytest.mark.parametrize("newline", ["\r\n", "\r"], ids=["crlf", "cr"])
def test_path_inspection_preserves_source_bytes(
    service, silicon_structure, tmp_path: Path, newline: str
) -> None:
    source_bytes = (
        silicon_structure.to(fmt="cif").replace("\n", newline).encode("utf-8")
    )
    path = tmp_path / "silicon.cif"
    path.write_bytes(source_bytes)

    inspection = service.inspect_structure(PathStructureSource(path))

    assert inspection.source.content.encode("utf-8") == source_bytes
    assert inspection.source.sha256 == hashlib.sha256(source_bytes).hexdigest()
    assert inspection.source.size_bytes == len(source_bytes)


def test_inspection_preserves_partial_periodicity(service) -> None:
    structure = Structure(
        Lattice(
            [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 20.0]],
            pbc=(True, True, False),
        ),
        ["Si"],
        [[0.0, 0.0, 0.5]],
    )

    inspection = service.inspect_structure(InMemoryStructureSource(structure))

    assert inspection.structure.periodicity == (True, True, False)


@pytest.mark.parametrize(
    ("name", "format_hint", "format"),
    [
        ("structure", None, "cif"),
        ("POSCAR", "cif", "cif"),
        ("POSCAR", None, "poscar"),
        ("silicon.poscar", None, "poscar"),
        ("silicon.cif", "poscar", "poscar"),
    ],
)
def test_format_hint_then_filename_then_content_precedence(
    service, silicon_structure, tmp_path: Path, name, format_hint, format
) -> None:
    content = silicon_structure.to(fmt=format)
    if format == "poscar":
        content = "\n".join(["data_valid_poscar", *content.splitlines()[1:]]) + "\n"
    sources = [InlineStructureSource(name, content, format_hint)]
    if format_hint is None:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        sources.append(PathStructureSource(path))
    for source in sources:
        inspection = service.inspect_structure(source)
        assert inspection.source.format == format
        assert Structure.from_str(inspection.canonical_cif, fmt="cif").matches(
            silicon_structure
        )


def test_disordered_oxidized_structure_preserves_chemistry_and_geometry(
    service,
) -> None:
    structure = Structure(
        Lattice.orthorhombic(4, 5, 6),
        [{"Fe2+": 0.25, "Mn2+": 0.75}, "O2-"],
        [[0.1, 0.2, 0.3], [0.6, 0.7, 0.8]],
    )
    inspection = service.inspect_structure(InMemoryStructureSource(structure))
    site = inspection.structure.sites[0]
    assert site.fractional_coordinates == pytest.approx((0.1, 0.2, 0.3))
    assert site.cartesian_coordinates_angstrom == pytest.approx((0.4, 1.0, 1.8))
    assert [
        (s.symbol, s.label, s.occupancy, s.oxidation_state) for s in site.species
    ] == [("Fe", "Fe2+", 0.25, 2.0), ("Mn", "Mn2+", 0.75, 2.0)]
    restored = Structure.from_str(inspection.canonical_cif, fmt="cif")
    assert restored.matches(structure)
    assert restored.composition == structure.composition
    inline = service.inspect_structure(
        InlineStructureSource("alloy.cif", inspection.canonical_cif)
    )
    assert inline.structure.sites[0].species == site.species


@pytest.mark.parametrize("format", ["cif", "poscar"])
@pytest.mark.parametrize("content", ["not a crystal structure", " \n"])
def test_inspection_rejects_invalid_content(service, tmp_path, format, content) -> None:
    path = tmp_path / f"broken.{format}"
    path.write_text(content, encoding="utf-8")
    for source in (
        InlineStructureSource(path.name, content),
        PathStructureSource(path),
    ):
        with pytest.raises(StructureInputError):
            service.inspect_structure(source)


@pytest.mark.parametrize("failure", ["missing", "directory", "non_utf8"])
def test_path_inspection_reports_file_errors(service, tmp_path, failure) -> None:
    path = tmp_path / "Si.cif"
    if failure == "directory":
        path.mkdir()
    elif failure == "non_utf8":
        path.write_bytes(b"\xff\xfe")
    error = FileNotFoundError if failure == "missing" else StructureInputError
    with pytest.raises(error):
        service.inspect_structure(PathStructureSource(path))


@pytest.mark.parametrize(
    "name", ["", "  ", ".", "..", "a/b.cif", "a\\b.cif", "Si\n.cif"]
)
def test_inline_source_rejects_invalid_filename(name) -> None:
    with pytest.raises(ValueError):
        InlineStructureSource(name, "data_Si")


@pytest.mark.parametrize(
    "source",
    [
        lambda: InlineStructureSource("Si.xyz", "Si", "xyz"),
        lambda: InlineStructureSource("Si.cif", None),
        lambda: PathStructureSource("  "),
        lambda: PathStructureSource(42),
        lambda: InMemoryStructureSource(object()),
    ],
)
def test_structure_sources_reject_invalid_shapes(source) -> None:
    with pytest.raises(ValueError):
        source()
