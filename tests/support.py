"""Shared, plain (non-fixture) test helpers.

Not named ``conftest.py``: more than one ``conftest.py`` exists in this
tree (``tests/conftest.py``, ``tests/server/conftest.py``), and pytest's
own rootless import mode gives every file literally named ``conftest.py``
the same bare top-level module name -- a test module doing
``from conftest import X`` resolves against whichever ``conftest.py``
Python's import cache happens to have already bound to that name, which
is order-dependent once more than one exists (confirmed the hard way,
v2 epic 9, #9: importable in isolation, ``ImportError`` once the full
suite collects ``tests/server/`` too). Fixtures still belong in
``conftest.py`` (pytest's own fixture-discovery is directory-scoped, not
Python's plain import system, so that part is unaffected); plain helper
*functions* a test calls directly belong here instead, under a name
unique across the whole tree.

``run_cli``/``default_profile_installed``/``REAL_ASSET_ROOT`` moved
here from ``tests/integration/test_cli_v2.py`` (v2 epic 9, #9) once a
second file (the five-scenario acceptance suite) needed to spawn the
real CLI subprocess too -- the ``real_assets`` fixture that wraps
``default_profile_installed`` stays in ``tests/conftest.py`` for the
same fixtures-are-directory-scoped reason.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from pymatgen.core import Element, Lattice, Species, Structure
from pymatgen.core.surface import Slab, SlabGenerator

from goldilocks_core.advisors.magnetic_config import (
    MagneticCell,
    MagneticConfigFacts,
    MagneticConfigHumanInput,
    OrderingRecord,
    framed_cell,
    magnetic_cell,
    magnetic_config,
)
from goldilocks_core.analysis.geometry import GeometryFacts, SlabGeometry, vacuum_axes
from goldilocks_core.assets.records import AssetFile, AssetSpec
from goldilocks_core.assets.runtime import statuses
from goldilocks_core.assets.store import AssetStore, asset_root
from goldilocks_core.inputs.structure import (
    InMemoryStructureSource,
    StructureSourceDocument,
    normalize_structure,
)
from goldilocks_core.pw_symmetry import pw_frame
from goldilocks_core.resolution import Provenance, Resolved

if TYPE_CHECKING:
    from collections.abc import Sequence

    from goldilocks_core.analysis.geometry import Dimensionality, LatticeAxis
    from goldilocks_core.analysis.is_magnetic import Magnetism
    from goldilocks_core.assets.pseudopotentials.registry import PseudoTable
    from goldilocks_core.pw_symmetry import PwRotations
    from goldilocks_core.resolution import FieldState
    from goldilocks_core.types import RelativisticTreatment

INTERNAL_TEXT = re.compile(
    r"\.py\b|goldilocks_core|''|\[['\"]|plan=|\(pitfall|\bepic\b|design\.md"
)
"""What user-facing text must not contain (#151): a module path, the package
name, a ``repr()`` artefact -- a quoted name followed by ``'s`` reads
``'scarf''s``, a list of names ``['Fe9']`` -- an internal literal such as
``plan=``, a design-document id such as ``(pitfall A10)`` or a roadmap note.
Quantum ESPRESSO literals such as ``occupations='fixed'`` stay quoted."""

REAL_ASSET_ROOT = asset_root()
"""The real, developer-machine asset root (not the per-test isolated
one ``conftest.py``'s ``isolated_default_asset_root`` autouse fixture
sets up) -- shared by every test that needs a genuinely-installed
pseudopotential table, not a synthetic fixture."""


def default_profile_installed() -> bool:
    store = AssetStore(REAL_ASSET_ROOT)
    return all(state == "installed" for _, _, state in statuses("default", store=store))


def run_cli(
    *arguments: str, cwd: Path | None = None, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    """Spawn the real ``goldilocks`` CLI entry point as a subprocess --
    shared by every integration test that exercises argument parsing
    end to end (v2 epic 9, #9), not just the internal core API."""
    return subprocess.run(
        [sys.executable, "-m", "goldilocks_core.cli.core", *arguments],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def in_memory_source(structure: Structure) -> StructureSourceDocument:
    """The source identity a structure built in memory publishes in a
    bundle's ``request`` (no submitted text, so no sha256), for tests that
    pass a pymatgen ``Structure`` to ``advise`` and then bundle it (#176)."""
    return normalize_structure(InMemoryStructureSource(structure)).source


def magnetic_decision(
    structure: Structure,
    is_magnetic: FieldState[Magnetism],
    needs_soc: FieldState[bool] | None = None,
    z_valences: dict[str, float] | None = None,
    human: MagneticConfigHumanInput | None = None,
    *,
    soc_table: FieldState[PseudoTable] | None = None,
) -> FieldState[MagneticConfigFacts]:
    """``magnetic_cell`` then ``magnetic_config``, the two steps
    ``service/_magnetic.py`` runs around pseudopotential selection -- for
    advisor-level tests that need one structure's whole magnetic
    decision (#128)."""
    cell = magnetic_cell(structure, is_magnetic, human)
    return magnetic_config(cell, needs_soc, soc_table, z_valences)


def framed_magnetic_cell(
    structure: Structure, magnetism: Magnetism = "non_magnetic", **settings: Any
) -> Resolved[MagneticCell]:
    """``magnetic_cell`` then ``framed_cell``, as ``service/_magnetic.py``
    runs them, with ``magnetism`` as the ``is_magnetic`` answer and
    ``settings`` as the human magnetic overrides: the cell the writer renders
    and the band path is read from (#118)."""
    cell = magnetic_cell(
        structure,
        Resolved(magnetism, Provenance(source="heuristic")),
        MagneticConfigHumanInput(**settings),
    )
    return Resolved(framed_cell(cell.value), cell.provenance)


def strict_json(document: str | bytes) -> Any:
    """``json.loads`` that rejects the non-standard ``Infinity``,
    ``-Infinity`` and ``NaN`` tokens Python's ``json.dumps`` writes by
    default (#137) -- shared by every test that checks a JSON document a
    transport or the bundle writes."""

    def reject(constant: str) -> None:
        raise ValueError(f"{constant} is not valid JSON")

    return json.loads(document, parse_constant=reject)


def fixture_upf(
    element: str,
    z_valence: float,
    relativistic: RelativisticTreatment = "scalar",
    functional: str = "PBEsol",
) -> bytes:
    """A minimal SSSP-shaped UPF file for ``element``: only the
    ``PP_HEADER`` attributes the importer reads and the projector counts
    every installed UPF carries, which the job's memory estimate reads
    (#148)."""
    return (
        b'<UPF version="2.0.1">\n'
        + (
            f'<PP_HEADER element="{element}" pseudo_type="NC" '
            f'functional="{functional}" '
            f'relativistic="{relativistic}" z_valence="{z_valence}" '
            'number_of_wfc="2" number_of_proj="4" l_max="1"/>\n'
        ).encode()
        + b"</UPF>\n"
    )


SSSP_FIXTURE_UPF = fixture_upf("Si", 4.0)


def sssp_fixture_archive(path: Path, members: dict[str, bytes]) -> None:
    """Write a ``.tar.gz`` containing ``members`` -- shared by every test
    that builds a fully-offline (``file://``, no network) SSSP-shaped
    pseudopotential asset."""
    with tarfile.open(path, "w:gz") as tar:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))


def sssp_fixture_table_spec(
    tmp_path: Path,
    z_valences: dict[str, float] | None = None,
    relativistic: RelativisticTreatment = "scalar",
    functional: str = "PBEsol",
) -> tuple[AssetSpec, PseudoTable]:
    """Build one real, fully-offline SSSP-shaped pseudopotential asset
    (file:// sources, no network) -- shared between
    ``tests/unit/test_service_v2.py`` and ``tests/unit/test_service_dos.py``
    (v2 epic 9, #9), matching the pattern already used by
    ``tests/unit/test_pseudo_importers.py``'s ``install_sssp_fixture``.

    ``z_valences`` maps every element the table covers to its UPF
    ``z_valence``. The default is Si alone, whose file is
    ``SSSP_FIXTURE_UPF`` as this module holds it at call time, so a test
    can monkeypatch it to vary the header. ``relativistic="full"`` builds
    the fully relativistic table a spin-orbit run selects (it needs
    ``z_valences``), named ``sssp-fixture-fr`` so it installs next to the
    scalar one. Another ``functional`` (it needs ``z_valences``) suffixes
    the id with it, ``sssp-fixture-lda`` for LDA."""
    from goldilocks_core.assets.pseudopotentials.registry import PseudoTable

    table_id = "sssp-fixture" if relativistic == "scalar" else "sssp-fixture-fr"
    if functional != "PBEsol":
        table_id += f"-{functional.lower()}"
    upf_by_element = (
        {
            element: fixture_upf(element, z_valence, relativistic, functional)
            for element, z_valence in z_valences.items()
        }
        if z_valences
        else {"Si": SSSP_FIXTURE_UPF}
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    upfs = tmp_path / "table.tar.gz"
    sidecar = tmp_path / "table.json"
    licence = tmp_path / "LICENSE.txt"
    sssp_fixture_archive(
        upfs,
        {f"nested/{element}.upf": upf for element, upf in upf_by_element.items()},
    )
    sidecar.write_text(
        json.dumps(
            {
                element: {
                    "filename": f"{element}.upf",
                    "md5": hashlib.md5(upf).hexdigest(),
                    "cutoff_wfc": 30.0,
                    "cutoff_rho": 120.0,
                    "pseudopotential": f"{element} fixture",
                }
                for element, upf in upf_by_element.items()
            }
        )
    )
    licence.write_text("SSSP fixture licence\n")
    spec = AssetSpec(
        f"pseudopotentials/{table_id}",
        "1",
        (
            AssetFile("pseudopotentials", "source/table.tar.gz", upfs.as_uri()),
            AssetFile("metadata", "source/table.json", sidecar.as_uri()),
            AssetFile("licence", "source/LICENSE.txt", licence.as_uri()),
        ),
    )
    registry_table = PseudoTable(
        id=table_id,
        provider="sssp",
        upstream_table="fixture",
        version="1",
        functional=functional,
        relativistic=relativistic,
        accuracy="efficiency",
        licence="fixture licence",
        citation="Synthetic SSSP fixture, cite me.",
        elements=tuple(sorted(upf_by_element)),
        asset=spec,
        default=True,
    )
    return spec, registry_table


def write_registry(path: Path, table: PseudoTable) -> None:
    """Write a one-table SSSP-shaped registry declaring ``table`` to ``path``,
    for CLI subprocesses (``GOLDILOCKS_PSEUDO_REGISTRY``)."""
    files = "".join(
        f'\n[[tables."{table.id}".files]]\n'
        f'role = "{file.role}"\npath = "{file.path}"\nurl = "{file.url}"\n'
        for file in table.asset.files
    )
    path.write_text(
        f'[tables."{table.id}"]\n'
        f'provider = "{table.provider}"\n'
        f'upstream_table = "{table.upstream_table}"\n'
        f'version = "{table.version}"\n'
        f'functional = "{table.functional}"\n'
        f'relativistic = "{table.relativistic}"\n'
        f'accuracy = "{table.accuracy}"\n'
        f'licence = "{table.licence}"\n'
        f'citation = "{table.citation}"\n'
        "default = true\n"
        f"elements = {json.dumps(list(table.elements))}\n" + files,
        encoding="utf-8",
    )


def dojo_fixture_table_spec(
    tmp_path: Path,
    *,
    upf: bytes = SSSP_FIXTURE_UPF,
    report_functional: object = "PBEsol",
    table_functional: str = "PBEsol",
    frozen_4f_core: bool = False,
) -> tuple[AssetSpec, PseudoTable]:
    """Build one fully-offline PseudoDojo-shaped table covering Si (file://
    sources, no network): ``upf`` and a dojo report whose ``low``/``normal``/
    ``high`` hints are 10/15/20 Ha (20/30/40 Ry), under a table with
    ``charge_density_dual`` 4. Its registry id ``pseudodojo-fixture``
    differs from its asset id."""
    from goldilocks_core.assets.pseudopotentials.registry import PseudoTable

    tmp_path.mkdir(parents=True, exist_ok=True)
    upfs = tmp_path / "upfs.tgz"
    reports = tmp_path / "reports.tgz"
    sssp_fixture_archive(upfs, {"nested/Si.upf": upf})
    report = {
        "xc": report_functional,
        "md5_upf": hashlib.md5(upf).hexdigest(),
        "hints": {
            "low": {"ecut": 10.0},
            "normal": {"ecut": 15.0},
            "high": {"ecut": 20.0},
        },
    }
    sssp_fixture_archive(reports, {"nested/Si.djrepo": json.dumps(report).encode()})
    spec = AssetSpec(
        "pseudopotentials/pseudodojo-fixture",
        "1",
        (
            AssetFile("pseudopotentials", "source/upfs.tgz", upfs.as_uri()),
            AssetFile("metadata", "source/reports.tgz", reports.as_uri()),
        ),
    )
    registry_table = PseudoTable(
        id="pseudodojo-fixture",
        provider="pseudodojo",
        upstream_table="fixture",
        version="1",
        functional=table_functional,
        relativistic="scalar",
        accuracy="efficiency",
        licence="fixture licence",
        citation="fixture citation",
        elements=("Si",),
        asset=spec,
        charge_density_dual=4.0,
        default=True,
        frozen_4f_core=frozen_4f_core,
    )
    return spec, registry_table


_MC2D_60196AFB_PHOSPHORENE_CIF = """\
data_P
_symmetry_space_group_name_H-M   'P 1'
_cell_length_a   3.30546570
_cell_length_b   4.61434267
_cell_length_c   22.18331037
_cell_angle_alpha   90.00000000
_cell_angle_beta   90.00000000
_cell_angle_gamma   90.00000000
_symmetry_Int_Tables_number   1
loop_
 _symmetry_equiv_pos_site_id
 _symmetry_equiv_pos_as_xyz
  1  'x, y, z'
loop_
 _atom_site_type_symbol
 _atom_site_label
 _atom_site_symmetry_multiplicity
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
  P  P0  1  0.50000000  0.91158132  0.45243739  1
  P  P1  1  0.50000000  0.08841868  0.54756261  1
  P  P2  1  1.00000000  0.58841862  0.45243739  1
  P  P3  1  1.00000000  0.41158138  0.54756261  1
"""


def phosphorene() -> Structure:
    """Phosphorene monolayer, MC2D mc2d-60196afb: 4 P atoms, P-P bonds of
    2.22-2.26 A, vacuum along c (22.2 A cell)."""
    return Structure.from_str(_MC2D_60196AFB_PHOSPHORENE_CIF, fmt="cif")


_MC3D_6516_CARBON_PAIR_CIF = """\
data_0

loop_
  _atom_site_label
  _atom_site_fract_x
  _atom_site_fract_y
  _atom_site_fract_z
  _atom_site_type_symbol
         C1  0.33333333333333337  0.6666666666666667  0.24999999999854772  C
         C2  0.6666666666666667  0.33333333333333337  0.7500000000014405  C
_cell_angle_alpha                       90.0
_cell_angle_beta                        90.0
_cell_angle_gamma                       119.99999999987348
_cell_length_a                          10.559999907643
_cell_length_b                          10.55999990768339
_cell_length_c                          17.179999849807
loop_
  _symmetry_equiv_pos_as_xyz
         'x, y, z'
_symmetry_int_tables_number             1
_symmetry_space_group_name_H-M          'P 1'
"""


def carbon_pair_in_a_box() -> Structure:
    """MC3D mc3d-6516, an isolated-atom artifact: two C atoms 10.5 A apart
    in a 10.56 x 10.56 x 17.18 A hexagonal cell, so no atom has a neighbour
    within 10 A."""
    return Structure.from_str(_MC3D_6516_CARBON_PAIR_CIF, fmt="cif")


def silicon_dimer_in_a_box() -> Structure:
    """An Si2 dimer (bond 2.25 A, along [111]) in a 12 A cubic box: 10.7 A
    of vacuum along every lattice vector. Si is the one element of
    ``sssp_fixture_table_spec``'s default table, so the dimer runs through
    ``generate()`` without installed pseudopotentials."""
    offset = 2.25 / (12.0 * 3**0.5)
    return Structure(
        Lattice.cubic(12.0), ["Si", "Si"], [[0, 0, 0], [offset, offset, offset]]
    )


def sodium_chloride() -> Structure:
    """Rock salt, Fm-3m, a = 5.64 A: Na-Cl 2.82 A."""
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(5.64), ["Na", "Cl"], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )


def graphite() -> Structure:
    """Bernal graphite, C on the 2b and 2c sites of P6_3/mmc, a = 2.46 A,
    c = 6.71 A: C-C 1.42 A in the sheets, 3.36 A between them."""
    return Structure.from_spacegroup(
        "P6_3/mmc",
        Lattice.hexagonal(2.46, 6.71),
        ["C", "C"],
        [[0, 0, 0.25], [1 / 3, 2 / 3, 0.25]],
    )


def molybdenum_disulfide() -> Structure:
    """2H-MoS2, P6_3/mmc, a = 3.16 A, c = 12.29 A: S-Mo-S sheets stacked
    across a van der Waals gap."""
    return Structure.from_spacegroup(
        "P6_3/mmc",
        Lattice.hexagonal(3.16, 12.29),
        ["Mo", "S"],
        [[1 / 3, 2 / 3, 0.25], [1 / 3, 2 / 3, 0.621]],
    )


def rhombohedral_bismuth_selenide() -> Structure:
    """Bi2Se3 (R-3m, hexagonal a = 4.14 A, c = 28.64 A) in its 5-atom
    rhombohedral primitive cell, a = 9.84 A and alpha = 24.28 deg, the cell
    MC3D mc3d-75053 stores. pymatgen puts c along z, so a and b point out
    of the xy plane."""
    a, c = 4.14, 28.64
    length = math.sqrt(a**2 / 3 + c**2 / 9)
    alpha = math.degrees(math.acos((2 * c**2 - 3 * a**2) / (2 * c**2 + 6 * a**2)))
    bismuth, selenium = 0.4008, 0.2117
    return Structure(
        Lattice.rhombohedral(length, alpha),
        ["Bi", "Bi", "Se", "Se", "Se"],
        [[bismuth] * 3, [-bismuth] * 3, [0, 0, 0], [selenium] * 3, [-selenium] * 3],
    )


def graphene_monolayer(c: float = 20.0) -> Structure:
    """A graphene sheet (C-C 1.42 A) in the xy plane, in a cell ``c`` A high
    along z (20 A by default), all of it vacuum."""
    return Structure(
        Lattice.hexagonal(2.46, c), ["C", "C"], [[0, 0, 0.5], [1 / 3, 2 / 3, 0.5]]
    )


def molybdenum_disulfide_monolayer(c: float = 20.0) -> Structure:
    """One S-Mo-S sheet of ``molybdenum_disulfide`` (a = 3.16 A, S planes
    3.17 A apart) in the xy plane, in a cell ``c`` A high along z (20 A by
    default)."""
    half_thickness = 1.585 / c
    return Structure(
        Lattice.hexagonal(3.16, c),
        ["Mo", "S", "S"],
        [
            [1 / 3, 2 / 3, 0.5],
            [2 / 3, 1 / 3, 0.5 + half_thickness],
            [2 / 3, 1 / 3, 0.5 - half_thickness],
        ],
    )


def janus_molybdenum_sulfide_selenide(c: float = 20.0) -> Structure:
    """A Janus MoSSe sheet (a = 3.22 A) in the xy plane: the S plane 1.55 A
    above Mo and the Se plane 1.65 A below, in a cell ``c`` A high along z
    (20 A by default). No symmetry operation maps c to -c (P3m1), so the
    sheet carries a dipole along its normal."""
    return Structure(
        Lattice.hexagonal(3.22, c),
        ["Mo", "S", "Se"],
        [
            [1 / 3, 2 / 3, 0.5],
            [2 / 3, 1 / 3, 0.5 + 1.55 / c],
            [2 / 3, 1 / 3, 0.5 - 1.65 / c],
        ],
    )


def rotated_about_x(structure: Structure, degrees: float) -> Structure:
    """``structure`` turned rigidly about the Cartesian x axis."""
    angle = np.radians(degrees)
    rotation = np.array(
        [
            [1, 0, 0],
            [0, np.cos(angle), -np.sin(angle)],
            [0, np.sin(angle), np.cos(angle)],
        ]
    )
    return Structure(
        Lattice(structure.lattice.matrix @ rotation.T),
        structure.species,
        structure.frac_coords,
    )


def with_vacuum_along(structure: Structure, axis: LatticeAxis) -> Structure:
    """``structure``, whose vacuum lies along c, with its lattice vectors and
    fractional coordinates permuted cyclically so that the vacuum vector
    becomes ``axis``. Atoms keep their Cartesian positions and site order."""
    order = np.roll([0, 1, 2], {"a": 1, "b": 2, "c": 0}[axis])
    return Structure(
        Lattice(structure.lattice.matrix[order]),
        structure.species,
        structure.frac_coords[:, order],
    )


def graphene_with_vacuum_along_x() -> Structure:
    """The graphene sheet of ``graphene_monolayer`` in the yz plane: the
    vacuum vector is a = (20, 0, 0) A, and b and c span the sheet."""
    return Structure(
        Lattice([[20.0, 0, 0], [0, 2.46, 0], [0, -1.23, 1.23 * math.sqrt(3)]]),
        ["C", "C"],
        [[0.5, 0, 0], [0.5, 1 / 3, 2 / 3]],
    )


def graphene_with_c_tilted() -> Structure:
    """``graphene_monolayer`` with c leaning 3 A along x: a and b stay in the
    xy plane and the vacuum along c is still 20 A."""
    sheet = graphene_monolayer()
    a, b, _ = sheet.lattice.matrix
    return Structure(Lattice([a, b, [3.0, 0, 20.0]]), sheet.species, sheet.frac_coords)


def graphene_with_vacuum_along_a() -> Structure:
    """``graphene_monolayer`` with its lattice vectors permuted cyclically:
    the vacuum vector a = (0, 0, 20) A comes first, and b and c span the
    sheet in the xy plane."""
    return Structure(
        Lattice([[0, 0, 20.0], [2.46, 0, 0], [-1.23, 1.23 * math.sqrt(3), 0]]),
        ["C", "C"],
        [[0.5, 0, 0], [0.5, 1 / 3, 2 / 3]],
    )


def carbon_chain() -> Structure:
    """A carbon chain along c (C-C 1.28 A) with 12 A between chains along a
    and b: a wire, periodic along c."""
    return Structure(
        Lattice.tetragonal(12.0, 2.56), ["C", "C"], [[0.5, 0.5, 0], [0.5, 0.5, 0.5]]
    )


def carbon_dioxide() -> Structure:
    """Dry ice, Pa-3, a = 5.62 A: C=O 1.15 A inside each molecule, 3.1 A
    between molecules."""
    return Structure.from_spacegroup(
        "Pa-3",
        Lattice.cubic(5.62),
        ["C", "O"],
        [[0, 0, 0], [0.1185, 0.1185, 0.1185]],
    )


_MC3D_4573_WATER_ICE_CIF = """\
data_0

loop_
  _atom_site_label
  _atom_site_fract_x
  _atom_site_fract_y
  _atom_site_fract_z
  _atom_site_type_symbol
         H1  0.16030715231323672  0.8396928476867637  0.24999999999239195  H
         H2  0.8396928476867634  0.16030715231323656  0.7499999999923843  H
         H3  0.005979649911938667  0.00597964991193467  9.715845373787842e-35  H
         H4  0.9940203500646564  0.9940203500646564  0.5000000000000077  H
         H5  0.9674206607569137  0.42584589732319206  0.9837891779390359  H
         H6  0.5741541026767801  0.03257933924305845  0.5162108220609611  H
         H7  0.032579339228914254  0.5741541026909709  0.4837891779390389  H
         H8  0.4258458973090057  0.9674206607710624  0.01621082206096412  H
         O1  0.1612316690525443  0.8410138827825016  0.06589485616831037  O
         O2  0.1589861172174753  0.8387683309474325  0.43410514383168813  O
         O3  0.8387683309332875  0.158986117231637  0.5658948561683119  O
         O4  0.8410138827683481  0.16123166906669772  0.9341051438316957  O
_cell_angle_alpha                       90.0
_cell_angle_beta                        90.0
_cell_angle_gamma                       117.95814914432724
_cell_length_a                          4.126434642797939
_cell_length_b                          4.126434642797939
_cell_length_c                          6.5883867784937
loop_
  _symmetry_equiv_pos_as_xyz
         'x, y, z'
_symmetry_int_tables_number             1
_symmetry_space_group_name_H-M          'P 1'
"""


def water_ice() -> Structure:
    """H2O ice, MC3D mc3d-4573: 4 hydrogen-bonded molecules in a 12-atom
    cell (shortest O-O 2.43 A), so no atom-free slab is wider than 1.21 A."""
    return Structure.from_str(_MC3D_4573_WATER_ICE_CIF, fmt="cif")


_MC3D_67775_SILICON_CIF = """\
data_0

loop_
  _atom_site_label
  _atom_site_fract_x
  _atom_site_fract_y
  _atom_site_fract_z
  _atom_site_type_symbol
         Si1  0.6666666666716649  0.3333333333433297  0.06292314380102376  Si
         Si2  0.33333333332833526  0.6666666666566704  0.5629231437931663  Si
         Si3  0.6666666666716649  0.3333333333433297  0.4370768562068337  Si
         Si4  0.33333333332833526  0.6666666666566704  0.9370768561989763  Si
_cell_angle_alpha                       90.0
_cell_angle_beta                        90.0
_cell_angle_gamma                       120.00000000021976
_cell_length_a                          3.8504103266
_cell_length_b                          3.85041032657442
_cell_length_c                          6.3634082249
loop_
  _symmetry_equiv_pos_as_xyz
         'x, y, z'
_symmetry_int_tables_number             1
_symmetry_space_group_name_H-M          'P 1'
"""


def mc3d_67775_silicon() -> Structure:
    """Hexagonal Si, MC3D 67775, as goldilocks-data's SCF campaign ran it.
    Its a and b differ in the last few bits of the cell file
    (3.8504103266 against 3.85041032657442)."""
    return Structure.from_str(_MC3D_67775_SILICON_CIF, fmt="cif")


_MC3D_42058_SILICON_CIF = """\
data_0

loop_
  _atom_site_label
  _atom_site_fract_x
  _atom_site_fract_y
  _atom_site_fract_z
  _atom_site_type_symbol
         Si1       0.5       0.5       0.5       Si
         Si2       0.7500000000092051  0.7500000000092051  0.7500000000092051  Si
_cell_angle_alpha                       59.99999999999999
_cell_angle_beta                        59.99999999999999
_cell_angle_gamma                       59.99999999999999
_cell_length_a                          3.8408466174999094
_cell_length_b                          3.8408466174999094
_cell_length_c                          3.8408466174999094
loop_
  _symmetry_equiv_pos_as_xyz
         'x, y, z'
_symmetry_int_tables_number             1
_symmetry_space_group_name_H-M          'P 1'
"""


def mc3d_42058_silicon() -> Structure:
    """Diamond Si, MC3D mc3d-42058: the 2-atom fcc primitive cell, which
    pymatgen writes with c along z and a in the xz plane. pw.x 7.5 found 4
    of its 48 symmetry operations in that frame and ran 282 k-points of a
    10x10x10 mesh (#140)."""
    return Structure.from_str(_MC3D_42058_SILICON_CIF, fmt="cif")


_MP_44_ALPHA_URANIUM_CIF = """\
data_U
_symmetry_space_group_name_H-M   'P 1'
_cell_length_a   2.77075206
_cell_length_b   3.23613745
_cell_length_c   4.85010636
_cell_angle_alpha   90.00000000
_cell_angle_beta   90.00000000
_cell_angle_gamma   115.34673871
_symmetry_Int_Tables_number   1
loop_
 _symmetry_equiv_pos_site_id
 _symmetry_equiv_pos_as_xyz
  1  'x, y, z'
loop_
 _atom_site_type_symbol
 _atom_site_label
 _atom_site_symmetry_multiplicity
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
  U  U0  1  0.09626689  0.19253377  0.75000000  1
  U  U1  1  0.90373311  0.80746523  0.25000000  1
"""


def alpha_uranium() -> Structure:
    """alpha-U (Cmcm), Materials Project mp-44, as MP serves it: the reduced
    primitive cell of the base-centred lattice, 2 atoms, gamma 115.35 deg.
    Its point group mixes a and b, whose reciprocal lengths differ (2.509
    against 2.148 A^-1)."""
    return Structure.from_str(_MP_44_ALPHA_URANIUM_CIF, fmt="cif")


_MP_1865_URANIUM_NITRIDE_CIF = """\
data_UN
_symmetry_space_group_name_H-M   'P 1'
_cell_length_a   3.44882753
_cell_length_b   3.44882701
_cell_length_c   3.44882695
_cell_angle_alpha   60.00001067
_cell_angle_beta   60.00001562
_cell_angle_gamma   60.00000542
_symmetry_Int_Tables_number   1
loop_
 _symmetry_equiv_pos_site_id
 _symmetry_equiv_pos_as_xyz
  1  'x, y, z'
loop_
 _atom_site_type_symbol
 _atom_site_label
 _atom_site_symmetry_multiplicity
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
  U  U0  1  0.50000000  0.50000000  0.50000000  1
  N  N1  1  0.00000000  0.00000000  0.00000000  1
"""


def rock_salt(
    cation: str, anion: str, a: float, *, primitive: bool = True
) -> Structure:
    """``cation`` and ``anion`` on rock salt (Fm-3m, lattice constant ``a`` in
    A), in the 2-atom primitive cell or, with ``primitive=False``, the 8-atom
    conventional one."""
    cell = Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(a), [cation, anion], [[0, 0, 0], [0.5, 0.5, 0.5]]
    )
    return cell.get_primitive_structure() if primitive else cell


