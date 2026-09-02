from __future__ import annotations

import re

from pymatgen.core import Structure
from pymatgen.core.periodic_table import Element

from goldilocks_core.calculation import CalculationIntent
from goldilocks_core.generation.errors import GenerationError
from goldilocks_core.types import JsonDict

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
    advice: JsonDict,
    selection: JsonDict,
    k_points: JsonDict,
) -> tuple[JsonDict, ...]:
    return (
        {
            "path": "inputs/qe.in",
            "content": _render_qe_scf(structure, intent, advice, selection, k_points),
            "role": "input",
        },
    )


def _render_qe_scf(
    structure: Structure,
    intent: CalculationIntent,
    advice: JsonDict,
    selection: JsonDict,
    k_points: JsonDict,
) -> str:
    if not structure.is_ordered:
        raise GenerationError(
            "Cannot generate Quantum ESPRESSO input for disordered structures"
        )

    elements = tuple(
        sorted(element.symbol for element in structure.composition.elements)
    )
    if advice["pseudopotential_requirements"]["functional"] != intent.functional:
        raise GenerationError(
            "Pseudopotential requirement functional mismatch: calculation "
            f"requires {intent.functional}, advice requires "
            f"{advice['pseudopotential_requirements']['functional']}"
        )
    pseudo_by_element = {
        pseudo["element"]: pseudo for pseudo in selection["pseudopotentials"]
    }
    if len(pseudo_by_element) != len(selection["pseudopotentials"]):
        raise GenerationError("Pseudopotential selection contains duplicate elements")
    missing_elements = sorted(set(elements) - set(pseudo_by_element))
    extra_elements = sorted(set(pseudo_by_element) - set(elements))
    if missing_elements or extra_elements:
        raise GenerationError(
            "Pseudopotential selection coverage mismatch; "
            f"missing: {', '.join(missing_elements) or 'none'}; "
            f"extra: {', '.join(extra_elements) or 'none'}"
        )
    selected_pseudos = tuple(pseudo_by_element[element] for element in elements)

    expected_functional = intent.functional
    for pseudo in selected_pseudos:
        missing = [
            name
            for name, value in (
                ("filename", pseudo["filename"]),
                ("ecutwfc_ry", pseudo["ecutwfc_ry"]),
                ("ecutrho_ry", pseudo["ecutrho_ry"]),
            )
            if value is None
        ]
        if missing:
            raise GenerationError(
                f"Pseudopotential selection for {pseudo['element']} is incomplete: "
                f"missing {', '.join(missing)}"
            )
        if pseudo["functional"] != expected_functional:
            raise GenerationError(
                f"Pseudopotential functional mismatch for {pseudo['element']}: "
                f"calculation requires {expected_functional}, selected "
                f"{pseudo['functional'] or 'unknown'}"
            )
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", pseudo["filename"]) is None:
            raise GenerationError(
                f"Unsafe pseudopotential filename: {pseudo['filename']!r}"
            )

    ecutwfc = max(float(pseudo["ecutwfc_ry"]) for pseudo in selected_pseudos)
    ecutrho = max(float(pseudo["ecutrho_ry"]) for pseudo in selected_pseudos)

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
    lines.extend(_k_points(k_points))

    return "\n".join(lines) + "\n"


def _control_section() -> list[str]:
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
    advice: JsonDict,
    ecutwfc: float,
    ecutrho: float,
) -> list[str]:
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


def _smearing_lines(advice: JsonDict) -> list[str]:
    smearing_type = advice["smearing"]["smearing_type"]
    if smearing_type in (None, "fixed"):
        return ["  occupations = 'fixed'"]
    qe_smearing = _QE_SMEARING.get(smearing_type)
    if qe_smearing is None:
        raise GenerationError(
            "Quantum ESPRESSO smearing advice is invalid: unsupported "
            f"method {smearing_type!r}"
        )
    if advice["smearing"]["width_ry"] is None:
        raise GenerationError("Smearing width is required when smearing is enabled")
    return [
        "  occupations = 'smearing'",
        f"  smearing = '{qe_smearing}'",
        f"  degauss = {_format_float(advice['smearing']['width_ry'])}",
    ]


def _spin_lines(advice: JsonDict) -> list[str]:
    if advice["spin_orbit"]["enabled"]:
        return ["  noncolin = .true.", "  lspinorb = .true."]
    if advice["magnetism"]["spin_polarized"]:
        return ["  nspin = 2"]
    return []


def _vdw_lines(advice: JsonDict) -> list[str]:
    method = advice["vdw"]["method"]
    if advice["vdw"]["use_vdw"]:
        if method not in _QE_VDW_CORR:
            raise GenerationError(
                "Quantum ESPRESSO vdW advice is invalid: enabled vdW requires "
                f"a supported method; got {method!r}"
            )
        vdw_corr, dftd3_version = _QE_VDW_CORR[method]
        lines = [f"  vdw_corr = '{vdw_corr}'"]
        if dftd3_version is not None:
            lines.append(f"  dftd3_version = {dftd3_version}")
        return lines
    if method is not None:
        raise GenerationError(
            "Quantum ESPRESSO vdW advice is invalid: disabled vdW requires "
            f"method=None; got {method!r}"
        )
    return []


def _electrons_section(advice: JsonDict) -> list[str]:
    return [
        "&ELECTRONS",
        f"  conv_thr = {_format_scientific(advice['convergence']['conv_thr'])}",
        f"  mixing_beta = {_format_float(advice['convergence']['mixing_beta'])}",
        f"  electron_maxstep = {advice['convergence']['electron_maxstep']}",
        "/",
        "",
    ]


def _cell_parameters(structure: Structure) -> list[str]:
    lines = ["CELL_PARAMETERS angstrom"]
    lines.extend(
        "  " + "  ".join(_format_float(value) for value in vector)
        for vector in structure.lattice.matrix
    )
    lines.append("")
    return lines


def _atomic_species(elements: tuple[str, ...], pseudo_by_element: dict) -> list[str]:
    lines = ["ATOMIC_SPECIES"]
    for element in elements:
        pseudo = pseudo_by_element[element]
        lines.append(
            f"  {element}  {_format_float(float(Element(element).atomic_mass))}  "
            f"{pseudo['filename']}"
        )
    lines.append("")
    return lines


def _atomic_positions(structure: Structure) -> list[str]:
    lines = ["ATOMIC_POSITIONS crystal"]
    for site in structure:
        coords = "  ".join(_format_float(value) for value in site.frac_coords)
        lines.append(f"  {site.specie.symbol}  {coords}")
    lines.append("")
    return lines


def _k_points(k_points: JsonDict) -> list[str]:
    grid = k_points["grid"]
    shift = k_points["shift"]
    return [
        "K_POINTS automatic",
        f"  {grid[0]}  {grid[1]}  {grid[2]}  {shift[0]}  {shift[1]}  {shift[2]}",
    ]


def _format_float(value: float) -> str:
    return f"{value:.10g}"


def _format_scientific(value: float) -> str:
    return f"{value:.10e}"
