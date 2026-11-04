from __future__ import annotations

import re
from decimal import Decimal

import pytest

from goldilocks_core.generation.errors import GenerationError
from goldilocks_core.generation.quantum_espresso.namelists import render_namelist


def test_renders_only_sections_that_received_a_keyword() -> None:
    text = render_namelist(
        {
            "calculation": "scf",
            "ecutwfc": 40.0,
            "conv_thr": 1e-08,
        }
    )

    assert "&CONTROL" in text
    assert "&SYSTEM" in text
    assert "&ELECTRONS" in text
    assert "&IONS" not in text
    assert "&CELL" not in text
    assert "&FCP" not in text
    assert "&RISM" not in text


def test_preserves_indexed_magnetic_keywords_verbatim() -> None:
    text = render_namelist(
        {
            "nspin": 2,
            "starting_magnetization(1)": 0.55,
            "angle1(1)": 90.0,
        }
    )

    assert "starting_magnetization(1) = 0.55" in text
    assert "angle1(1)" in text and "90.0" in text


def test_never_rederives_magnetization_from_atoms_magic() -> None:
    """The exact bug this module exists to avoid: ASE's write_espresso_in
    silently overwrites starting_magnetization from atoms.get_initial_
    magnetic_moments() whenever nspin==2. render_namelist never touches
    Atoms at all, so a resolved non-zero value must survive unchanged."""
    text = render_namelist({"nspin": 2, "starting_magnetization(1)": 0.55})

    assert "starting_magnetization(1) = 0.55" in text
    assert "0.0" not in text


def _values(text: str) -> dict[str, str]:
    return dict(re.findall(r"^\s*(\S+)\s+= (\S+)$", text, flags=re.MULTILINE))


def test_float_noise_renders_as_the_shortest_decimal() -> None:
    """#178: a float product such as 14 * 0.2e-9 is 2.8000000000000003e-09,
    and ASE writes the repr of what it is given. Every float, indexed keys
    included, is written to 12 significant digits, never as -0.0."""
    text = render_namelist(
        {
            "conv_thr": 14 * 0.2e-9,
            "etot_conv_thr": 12 * 1e-5,
            "starting_magnetization(1)": 0.1 + 0.2,
            "tot_magnetization": -0.0,
            "ecutwfc": 45.12345678912345,
        }
    )

    assert _values(text) == {
        "etot_conv_thr": "0.00012",
        "ecutwfc": "45.1234567891",
        "starting_magnetization(1)": "0.3",
        "tot_magnetization": "0.0",
        "conv_thr": "2.8e-09",
    }


def test_nat_scaled_thresholds_render_as_their_decimal_for_nat_1_to_200() -> None:
    """#178: 45 of these conv_thr products and 101 etot_conv_thr products
    carried float noise into the input."""
    for nat in range(1, 201):
        values = _values(
            render_namelist({"conv_thr": nat * 0.2e-9, "etot_conv_thr": nat * 1e-5})
        )

        assert Decimal(values["conv_thr"]) == nat * Decimal("0.2e-9"), nat
        assert Decimal(values["etot_conv_thr"]) == nat * Decimal("1e-5"), nat


def test_small_scalars_are_kept_not_snapped_to_zero() -> None:
    """A conv_thr of 1e-12 is a legitimate request; only card geometry
    snaps near-zero values (``scf.py``)."""
    text = render_namelist({"conv_thr": 1e-12, "etot_conv_thr": 1e-11})

    assert _values(text) == {"etot_conv_thr": "1e-11", "conv_thr": "1e-12"}


def test_booleans_render_as_qe_fortran_literals() -> None:
    text = render_namelist({"tprnfor": True, "tstress": False})

    assert "tprnfor" in text and ".true." in text
    assert "tstress" in text and ".false." in text


def test_unrecognized_keyword_raises_generation_error_not_silent_drop() -> None:
    with pytest.raises(GenerationError, match="unrecognized"):
        render_namelist({"ecutwfc": 40.0, "totally_bogus_keyword": 1})


def test_empty_keywords_raises_generation_error() -> None:
    with pytest.raises(GenerationError, match="no Quantum ESPRESSO"):
        render_namelist({})