def uranium_nitride() -> Structure:
    """UN (rock salt, Fm-3m), Materials Project mp-1865, as MP serves it:
    the fcc primitive cell, whose three reciprocal lengths, equal by
    symmetry, differ in the seventh significant figure from CIF noise
    (up to 4.5e-7 A^-1)."""
    return Structure.from_str(_MP_1865_URANIUM_NITRIDE_CIF, fmt="cif")


def hcp_gadolinium() -> Structure:
    """hcp Gd (P6_3/mmc), Materials Project mp-155: 2 atoms, a = 3.642 A,
    c = 5.902 A."""
    return Structure.from_spacegroup(
        "P6_3/mmc", Lattice.hexagonal(3.642, 5.902), ["Gd"], [[1 / 3, 2 / 3, 0.25]]
    )


def fcc_lead() -> Structure:
    """fcc Pb (Fm-3m), MC3D mc3d-48868, in its 4-atom conventional cell
    (a = 4.919 A)."""
    return Structure.from_spacegroup(
        "Fm-3m", Lattice.cubic(4.919), ["Pb"], [[0.0, 0.0, 0.0]]
    )


def fcc_copper() -> Structure:
    """fcc Cu (Fm-3m, a = 3.61 A) in its 4-atom conventional cell."""
    return Structure.from_spacegroup("Fm-3m", Lattice.cubic(3.61), ["Cu"], [[0, 0, 0]])


