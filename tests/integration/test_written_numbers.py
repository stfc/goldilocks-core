"""Published bundles write decimals, not float artefacts (#178).

``advise``/``check``/``generate``/``publish`` end to end on a synthetic
SSSP-shaped table, so it runs in CI. The nat-scaled thresholds are the
decimals their formulas name, in ``goldilocks.json`` and in the input alike,
and no number in a ``pw.x`` input has more significant digits than its
writer formats (12 in a namelist, 10 in a card, a band path's vertices
included), lies between 0 and 1e-10 in magnitude, or reads ``-0``.

On these cells ``pw_symmetry.pw_frame`` has already set every near-zero
lattice component and coordinate to 0, so the writer's own card snap below
1e-10 is not reached here; tests/unit/test_generation_quantum_espresso_scf.py
pins it on the writer directly.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from pymatgen.core import Structure
from support import (
    carbon_dioxide,
    in_memory_source,
    sssp_fixture_table_spec,
    strict_json,
)

from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.bundle import DirectoryOutput, publish
from goldilocks_core.inputs.hpc import load_hpc_profile
from goldilocks_core.service import (
    advise,
    advise_band,
    advise_relax,
    check,
    check_band,
    check_relax,
    generate,
    generate_band,
    generate_relax,
    render_submission,
    render_submission_band,
    render_submission_relax,
    to_bundle_input,
    to_bundle_input_band,
    to_bundle_input_relax,
)
from goldilocks_core.steps import default_shared_context

pytestmark = pytest.mark.integration

_MC3D_65529_SPINEL_CIF = """\
data_0

loop_
  _atom_site_label
  _atom_site_fract_x
  _atom_site_fract_y
  _atom_site_fract_z
  _atom_site_type_symbol
         Mg1  0.7499999999938363  0.7499999999938363  0.7499999999938363  Mg
         Mg2  0.5  0.5  0.5  Mg
         Al1  0.12499999999691201  0.12499999999691201  0.12499999999691201  Al
         Al2  0.12499999999691196  0.6249999999845848  0.12499999999691207  Al
         Al3  0.624999999996912  0.12499999998458478  0.1250000000092639  Al
         Al4  0.12499999999691196  0.12499999999691196  0.6249999999845848  Al
         O1  0.8885670162910045  0.8885670162910045  0.8885670162910045  O
         O2  0.36143298370283183  0.9157010488915293  0.3614329837028318  O
         O3  0.8885670162910044  0.33429895112699615  0.8885670162910047  O
         O4  0.33429895112699615  0.8885670162910044  0.8885670162910047  O
         O5  0.9157010488915293  0.3614329837028316  0.3614329837028318  O
         O6  0.3614329837028318  0.3614329837028316  0.36143298370283183  O
         O7  0.3614329837028318  0.3614329837028316  0.9157010488915293  O
         O8  0.8885670162910045  0.8885670162910045  0.33429895112699626  O
_cell_angle_alpha                       60.00000000000001
_cell_angle_beta                        60.00000000000001
_cell_angle_gamma                       60.00000000000001
_cell_length_a                          5.736097243231706
_cell_length_b                          5.736097243231706
_cell_length_c                          5.736097243231706
loop_
  _symmetry_equiv_pos_as_xyz
         'x, y, z'
