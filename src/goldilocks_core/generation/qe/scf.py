"""Quantum ESPRESSO SCF input writer and section renderers."""

from __future__ import annotations

import re

from pymatgen.core import Structure
from pymatgen.core.periodic_table import Element

from goldilocks_core.contracts import (
    CalculationIntent,
    GeneratedFile,
    ParameterAdvice,
    SelectionRecord,
)

# Code-agnostic vdW method labels → (QE ``vdw_corr`` value, ``dftd3_version``).
# QE has no separate D3-BJ keyword: both D3 variants use ``vdw_corr='grimme-d3'``
# and select the damping via ``dftd3_version`` (3 = zero damping, 4 = Becke-Johnson).
_QE_VDW_CORR = {
    "d3": ("grimme-d3", 3),
    "d3bj": ("grimme-d3", 4),
    "ts": ("ts-vdw", None),
    "mbd": ("many-body-dispersion", None),
}
_QE_SMEARING = {
    "gaussian": "gaussian",
    "mp": "mp",
    "cold": "cold",
}


def write_qe_scf(
    structure: Structure,
    intent: CalculationIntent,
    advice: ParameterAdvice,
    selection: SelectionRecord,
) -> tuple[GeneratedFile, ...]:
    """Write the Quantum ESPRESSO SCF input for one calculation intent.

    Args:
        structure: Ordered structure to write in QE cell/position cards.
        intent: Calculation intent. The dispatcher is responsible for
            selecting this writer only for compatible intents.
        advice: Smearing, magnetism, SOC, and convergence advice.
        selection: K-point grid plus pseudopotential and cutoff selections
            produced by the Select stage.

    Returns:
        A one-element tuple holding the rendered QE SCF input file.

    Raises:
        ValueError: If the structure is disordered or the advice carries an
            unsupported smearing or vdW method for the QE target.
    """
    return (
        GeneratedFile(
            path="inputs/qe.in",
            content=_render_qe_scf(structure, intent, advice, selection),
        ),
    )


def _render_qe_scf(
    structure: Structure,
    intent: CalculationIntent,
    advice: ParameterAdvice,
    selection: SelectionRecord,
) -> str:
    """Render a Quantum ESPRESSO SCF input from staged Core records.

    Selection records are trusted as produced by the Select stage; this
    renderer does not re-validate pseudopotential coverage or cutoffs.

    Args:
        structure: Ordered structure to write in QE cell/position cards.
        intent: Calculation intent (unused by the QE SCF renderer).
        advice: Smearing, magnetism, SOC, and convergence advice.
        selection: K-point grid plus pseudopotential and cutoff selections.

    Returns:
        Complete QE input text ending with a trailing newline.
    """
    if not structure.is_ordered:
        raise ValueError(
            "Cannot generate Quantum ESPRESSO input for disordered structures"
        )

    elements = tuple(
        sorted(element.symbol for element in structure.composition.elements)
    )
    pseudo_by_element = {
        pseudo.element: pseudo for pseudo in selection.pseudopotentials
    }
    selected_pseudos = tuple(pseudo_by_element[element] for element in elements)
    ecutwfc = max(float(pseudo.ecutwfc_ry) for pseudo in selected_pseudos)
    ecutrho = max(float(pseudo.ecutrho_ry) for pseudo in selected_pseudos)

    for pseudo in selected_pseudos:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", pseudo.filename) is None:
            raise ValueError(f"Unsafe pseudopotential filename: {pseudo.filename!r}")

    lines: list[str] = []
    lines.extend(_control_section())
    lines.extend(
        _system_section(
            structure=structure,
            advice=advice,
            ecutwfc=ecutwfc,
            ecutrho=ecutrho,
        )
    )
    lines.extend(_electrons_section(advice))
    lines.extend(_cell_parameters(structure))
    lines.extend(_atomic_species(elements, pseudo_by_element))
    lines.extend(_atomic_positions(structure))
    lines.extend(_k_points(selection))

    return "\n".join(lines) + "\n"


def _control_section() -> list[str]:
    """Return the QE CONTROL namelist."""
    return [
        "&CONTROL",
        "  calculation = 'scf'",
        "  pseudo_dir = './pseudo'",
        "  outdir = './out'",
        "  tprnfor = .true.",
        "  tstress = .true.",
        "/",
        "",
    ]