QE_BOHR_ANGSTROM = 0.529177210903
"""QE 7.3's bohr radius in A (``Modules/constants.f90``), which converts
celldm(1) of QE's example inputs."""


def qe_fcc_lattice(celldm: float) -> Lattice:
    """QE's ibrav = 2 lattice for celldm(1) in bohr."""
    half = celldm * QE_BOHR_ANGSTROM / 2
    return Lattice([[-half, 0, half], [0, half, half], [-half, half, 0]])


def aluminium_arsenide() -> Structure:
    """QE 7.3 PHonon example02's zincblende AlAs: ibrav = 2, celldm(1)
    10.50, Al at the origin and As at (1/4, 1/4, 1/4) alat."""
    quarter = 10.50 * QE_BOHR_ANGSTROM / 4
    return Structure(
        qe_fcc_lattice(10.50),
        ["Al", "As"],
        [[0, 0, 0], [quarter, quarter, quarter]],
        coords_are_cartesian=True,
    )


def rutile_titanium_dioxide() -> Structure:
    """Rutile TiO2 (P4_2/mnm, a = 4.594 A, c = 2.959 A, O at u = 0.3053)."""
    return Structure.from_spacegroup(
        "P4_2/mnm",
        Lattice.tetragonal(4.594, 2.959),
        ["Ti", "O"],
        [[0, 0, 0], [0.3053, 0.3053, 0]],
    )