_symmetry_int_tables_number             1
_symmetry_space_group_name_H-M          'P 1'
"""

_NUMBER = re.compile(r"(?<![\w.()-])-?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?(?![\w.])")
"""A number standing alone in an input line: not the digit of a label
(``Fe1``), a manifold (``Fe-3d``) or an index (``angle1(2)``)."""


@pytest.fixture
def store(tmp_path, monkeypatch) -> AssetStore:
    spec, registry_table = sssp_fixture_table_spec(
        tmp_path / "sources", {"Al": 3.0, "C": 4.0, "Mg": 10.0, "O": 6.0}
    )
    monkeypatch.setattr(
        "goldilocks_core.service._pseudo.load_tables",
        lambda *_args, **_kwargs: {registry_table.id: registry_table},
    )
    store = AssetStore(tmp_path / "store")
    store.install(spec, sssp_preparer(registry_table))
    return store


def _assert_written_as_decimals(text: str) -> None:
    namelists, cards = text.split("ATOMIC_SPECIES", 1)
    for part, digits in ((namelists, 12), (cards, 10)):
        for token in _NUMBER.findall(part):
            value = Decimal(token)
            assert len(value.normalize().as_tuple().digits) <= digits, token
            assert value == 0 or abs(value) >= Decimal("1e-10"), token
            assert not (value == 0 and token.startswith("-")), token


def test_a_spinel_scf_bundle_writes_conv_thr_as_its_decimal(store, tmp_path) -> None:
    """MgAl2O4, MC3D mc3d-65529, nat 14: the float product 14 * 0.2e-9 is
    2.8000000000000003e-09, which goldilocks.json recorded and scf.in
    printed. The fcc cell is written turned into its standard orientation;
    ``pw_frame`` sets the residues the turn leaves where its lattice vectors
    have a zero to 0."""
    hpc = load_hpc_profile("scarf")
    spinel = Structure.from_str(_MC3D_65529_SPINEL_CIF, fmt="cif")
    advice = advise(spinel, hpc=hpc, store=store)
    steps = generate(advice, check(advice))
    script = render_submission(advice, hpc, "quantum_espresso", steps)
    bundle = to_bundle_input(
        advice,
        steps,
        script,
        default_shared_context(),
        code="quantum_espresso",
        hpc=hpc,
        assignments={},
        source=in_memory_source(spinel),
    )
    publish(bundle, DirectoryOutput(tmp_path / "bundle"))

    text = (tmp_path / "bundle" / "scf.in").read_text()
    records = strict_json((tmp_path / "bundle" / "goldilocks.json").read_text())[
        "records"
    ]
    assert "   conv_thr         = 2.8e-09" in text.splitlines()
    assert records["convergence"]["value"]["conv_thr"] == 2.8e-09
    _assert_written_as_decimals(text)


def test_a_dry_ice_vc_relax_bundle_writes_etot_conv_thr_as_its_decimal(
    store, tmp_path
) -> None:
    """CO2 dry ice, nat 12: the float product 12 * 1e-5 is
    0.00012000000000000002, which both records and vc-relax.in carried."""
    hpc = load_hpc_profile("scarf")
    dry_ice = carbon_dioxide()
    advice = advise_relax(dry_ice, calculation="vc-relax", hpc=hpc, store=store)
    steps = generate_relax(advice, check_relax(advice))
    script = render_submission_relax(advice, hpc, "quantum_espresso", steps)
    bundle = to_bundle_input_relax(
        advice,
        steps,
        script,
        default_shared_context(),
        code="quantum_espresso",
        hpc=hpc,
        assignments={},
        source=in_memory_source(dry_ice),
    )
    publish(bundle, DirectoryOutput(tmp_path / "bundle"))

    text = (tmp_path / "bundle" / "vc-relax.in").read_text()
    records = strict_json((tmp_path / "bundle" / "goldilocks.json").read_text())[
        "records"
    ]
    assert "   etot_conv_thr    = 0.00012" in text.splitlines()
    assert records["convergence"]["value"]["etot_conv_thr"] == 0.00012
    assert records["relax"]["value"]["etot_conv_thr"] == 0.00012
    _assert_written_as_decimals(text)


def test_a_spinel_band_bundle_writes_both_pw_x_inputs_as_decimals(
    store, tmp_path
) -> None:
    """#118: bands.in is written with scf.in's helpers, its own conv_thr the
    same nat-scaled decimal, and its K_POINTS crystal_b vertices, fractions
    of the turned fcc cell's reciprocal vectors, are card numbers too."""
    hpc = load_hpc_profile("scarf")
    spinel = Structure.from_str(_MC3D_65529_SPINEL_CIF, fmt="cif")
    advice = advise_band(spinel, hpc=hpc, store=store)
    steps = generate_band(advice, check_band(advice))
    script = render_submission_band(advice, hpc, "quantum_espresso", steps)
    bundle = to_bundle_input_band(
        advice,
        steps,
        script,
        default_shared_context(),
        code="quantum_espresso",
        hpc=hpc,
        assignments={},
        source=in_memory_source(spinel),
    )
    publish(bundle, DirectoryOutput(tmp_path / "bundle"))

    records = strict_json((tmp_path / "bundle" / "goldilocks.json").read_text())[
        "records"
    ]
    assert records["bands_convergence"]["value"]["conv_thr"] == 2.8e-09
    for name in ("scf.in", "bands.in"):
        text = (tmp_path / "bundle" / name).read_text()
        assert "   conv_thr         = 2.8e-09" in text.splitlines(), name
        _assert_written_as_decimals(text)
    assert "K_POINTS crystal_b" in (tmp_path / "bundle" / "bands.in").read_text()
