import hashlib
import json
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from goldilocks_core.inputs.structure import (
    InlineStructureSource,
    InMemoryStructureSource,
    PathStructureSource,
    StructureInputError,
    normalize_structure,
    require_ordered,
)
from goldilocks_core.serialization import to_portable


def _inspect(source):
    return normalize_structure(source).inspection


@pytest.mark.parametrize("format", ["cif", "poscar"])
def test_sources_preserve_structure_and_source_provenance(
    silicon_structure, tmp_path: Path, format: str
) -> None:
    content = silicon_structure.to(fmt=format)
    path = tmp_path / f"silicon.{format}"
    path.write_text(content, encoding="utf-8")
    sources = (
        InlineStructureSource(path.name, content),
        PathStructureSource(path),
        InMemoryStructureSource(silicon_structure),
    )
    inspections = [_inspect(source) for source in sources]
    for inspection, origin in zip(
        inspections, ("inline", "path", "generated"), strict=True
    ):
        canonical = Structure.from_str(inspection["canonical_cif"], fmt="cif")
        assert canonical.matches(silicon_structure)
        assert inspection["source"]["origin"] == origin
        document = json.loads(json.dumps(to_portable(inspection)))
        assert str(tmp_path) not in str(document)
        assert "pymatgen.core.structure" not in str(document)
        if origin == "generated":
            assert inspection["source"]["content"] is None
            assert inspection["source"]["sha256"] is None
            assert inspection["source"]["size_bytes"] is None
        else:
            assert inspection["source"]["name"] == path.name
            assert inspection["source"]["format"] == format
            assert inspection["source"]["content"] == content
            assert (
                inspection["source"]["sha256"]
                == hashlib.sha256(content.encode()).hexdigest()
            )
            assert inspection["source"]["size_bytes"] == len(content.encode())


@pytest.mark.parametrize("newline", ["\r\n", "\r"], ids=["crlf", "cr"])
def test_path_inspection_preserves_source_bytes(
    silicon_structure, tmp_path: Path, newline: str
) -> None:
    source_bytes = (
        silicon_structure.to(fmt="cif").replace("\n", newline).encode("utf-8")
    )
    path = tmp_path / "silicon.cif"
    path.write_bytes(source_bytes)

    inspection = _inspect(PathStructureSource(path))

    assert inspection["source"]["content"].encode("utf-8") == source_bytes
    assert inspection["source"]["sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert inspection["source"]["size_bytes"] == len(source_bytes)
    assert Structure.from_str(inspection["canonical_cif"], fmt="cif").matches(
        silicon_structure
    )


def test_inspection_preserves_partial_periodicity() -> None:
    structure = Structure(
        Lattice(
            [[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 20.0]],
            pbc=(True, True, False),
        ),
        ["Si"],
        [[0.0, 0.0, 0.5]],
    )

    inspection = _inspect(InMemoryStructureSource(structure))

    assert inspection["structure"]["periodicity"] == [True, True, False]


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
    silicon_structure, tmp_path: Path, name, format_hint, format
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
        inspection = _inspect(source)
        assert inspection["source"]["format"] == format
        assert Structure.from_str(inspection["canonical_cif"], fmt="cif").matches(
            silicon_structure
        )


def test_disordered_oxidized_structure_preserves_chemistry_and_geometry() -> None:
    structure = Structure(
        Lattice.orthorhombic(4, 5, 6),
        [{"Fe2+": 0.25, "Mn2+": 0.75}, "O2-"],
        [[0.1, 0.2, 0.3], [0.6, 0.7, 0.8]],
    )
    inspection = _inspect(InMemoryStructureSource(structure))
    site = inspection["structure"]["sites"][0]
    assert site["fractional_coordinates"] == pytest.approx((0.1, 0.2, 0.3))
    assert site["cartesian_coordinates_angstrom"] == pytest.approx((0.4, 1.0, 1.8))
    assert [
        (s["symbol"], s["label"], s["occupancy"], s["oxidation_state"])
        for s in site["species"]
    ] == [("Fe", "Fe2+", 0.25, 2.0), ("Mn", "Mn2+", 0.75, 2.0)]
    restored = Structure.from_str(inspection["canonical_cif"], fmt="cif")
    assert restored.matches(structure)
    assert restored.composition == structure.composition
    inline = _inspect(InlineStructureSource("alloy.cif", inspection["canonical_cif"]))
    assert inline["structure"]["sites"][0]["species"] == site["species"]


@pytest.mark.parametrize(
    ("format", "labels"), [("cif", ["Ni1", "O1"]), ("poscar", ["Ni", "O"])]
)
def test_inspection_reports_each_site_s_label(format: str, labels: list[str]) -> None:
    """#185: a site's label is what starting_magnetization is keyed by, and
    /inspect reported only the species string ('Ni'). A CIF keeps its
    _atom_site_label (Ni1/O1, as the MC3D CIF of NiO has); a POSCAR's
    labels are its element symbols."""
    nio = Structure(
        Lattice.from_parameters(2.95, 2.95, 2.95, 60, 60, 60),
        ["Ni", "O"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        labels=["Ni1", "O1"],
    )

    inspection = _inspect(InlineStructureSource(f"NiO.{format}", nio.to(fmt=format)))

    sites = inspection["structure"]["sites"]
    assert [site["label"] for site in sites] == labels
    assert [site["species"][0]["label"] for site in sites] == ["Ni", "O"]


@pytest.mark.parametrize("format", ["cif", "poscar"])
@pytest.mark.parametrize("content", ["not a crystal structure", " \n"])
def test_inspection_rejects_invalid_content(tmp_path, format, content) -> None:
    path = tmp_path / f"broken.{format}"
    path.write_text(content, encoding="utf-8")
    for source in (
        InlineStructureSource(path.name, content),
        PathStructureSource(path),
    ):
        with pytest.raises(StructureInputError):
            _inspect(source)


@pytest.mark.parametrize("failure", ["missing", "directory", "non_utf8"])
def test_path_inspection_reports_file_errors(tmp_path, failure) -> None:
    path = tmp_path / "Si.cif"
    if failure == "directory":
        path.mkdir()
    elif failure == "non_utf8":
        path.write_bytes(b"\xff\xfe")
    error = FileNotFoundError if failure == "missing" else StructureInputError
    with pytest.raises(error):
        _inspect(PathStructureSource(path))


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


def test_an_ordered_structure_is_accepted() -> None:
    silicon = Structure(
        Lattice.cubic(5.43), ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]]
    )

    assert require_ordered(silicon) is None


def test_a_disordered_structure_names_its_first_partially_occupied_sites() -> None:
    """#224: sites are numbered from 1, as the Workbench's site list is; a
    vacancy counts like a mixed site, and sites past the third are counted."""
    alloy = {"Fe": 0.5, "Ni": 0.5}
    structure = Structure(
        Lattice.cubic(8.0),
        ["O", alloy, {"O": 0.9}, alloy, alloy, alloy],
        [
            [0, 0, 0],
            [0.5, 0, 0],
            [0, 0.5, 0],
            [0, 0, 0.5],
            [0.5, 0.5, 0],
            [0.5, 0, 0.5],
        ],
    )

    with pytest.raises(StructureInputError) as error:
        require_ordered(structure)

    assert str(error.value) == (
        "the structure has partially occupied sites, which no input file can "
        "describe: site 2 (Fe0.5 Ni0.5), site 3 (O0.9), site 4 (Fe0.5 Ni0.5) and "
        "2 more. Order it first, for example as a supercell with one species on "
        "every site."
    )
    assert error.value.public_error()["kind"] == "invalid_structure"