def wurtzite_zinc_oxide() -> Structure:
    """Wurtzite ZnO (P6_3mc, a = 3.250 A, c = 5.207 A, u = 0.382): an
    insulator that the installed metallicity classifier calls a metal."""
    return Structure.from_spacegroup(
        "P6_3mc",
        Lattice.hexagonal(3.250, 5.207),
        ["Zn", "O"],
        [[1 / 3, 2 / 3, 0], [1 / 3, 2 / 3, 0.382]],
    )


def generated_slab(bulk: Structure, miller: tuple[int, int, int]) -> Slab:
    """pymatgen's ``SlabGenerator`` slab of ``bulk`` with Miller index
    ``miller``, at least 6 A thick under 12 A of vacuum along c, centred in
    the cell. SlabGenerator keeps c along a bulk lattice vector, so c is
    usually tilted off the slab normal; ``Slab.get_orthogonal_c_slab`` gives
    the same slab with c along the normal."""
    return SlabGenerator(
        bulk, miller, min_slab_size=6, min_vacuum_size=12, center_slab=True
    ).get_slab()


def rutile_ruthenium_dioxide() -> Structure:
    """Rutile RuO2 (P4_2/mnm, a = 4.49 A, c = 3.11 A, O at u = 0.306) with
    its two Ru sites labelled Ru1 and Ru2, the sublattices its
    antiferromagnetic order sets apart."""
    u = 0.306
    return Structure(
        Lattice.tetragonal(4.49, 3.11),
        ["Ru", "Ru", "O", "O", "O", "O"],
        [
            [0, 0, 0],
            [0.5, 0.5, 0.5],
            [u, u, 0],
            [-u, -u, 0],
            [0.5 + u, 0.5 - u, 0.5],
            [0.5 - u, 0.5 + u, 0.5],
        ],
        labels=["Ru1", "Ru2", "O", "O", "O", "O"],
    )