def _system_section(
    *,
    structure: Structure,
    advice: ParameterAdvice,
    ecutwfc: float,
    ecutrho: float,
) -> list[str]:
    """Return the QE SYSTEM namelist from advice and cutoffs."""
    ntyp = len(structure.composition.elements)
    return [
        "&SYSTEM",
        "  ibrav = 0",
        f"  nat = {len(structure)}",
        f"  ntyp = {ntyp}",
        f"  ecutwfc = {_format_float(ecutwfc)}",
        f"  ecutrho = {_format_float(ecutrho)}",
        *_smearing_lines(advice),
        *_spin_lines(advice),
        *_vdw_lines(advice),
        "/",
        "",
    ]


def _smearing_lines(advice: ParameterAdvice) -> list[str]:
    """Return SYSTEM occupation/smearing lines from smearing advice."""
    smearing_type = advice.smearing.smearing_type
    if smearing_type in (None, "fixed"):
        return ["  occupations = 'fixed'"]
    qe_smearing = _QE_SMEARING.get(smearing_type)
    if qe_smearing is None:
        raise ValueError(
            "Quantum ESPRESSO smearing advice is invalid: unsupported "
            f"method {smearing_type!r}"
        )
    if advice.smearing.width_ry is None:
        raise ValueError("Smearing width is required when smearing is enabled")
    return [
        "  occupations = 'smearing'",
        f"  smearing = '{qe_smearing}'",
        f"  degauss = {_format_float(advice.smearing.width_ry)}",
    ]


def _spin_lines(advice: ParameterAdvice) -> list[str]:
    """Return SYSTEM spin lines from magnetism and SOC advice."""
    if advice.spin_orbit.enabled:
        return ["  noncolin = .true.", "  lspinorb = .true."]
    if advice.magnetism.spin_polarized:
        return ["  nspin = 2"]
    return []


def _vdw_lines(advice: ParameterAdvice) -> list[str]:
    """Return SYSTEM vdW-corr lines from vdW advice."""
    method = advice.vdw.method
    if advice.vdw.use_vdw:
        if method not in _QE_VDW_CORR:
            raise ValueError(
                "Quantum ESPRESSO vdW advice is invalid: enabled vdW requires "
                f"a supported method; got {method!r}"
            )
        vdw_corr, dftd3_version = _QE_VDW_CORR[method]
        lines = [f"  vdw_corr = '{vdw_corr}'"]
        if dftd3_version is not None:
            lines.append(f"  dftd3_version = {dftd3_version}")
        return lines
    if method is not None:
        raise ValueError(
            "Quantum ESPRESSO vdW advice is invalid: disabled vdW requires "
            f"method=None; got {method!r}"
        )
    return []


def _electrons_section(advice: ParameterAdvice) -> list[str]:
    """Return the QE ELECTRONS namelist from convergence advice."""
    return [
        "&ELECTRONS",
        f"  conv_thr = {_format_scientific(advice.convergence.conv_thr)}",
        f"  mixing_beta = {_format_float(advice.convergence.mixing_beta)}",
        f"  electron_maxstep = {advice.convergence.electron_maxstep}",
        "/",
        "",
    ]


def _cell_parameters(structure: Structure) -> list[str]:
    """Return QE CELL_PARAMETERS card in angstrom."""
    lines = ["CELL_PARAMETERS angstrom"]
    for vector in structure.lattice.matrix:
        lines.append("  " + "  ".join(_format_float(value) for value in vector))
    lines.append("")
    return lines


def _atomic_species(elements: tuple[str, ...], pseudo_by_element: dict) -> list[str]:
    """Return QE ATOMIC_SPECIES card."""
    lines = ["ATOMIC_SPECIES"]
    for element in elements:
        pseudo = pseudo_by_element[element]
        lines.append(
            f"  {element}  {_format_float(float(Element(element).atomic_mass))}  "
            f"{pseudo.filename}"
        )
    lines.append("")
    return lines


def _atomic_positions(structure: Structure) -> list[str]:
    """Return QE ATOMIC_POSITIONS card in fractional coordinates."""
    lines = ["ATOMIC_POSITIONS crystal"]
    for site in structure:
        coords = "  ".join(_format_float(value) for value in site.frac_coords)
        lines.append(f"  {site.specie.symbol}  {coords}")
    lines.append("")
    return lines


def _k_points(selection: SelectionRecord) -> list[str]:
    """Return QE K_POINTS automatic card from selected grid and shift."""
    grid = selection.k_points.grid
    shift = selection.k_points.shift
    return [
        "K_POINTS automatic",
        f"  {grid[0]}  {grid[1]}  {grid[2]}  {shift[0]}  {shift[1]}  {shift[2]}",
    ]


def _format_float(value: float) -> str:
    """Format finite numeric values deterministically for QE text."""
    return f"{value:.10g}"


def _format_scientific(value: float) -> str:
    """Format scientific notation for QE namelists."""
    return f"{value:.10e}"