def antiferromagnetic_nickel_oxide() -> Structure:
    """NiO's AFM-II order on rock salt (a = 4.17 A): ferromagnetic (111) Ni
    planes alternating between Ni1 and Ni2, in the 4-atom rhombohedral cell
    a (1/2, 1/2, 1), a (1/2, 1, 1/2), a (1, 1/2, 1/2) (rhombohedral angle
    33.56 degrees)."""
    a = 4.17
    return Structure(
        Lattice(a * np.array([[0.5, 0.5, 1.0], [0.5, 1.0, 0.5], [1.0, 0.5, 0.5]])),
        ["Ni", "Ni", "O", "O"],
        a * np.array([[0, 0, 0], [0, 0.5, 0.5], [0.5, 0, 0], [0.5, 0.5, 0.5]]),
        coords_are_cartesian=True,
        labels=["Ni1", "Ni2", "O", "O"],
    )


def ilmenite() -> Structure:
    """FeTiO3 ilmenite (R-3, hexagonal a = 5.088 A, c = 14.085 A) in its
    10-atom rhombohedral primitive cell, rhombohedral angle 54.7 degrees."""
    return Structure.from_spacegroup(
        "R-3",
        Lattice.hexagonal(5.088, 14.085),
        ["Fe", "Ti", "O"],
        [[0, 0, 0.3554], [0, 0, 0.1464], [0.317, 0.020, 0.245]],
    ).get_primitive_structure()


def flattened_rhombohedral_silicon() -> Structure:
    """Six Si atoms on a general position of R-3 in a flattened rhombohedral
    cell (hexagonal a = 7 A, c = 5 A, rhombohedral angle above 90 degrees),
    Si-Si 2.01 A and up."""
    return Structure.from_spacegroup(
        "R-3", Lattice.hexagonal(7.0, 5.0), ["Si"], [[0.13, 0.31, 0.07]]
    ).get_primitive_structure()


def _zirconia_sites_on(lattice: Lattice) -> Structure:
    """The 12 sites of monoclinic ZrO2 (P2_1/c, a = 5.15, b = 5.21,
    c = 5.31 A, beta = 99.23 degrees), in fractional coordinates, on
    ``lattice``."""
    zirconia = Structure.from_spacegroup(
        "P2_1/c",
        Lattice.monoclinic(5.15, 5.21, 5.31, 99.23),
        ["Zr", "O", "O"],
        [[0.2754, 0.0395, 0.2083], [0.0700, 0.3317, 0.3447], [0.4496, 0.7569, 0.4792]],
    )
    return Structure(lattice, zirconia.species, zirconia.frac_coords)


def right_angled_monoclinic_zirconia() -> Structure:
    """The sites of monoclinic ZrO2 (P2_1/c) on a lattice whose angles are
    all exactly 90 degrees (a = 5.15, b = 5.21, c = 5.31 A): monoclinic
    symmetry on an orthorhombic metric."""
    return _zirconia_sites_on(Lattice.orthorhombic(5.15, 5.21, 5.31))


def monoclinic_zirconia_on_a_rhombic_lattice() -> Structure:
    """The sites of monoclinic ZrO2 (P2_1/c) on a lattice with a = c =
    5.20 A, b = 5.21 A and beta = 99.23 degrees: monoclinic symmetry on a
    C-centred orthorhombic metric, the two lattice vectors normal to the
    unique axis b equal in length."""
    return _zirconia_sites_on(Lattice.monoclinic(5.20, 5.21, 5.20, 99.23))


def monoclinic_zirconia_on_a_hexagonal_lattice() -> Structure:
    """The sites of monoclinic ZrO2 (P2_1/c) on a lattice with a = c =
    6.00 A at beta = 120 degrees and b = 5.21 A: monoclinic symmetry on a
    hexagonal metric, Zr-O 2.01 A and up."""
    return _zirconia_sites_on(Lattice.monoclinic(6.00, 5.21, 6.00, 120))


def sulfur_substituted_monoclinic_zirconia() -> Structure:
    """Monoclinic ZrO2 (P2_1/c, a = 5.15, b = 5.21, c = 5.31 A, beta = 99.23
    degrees) with one of its eight O replaced by S: a P1 defect cell on a
    monoclinic lattice, with reciprocal angles of 90, about 81 and 90
    degrees."""
    zirconia = _zirconia_sites_on(Lattice.monoclinic(5.15, 5.21, 5.31, 99.23))
    zirconia.replace(zirconia.indices_from_symbol("O")[0], "S")
    return zirconia


def sulfur_substituted_right_angled_zirconia() -> Structure:
    """``right_angled_monoclinic_zirconia`` with one of its eight O replaced
    by S: a P1 defect cell on an orthorhombic metric, every reciprocal
    angle 90 degrees."""
    zirconia = right_angled_monoclinic_zirconia()
    zirconia.replace(zirconia.indices_from_symbol("O")[0], "S")
    return zirconia


def sheared_sulfur_substituted_zirconia() -> Structure:
    """``sulfur_substituted_monoclinic_zirconia``'s sites on a 5.15 x 5.21 x
    5.31 A lattice with angles of 94, 99 and 103 degrees: a P1 cell whose
    standard primitive cell has reciprocal angles of about 84, 80 and 76
    degrees, all acute (Setyawan and Curtarolo's TRI1b)."""
    zirconia = sulfur_substituted_monoclinic_zirconia()
    return Structure(
        Lattice.from_parameters(5.15, 5.21, 5.31, 94, 99, 103),
        zirconia.species,
        zirconia.frac_coords,
    )


def displaced_hcp_gadolinium() -> Structure:
    """``hcp_gadolinium`` with its second atom moved (0.11, 0.07, 0.05) A
    off its site: P-1 on a hexagonal metric, with reciprocal angles of 90,
    90 and 60 degrees."""
    gadolinium = hcp_gadolinium()
    gadolinium.translate_sites([1], [0.11, 0.07, 0.05], frac_coords=False)
    return gadolinium


def layered_antiferromagnetic_nickel() -> Structure:
    """fcc Ni (a = 3.52 A) with the AFM-I order of CuAu-type layering --
    (100) planes alternating between Ni1 and Ni2, so the layering runs along
    a -- in its 4-atom cubic cell: a tetragonal crystal on a cubic
    lattice."""
    return Structure(
        Lattice.cubic(3.52),
        ["Ni"] * 4,
        [[0, 0, 0], [0, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
        labels=["Ni1", "Ni1", "Ni2", "Ni2"],
    )


def graphene_with_a_60_degree_cell() -> Structure:
    """``graphene_monolayer`` with b at 60 degrees from a instead of 120."""
    return Structure(
        Lattice([[2.46, 0, 0], [1.23, 1.23 * math.sqrt(3), 0], [0, 0, 20.0]]),
        ["C", "C"],
        [[1 / 3, 1 / 3, 0.5], [2 / 3, 2 / 3, 0.5]],
    )


def oblique_carbon_sheet(*, obtuse: bool = False) -> Structure:
    """Two C atoms 1.67 A apart in a planar sheet on an oblique lattice,
    a = 3.0 A and b = 3.4 A at 70 degrees, 20 A high along z. ``obtuse``
    gives the same sheet in the basis (b, -a): 3.4 A and 3.0 A at 110
    degrees."""
    if obtuse:
        lattice, second = (
            Lattice.from_parameters(3.4, 3.0, 20.0, 90, 90, 110),
            [0.35, 0.55, 0.5],
        )
    else:
        lattice, second = (
            Lattice.from_parameters(3.0, 3.4, 20.0, 90, 90, 70),
            [0.45, 0.35, 0.5],
        )
    return Structure(lattice, ["C", "C"], [[0, 0, 0.5], second])


def rectangular_graphene() -> Structure:
    """``graphene_monolayer`` (C-C 1.42 A) in its 4-atom rectangular cell,
    a = 2.46 A and b = 2.46 sqrt(3) A, 20 A high along z."""
    return Structure(
        Lattice.orthorhombic(2.46, 2.46 * math.sqrt(3), 20.0),
        ["C"] * 4,
        [[0, 1 / 6, 0.5], [0.5, 1 / 3, 0.5], [0.5, 2 / 3, 0.5], [0, 5 / 6, 0.5]],
    )


def distorted_tungsten_ditelluride_sheet() -> Structure:
    """A 1T'-WTe2-like sheet: W and two Te sites of P2_1/m on a 6.25 x
    3.48 A rectangular lattice, 20 A high along z, whose monoclinic axis b
    lies in the sheet."""
    return Structure.from_spacegroup(
        "P2_1/m",
        Lattice.orthorhombic(6.25, 3.48, 20.0),
        ["W", "Te", "Te"],
        [[0.10, 0.25, 0.010], [0.36, 0.25, 0.085], [0.62, 0.25, -0.080]],
    )


def tilted_straddling_molybdenum_disulfide() -> Structure:
    """The S-Mo-S sheet of ``molybdenum_disulfide_monolayer`` with c leaning
    (1.58, 0.912) A off the normal and Mo on the cell boundary, so that the
    sheet straddles it."""
    lattice = Lattice.hexagonal(3.16, 20.0).matrix
    cartesian = Lattice(lattice).get_cartesian_coords(
        [[1 / 3, 2 / 3, 0], [2 / 3, 1 / 3, 0], [2 / 3, 1 / 3, 0]]
    )
    cartesian[:, 2] = [0.0, 1.585, -1.585]
    return Structure(
        Lattice([lattice[0], lattice[1], [1.58, 0.912, 20.0]]),
        ["Mo", "S", "S"],
        cartesian,
        coords_are_cartesian=True,
        to_unit_cell=True,
    )


def written_alpha_uranium() -> Structure:
    """``alpha_uranium`` as goldilocks writes it by default: ``pw_frame``
    only idealizes it, by 3e-6 A, keeping its orientation and primitive
    basis."""
    return pw_frame(alpha_uranium())[0]


def written_silicon() -> Structure:
    """``mc3d_42058_silicon`` as goldilocks writes it by default: ``pw_frame``
    turns its cubic axes onto x, y and z, where pw.x keeps all 48
    operations."""
    return pw_frame(mc3d_42058_silicon())[0]


def _written(
    lattice: list[list[float]],
    sites: list[tuple[str, float | None, tuple[float, float, float]]],
) -> Structure:
    """A cell as goldilocks writes it (the simulated cell of
    ``records.magnetic``, framed by ``pw_symmetry.pw_frame``), from its
    lattice rows in A and its sites as (element, starting-magnetization
    class or None, fractional coordinates). Each class is a species of its
    own, as ``advisors/species_split.py`` builds them. The cells built
    with it below were taken from goldilocks at the band task's merge
    (8829358) for structures of the 2026-10-19 batch, rounded to 1e-12, so
    that tests need neither the CIF nor the magnetic enumeration."""
    return Structure(
        Lattice(lattice),
        [
            Element(symbol) if spin is None else Species(symbol, spin=spin)
            for symbol, spin, _ in sites
        ],
        [coordinates for _, _, coordinates in sites],
    )


def written_bcc_iron() -> Structure:
    """bcc Fe, MC3D mc3d-17673, written by default: the spin-polarized
    1-atom primitive cell with its cubic axes on x, y and z."""
    return _written(
        [
            [1.394432230543, -1.394432230543, -1.394432230543],
            [-1.394432230543, 1.394432230543, -1.394432230543],
            [1.394432230543, 1.394432230543, 1.394432230543],
        ],
        [("Fe", 1.0, (0.0, 0.0, 0.0))],
    )


def written_sodium_chloride() -> Structure:
    """Rock-salt NaCl, MC3D mc3d-76777, written by default: the 2-atom fcc
    primitive cell with its cubic axes on x, y and z."""
    return _written(
        [
            [2.805213303632, 0.0, 2.805213303632],
            [2.805213303632, 2.805213303632, 0.0],
            [0.0, 2.805213303632, 2.805213303632],
        ],
        [("Na", None, (0.0, 0.0, 0.0)), ("Cl", None, (0.5, 0.5, 0.5))],
    )


def written_gallium_arsenide() -> Structure:
    """Zincblende GaAs, MC3D mc3d-13434, written by default: the 2-atom fcc
    primitive cell with its cubic axes on x, y and z."""
    return _written(
        [
            [2.827626365794, -2.827626365794, 0.0],
            [2.827626365794, 0.0, 2.827626365794],
            [0.0, -2.827626365794, 2.827626365794],
        ],
        [
            ("Ga", None, (0.0, 0.0, 0.0)),
            ("As", None, (0.749999999982, 0.749999999982, 0.750000000018)),
        ],
    )


def written_boron_nitride_monolayer() -> Structure:
    """The hBN monolayer, MC2D mc2d-04b28fdc, written by default: a along x,
    the sheet in the xy plane, 20 A high along c."""
    return _written(
        [
            [2.50930018, 0.0, 0.0],
            [-1.25465009, 2.173117701601, 0.0],
            [0.0, 0.0, 20.0],
        ],
        [
            ("B", None, (0.333333333333, 0.666666666667, 0.5)),
            ("N", None, (0.666666666667, 0.333333333333, 0.5)),
        ],
    )


def written_lanthanum_cuprate() -> Structure:
    """T-La2CuO4 (I4/mmm), Materials Project mp-19735, written by default
    (spin-polarized, one species per element): the 7-atom body-centred
    primitive cell, a = b = 3.81 A on x and y, c = 7.14 A."""
    return _written(
        [
            [3.813804, 0.0, 0.0],
            [0.0, 3.813804, 0.0],
            [-1.906902, -1.906902, 6.612450996404],
        ],
        [
            ("La", 1.0, (0.360893, 0.360893, 0.721786)),
            ("La", 1.0, (0.639107, 0.639107, 0.278214)),
            ("Cu", 1.0, (0.0, 0.0, 0.0)),
            ("O", 1.0, (0.0, 0.5, 0.0)),
            ("O", 1.0, (0.5, 0.0, 0.0)),
            ("O", 1.0, (0.186226, 0.186226, 0.372452)),
            ("O", 1.0, (0.813774, 0.813774, 0.627548)),
        ],
    )


def written_manganese_thiophosphate_monolayer() -> Structure:
    """The MnPS3 monolayer, MC2D mc2d-9ffd1741, written by default
    (spin-polarized, one species per element): idealized to its four
    operations, a = 5.66 A along x and b = 5.82 A at 60.9 degrees from it,
    the sheet in the xy plane."""
    return _written(
        [
            [5.65873239, 0.0, 0.0],
            [2.829366195, 5.088206724238, 0.0],
            [0.0, 0.0, 22.94442368],
        ],
        [
            ("Mn", 1.0, (0.1772961325, 0.645407735, 0.5000002)),
            ("Mn", 1.0, (0.8227038675, 0.354592265, 0.5000002)),
            ("P", 1.0, (0.5023951125, 1.0, 0.45296376)),
            ("P", 1.0, (0.4976048875, 0.0, 0.54703664)),
            ("S", 1.0, (0.8655777775, 1.0, 0.440237235)),
            ("S", 1.0, (0.5046158675, 0.642731645, 0.4358927775)),
            ("S", 1.0, (0.1473475125, 0.357268355, 0.4358927775)),
            ("S", 1.0, (0.1344222225, 0.0, 0.559763165)),
            ("S", 1.0, (0.4953841325, 0.357268355, 0.5641076225)),
            ("S", 1.0, (0.8526524875, 0.642731645, 0.5641076225)),
        ],
    )


def written_alpha_sulfur() -> Structure:
    """alpha-S (Fddd), MC3D mc3d-4618, written by default: the 32-atom
    face-centred primitive cell, a = 13.75, b = 13.25 and c = 8.35 A."""
    return _written(
        [
            [0.0, -6.459813815012, 12.141720392067],
            [-5.296773895398, 0.0, 12.141720392067],
            [-5.296773895398, -6.459813815012, 0.0],
        ],
        [
            ("S", None, (0.671075704951, 0.477743487444, 0.484997022277)),
            ("S", None, (0.765002977723, 0.883816214673, 0.578924295049)),
            ("S", None, (0.484997022277, 0.366183785327, 0.671075704951)),
            ("S", None, (0.883816214673, 0.765002977723, 0.772256512556)),
            ("S", None, (0.366183785327, 0.484997022277, 0.477743487444)),
            ("S", None, (0.772256512556, 0.578924295049, 0.883816214673)),
            ("S", None, (0.477743487444, 0.671075704951, 0.366183785327)),
            ("S", None, (0.578924295049, 0.772256512556, 0.765002977723)),
            ("S", None, (0.900416385977, 0.355071410257, 0.314065185351)),
            ("S", None, (0.935934814649, 0.819552981585, 0.349583614023)),
            ("S", None, (0.314065185351, 0.430447018415, 0.900416385977)),
            ("S", None, (0.819552981577, 0.935934814657, 0.894928589735)),
            ("S", None, (0.430447018415, 0.314065185351, 0.355071410257)),
            ("S", None, (0.894928589735, 0.349583614031, 0.819552981577)),
            ("S", None, (0.355071410257, 0.900416385977, 0.430447018415)),
            ("S", None, (0.349583614023, 0.894928589743, 0.935934814649)),
            ("S", None, (0.949399063091, 0.454280072258, 0.361899618252)),
            ("S", None, (0.888100381748, 0.015578753602, 0.300600936909)),
            ("S", None, (0.361899618252, 0.234421246398, 0.949399063091)),
            ("S", None, (0.015578753585, 0.888100381765, 0.795719927743)),
            ("S", None, (0.234421246398, 0.361899618252, 0.454280072258)),
            ("S", None, (0.795719927734, 0.300600936916, 0.015578753594)),
            ("S", None, (0.454280072258, 0.949399063091, 0.234421246398)),
            ("S", None, (0.300600936899, 0.795719927751, 0.888100381757)),
            ("S", None, (0.877347444399, 0.634241249704, 0.188568769379)),
            ("S", None, (0.061431230621, 0.950157463483, 0.372652555601)),
            ("S", None, (0.188568769379, 0.299842536517, 0.877347444399)),
            ("S", None, (0.950157463483, 0.061431230621, 0.615758750296)),
            ("S", None, (0.299842536517, 0.188568769379, 0.634241249704)),
            ("S", None, (0.615758750296, 0.372652555601, 0.950157463483)),
            ("S", None, (0.634241249704, 0.877347444399, 0.299842536517)),
            ("S", None, (0.372652555601, 0.615758750296, 0.061431230621)),
        ],
    )


def written_afm_nickel_oxide() -> Structure:
    """Rock-salt NiO, MC3D mc3d-29856, written with magnetic_ordering=afm:
    4 atoms, the two Ni with opposite moments, a = c = 2.89 A and
    b = 5.01 A."""
    return _written(
        [
            [-1.446684388624, 2.505730863613, 0.0],
            [-1.446684388624, 0.835243621204, 4.724851427971],
            [1.446684388624, 2.505730863613, 0.0],
        ],
        [
            ("Ni", 1.0, (0.0, 0.0, 0.0)),
            ("Ni", -1.0, (0.0, 0.5, 0.5)),
            ("O", 0.0, (0.5, 0.25, 0.75)),
            ("O", 0.0, (0.5, 0.75, 0.25)),
        ],
    )


def written_afm_manganese_oxide() -> Structure:
    """Rock-salt MnO, MC3D mc3d-14218, written with magnetic_ordering=afm:
    4 atoms, the two Mn with opposite moments, a = b = 3.07 A and
    c = 5.31 A."""
    return _written(
        [
            [1.53373905321, 2.656513965712, 0.0],
            [-3.06747810642, 0.0, 0.0],
            [1.53373905321, 0.885504655237, 5.009170771924],
        ],
        [
            ("Mn", 1.0, (0.0, 0.0, 0.0)),
            ("Mn", -1.0, (0.5, 0.5, 0.5)),
            ("O", 0.0, (0.25, 0.75, 0.25)),
            ("O", 0.0, (0.75, 0.25, 0.75)),
        ],
    )


def written_afm_nickel() -> Structure:
    """fcc Ni, MC3D mc3d-4988, written with magnetic_ordering=afm: 2 atoms
    with opposite moments, a = c = 2.45 A and b = 4.24 A."""
    return _written(
        [
            [-1.224045949109, 2.120109774656, 0.0],
            [0.0, -1.413406516437, 3.997717329384],
            [1.224045949109, 2.120109774656, 0.0],
        ],
        [("Ni", 1.0, (0.0, 0.0, 0.0)), ("Ni", -1.0, (0.5, 0.5, 0.5))],
    )


def written_afm_hematite() -> Structure:
    """Corundum Fe2O3, MC3D mc3d-44692, written with magnetic_ordering=afm:
    10 atoms, two Fe with each moment, a = c = 4.70 A and b = 5.18 A."""
    return _written(
        [
            [-2.3513156913, 4.072598241965, 0.0],
            [2.3513156913, 1.357532747322, 4.414390845306],
            [2.3513156913, 4.072598241965, 0.0],
        ],
        [
            ("Fe", 1.0, (0.345305649413, 0.035916948239, 0.309388701174)),
            ("Fe", 1.0, (0.845305649413, 0.535916948239, 0.309388701174)),
            ("Fe", -1.0, (0.154694350579, 0.464083051738, 0.690611298841)),
            ("Fe", -1.0, (0.654694350579, 0.964083051738, 0.690611298841)),
            ("O", 0.0, (0.935872550565, 0.749999999989, 0.814127449439)),
            ("O", 0.0, (0.750000000003, 0.250000000011, 0.814127449423)),
            ("O", 0.0, (0.564127449427, 0.749999999989, 0.500000000007)),
            ("O", 0.0, (0.064127449414, 0.250000000011, 0.185872550582)),
            ("O", 0.0, (0.250000000009, 0.749999999989, 0.185872550589)),
            ("O", 0.0, (0.435872550573, 0.250000000011, 0.499999999993)),
        ],
    )


def written_afm_uranium_dioxide() -> Structure:
    """Fluorite UO2, Materials Project mp-1597, written with
    magnetic_ordering=afm: 6 atoms, the two U with opposite moments,
    a = c = 3.86 A and b = 6.68 A."""
    return _written(
        [
            [-1.92828374, 3.339885409089, 0.0],
            [0.0, -2.226590272726, 6.297748323074],
            [3.85656748, 0.0, 0.0],
        ],
        [
            ("U", -1.0, (0.5, 0.75, 0.25)),
            ("U", 1.0, (0.5, 0.25, 0.75)),
            ("O", 0.0, (0.75, 0.625, 0.875)),
            ("O", 0.0, (0.75, 0.125, 0.375)),
            ("O", 0.0, (0.25, 0.875, 0.625)),
            ("O", 0.0, (0.25, 0.375, 0.125)),
        ],
    )


def written_magnetic_cell(structure: Structure) -> Resolved[MagneticCell]:
    """``structure``, a cell as goldilocks writes it (``_written``), as the
    resolved simulated cell of a collinear run in its own basis, for
    advisors that read the written cell: spin-polarized when its species
    carry starting-magnetization classes, with the ordering
    ``magnetic_ordering=afm`` applies when some class is negative, as in the
    antiferromagnetic cells above, otherwise the input kept."""
    spins = [getattr(site.specie, "spin", None) for site in structure]
    spin_polarized = any(spin is not None for spin in spins)
    if any(spin is not None and spin < 0 for spin in spins):
        ordering = OrderingRecord(
            requested="afm", applied="afm-1", criterion="smallest_cell"
        )
    else:
        ordering = OrderingRecord(
            requested=None, applied="fm" if spin_polarized else None
        )
    cell = MagneticCell(
        structure=structure,
        spin_polarized=spin_polarized,
        spin_orbit_enabled=False,
        magnetic_elements=(),
        ordering=ordering,
        cell_in_input_basis=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        tot_magnetization=None,
    )
    return Resolved(cell, Provenance(source="heuristic"))


ISOTROPIC_STRAINS = (-0.03, -0.02, -0.01, -0.005, 0.005, 0.01, 0.02, 0.03)
"""The isotropic strains ``symmetric_strains`` starts with."""
_RANDOM_STRAIN_SIZES = (0.01, 0.02, 0.03)
_RANDOM_STRAINS_PER_SIZE = 8


def symmetric_strains(structure: Structure, rotations: PwRotations) -> list[np.ndarray]:
    """Cartesian strain tensors that keep every operation in ``rotations``,
    as a vc-relax does: isotropic ones of +-0.5, 1, 2 and 3%, and eight
    random ones each of 1, 2 and 3% (seeded), averaged over the operations
    so that each maps the strained lattice onto itself. A slab, written with
    its vacuum along c and its plane in xy, is strained in its plane only,
    as cell_dofree='2Dxy' relaxes it."""
    lattice = structure.lattice.matrix
    cartesian = [lattice.T @ w @ np.linalg.inv(lattice.T) for w in rotations.rotations]
    plane = np.diag([1.0, 1.0, 0.0]) if vacuum_axes(structure) == ("c",) else np.eye(3)
    strains = [size * plane for size in ISOTROPIC_STRAINS]
    generator = np.random.default_rng(215)
    for size in _RANDOM_STRAIN_SIZES:
        for _ in range(_RANDOM_STRAINS_PER_SIZE):
            raw = generator.uniform(-1.0, 1.0, (3, 3))
            raw = plane @ (raw + raw.T) @ plane
            averaged = sum(r @ raw @ r.T for r in cartesian) / len(cartesian)
            strains.append(averaged * size / np.abs(np.linalg.eigvalsh(averaged)).max())
    return strains


def strained(structure: Structure, strain: np.ndarray) -> Structure:
    """``structure`` with every lattice vector a turned into (1 + strain) a,
    its fractional coordinates kept."""
    return Structure(
        structure.lattice.matrix @ (np.eye(3) + strain).T,
        structure.species,
        structure.frac_coords,
    )


def points_along_lines(
    vertices: Sequence[np.ndarray], counts: Sequence[int]
) -> tuple[np.ndarray, np.ndarray]:
    """The points QE 7.3's ``generate_k_along_lines`` makes of ``vertices``
    and their ``counts``, in its operation order
    (``Modules/generate_k_along_lines.f90:26-50``): a count n > 0 puts the n
    points x + (delta * j) * (y - x), delta = 1.0 / n and j = 1..n, after
    vertex x on the way to the next vertex y, and 0 jumps straight to y; the
    last count is not used. Also returns, for each pair of consecutive
    points, whether it is such a jump. The coordinates are taken as given:
    pw.x expands a K_POINTS crystal_b card in crystal coordinates, matdyn.x
    its rows after converting them to Cartesian ones."""
    points, jumps = [vertices[0]], []
    for start, end, count in zip(vertices, vertices[1:], counts, strict=False):
        if count == 0:
            points.append(end)
            jumps.append(True)
            continue
        delta = 1.0 / count
        points.extend(start + (delta * j) * (end - start) for j in range(1, count + 1))
        jumps.extend([False] * count)
    return np.array(points), np.array(jumps)


def geometry_facts(
    dimensionality: Dimensionality,
    vacuum_axes: tuple[LatticeAxis, ...] = (),
    *,
    ab_in_xy: bool = True,
) -> GeometryFacts:
    """``GeometryFacts`` for advisor and check tests: 20 A of vacuum along
    each axis in ``vacuum_axes`` and a 2 A gap along the others. With one
    vacuum axis the cell is a slab, in the xy frame when that axis is c and
    ``ab_in_xy``, with c along z, room for QE's 2D Coulomb truncation in that
    frame, and its vacuum centred on the cell origin, filling 80% of the
    cell."""
    slab = None
    if len(vacuum_axes) == 1:
        (axis,) = vacuum_axes
        xy_frame = axis == "c" and ab_in_xy
        slab = SlabGeometry(
            vacuum_axis=axis,
            xy_frame=xy_frame,
            fits_2d_truncation=xy_frame,
            vacuum_center=0.0,
            vacuum_fraction=0.8,
        )
    return GeometryFacts(
        dimensionality=dimensionality,
        low_dimensional=dimensionality != "3d",
        vacuum_axes=vacuum_axes,
        vacuum_widths_angstrom=tuple(
            20.0 if axis in vacuum_axes else 2.0 for axis in ("a", "b", "c")
        ),
        slab=slab,
    )


def written_cell(structure: Structure) -> Resolved[MagneticConfigFacts]:
    """A resolved non-magnetic ``MagneticConfigFacts`` whose ``cell`` is
    ``structure``: the cell the writer renders, which the written-cell rules
    of ``checks.check_all`` read."""
    facts = MagneticConfigFacts(
        cell=structure,
        ordering=OrderingRecord(requested=None, applied=None),
        spin_polarized=False,
        magnetic_elements=(),
        starting_magnetization=None,
        compensated=False,
        tot_magnetization=None,
        spin_orbit_enabled=False,
        angle1=None,
        angle2=None,
    )
    return Resolved(facts, Provenance(source="heuristic"))
