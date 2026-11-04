"""hubbard_u: whether a Hubbard +U correction applies, and which U_eff each
element gets.

A resolved ``HubbardUDecision`` holds one ``HubbardU`` entry per element
that gets +U, either from the built-in table below or from a human
``u_by_element`` (which replaces the table). The QE writers render a
HUBBARD card iff ``u_values`` is non-empty, so every resolved decision is
renderable: no Hubbard outcome can pass ``checks.check_all`` and then fail
in a writer (#135). An element without a U is plain DFT. The decision's
warnings follow from its entries and projectors alone, whichever branch
produced them (``_decision``, #167).

**Projectors.** The card's projector type is the ``hubbard_projectors``
setting, the same for every task: ``ortho-atomic`` by default, which QE
recommends (Doc/Hubbard_input.tex:141), or ``atomic``, the only type ph.x
accepts for DFPT+U (PHonon/PH/phq_readin.f90:766-767). A U value is tied
to the projectors it was derived with (I. Timrov et al., Phys. Rev. B 102,
235159 (2020); Doc/Hubbard_input.tex:624), so switching projectors changes
what a given U means; the table below is used unchanged with either.

**When.** The ``needs_correlation`` fact (a transition metal, lanthanide or
actinide with O or F, Materials Project's screening rule) or a human/LLM
``needs_correlation`` override decides whether +U applies at all. A hybrid
functional (``advisors.functional.HYBRID_FUNCTIONAL``) already corrects
the self-interaction error +U patches, so it always gets no +U
(goldilocks-core-design.md:2626-2627).

**Built-in table** (``_U_TABLE``), conventions in short:

- Each value is a Dudarev U_eff = U - J in eV on one manifold, written as
  ``U <label>-<manifold> <value>`` under ``HUBBARD (<projectors>)``. QE
  reads a card holding only U values as ``lda_plus_u_kind = 0``, the
  simplified Dudarev scheme (Modules/read_cards.f90:3046-3048).
- d block: the Materials Project convention (V, Cr, Mn, Fe, Co, Ni, Mo, W;
  fits to GGA+U oxide oxidation enthalpies, VASP PAW, PBE) plus Cu 4.0
  (the Wang et al. 2006 fit, as tabulated by Jain et al. 2011). Ce: 5.0
  from Loschen et al. 2007 (VASP PAW, PW91). Pr-Yb: Topsakal & Wentzcovitch
  2014, fitted in QE (atomic projectors) with the Wentzcovitch PAW datasets
  SSSP ships. Pa
  (OQMD's qmpy configuration) and U, Np, Pu (OQMD): 4.0 for An(IV) oxides,
  VASP PAW. Am, Cm: Suzuki et al. 2013 (all-electron LDA+U+SOC, J = 0).
  Bk: Chen & Kaltsoyannis 2025 (all-electron PBE+U+SOC).
- None of these was derived with QE's ortho-atomic projectors, so under
  them every table value carries ``hubbard.projector_mismatch``; under
  atomic projectors the Pr-Yb values match and only the others carry it.
  Each is one value per element whatever its oxidation state or
  environment, fitted on oxides or fluorides (Pr-Yb: nitrides) with PBE,
  PW91 or LDA, while the default functional here is PBEsol; the
  SOC-derived actinide values are applied without SOC.
- ``_NO_U`` elements deliberately get no U (plain DFT, no warning): the
  other d-block elements (Materials Project convention), La (La3+ is 4f0),
  Lu (4f14 5d0) and Th (5f0).
- Every other correlated element (Ac, Cf, Es, Fm, Md, No, Lr; no installed
  table covers Rf-Cn) has no published U: plain DFT plus a
  ``hubbard.u_value_missing`` warning naming the element, its manifold and
  ``u_by_element``.
- No installed pseudopotential can carry a U on La-4f or Ac-5f
  (``_NO_HUBBARD_CHANNEL``), so ``u_by_element`` rejects both and Ac's
  warning says so instead of suggesting a value.

Self-consistent calibration (hp.x, #124) is not implemented. Bastonero et
al., npj Comput. Mater. 11, 183 (2025) (ortho-atomic linear response on
QE, PBEsol and SSSP 1.3) is the stack-matched benchmark for it.

**No ml tier, permanently.** An ENN-based +U predictor (Uhrin et al. 2025)
needs an SCF occupation matrix as input, which a stateless advisor never
has (goldilocks-core-design.md:2635).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, NamedTuple

from pydantic import AfterValidator, Field
from pymatgen.core import Structure
from pymatgen.core.periodic_table import Element

from goldilocks_core.advisors.functional import HYBRID_FUNCTIONAL
from goldilocks_core.analysis.composition import CompositionFacts, composition
from goldilocks_core.inputs.overrides import HumanInput, LlmInput
from goldilocks_core.resolution import (
    Blocked,
    FieldState,
    Provenance,
    Resolved,
    Warning,
    blocked_by,
    field_sources_from,
)

HubbardProjectors = Literal["ortho-atomic", "atomic"]
"""The HUBBARD card's projector types this package writes (module
docstring)."""

_DEFAULT_PROJECTORS: HubbardProjectors = "ortho-atomic"


class _TabulatedU(NamedTuple):
    manifold: str
    u_eff_ev: float
    citation: str
    doi: str


_MATERIALS_PROJECT = (
    "Materials Project; A. Wang et al., Sci. Rep. 11, 15496 (2021), Table S3",
    "10.1038/s41598-021-94550-5",
)
_MATERIALS_PROJECT_RELAX_SET = (
    "Materials Project MPRelaxSet; A. Jain et al., Phys. Rev. B 84, 045115 (2011)",
    "10.1103/PhysRevB.84.045115",
)
_JAIN_2011 = (
    "A. Jain et al., Phys. Rev. B 84, 045115 (2011), Table I",
    "10.1103/PhysRevB.84.045115",
)
_LOSCHEN_2007 = (
    "C. Loschen et al., Phys. Rev. B 75, 035115 (2007)",
    "10.1103/PhysRevB.75.035115",
)
_TOPSAKAL_2014 = (
    "M. Topsakal and R. M. Wentzcovitch, Comput. Mater. Sci. 95, 263 (2014)",
    "10.1016/j.commatsci.2014.07.030",
)
_QMPY = (
    "OQMD qmpy configuration (hubbards.yml); S. Kirklin et al., "
    "npj Comput. Mater. 1, 15010 (2015)",
    "10.1038/npjcompumats.2015.10",
)
_OQMD = (
    "S. Kirklin et al. (OQMD), npj Comput. Mater. 1, 15010 (2015)",
    "10.1038/npjcompumats.2015.10",
)
_SUZUKI_2013 = (
    "M.-T. Suzuki et al., Phys. Rev. B 88, 195146 (2013)",
    "10.1103/PhysRevB.88.195146",
)
_CHEN_2025 = (
    "J.-L. Chen and N. Kaltsoyannis, J. Phys. Chem. C 129, 10313 (2025)",
    "10.1021/acs.jpcc.5c01663",
)
_VASP_PAW_SOURCES = frozenset(
    {
        _MATERIALS_PROJECT,
        _MATERIALS_PROJECT_RELAX_SET,
        _JAIN_2011,
        _LOSCHEN_2007,
        _QMPY,
        _OQMD,
    }
)
_ALL_ELECTRON_SOURCES = frozenset({_SUZUKI_2013, _CHEN_2025})
_DERIVED_WITH: dict[HubbardProjectors, frozenset[tuple[str, str]]] = {
    "ortho-atomic": frozenset(),
    "atomic": frozenset({_TOPSAKAL_2014}),
}
"""The sources whose values were fitted in QE with each projector type:
none with ortho-atomic, Topsakal & Wentzcovitch's with atomic."""

_U_TABLE: dict[str, _TabulatedU] = {
    "V": _TabulatedU("3d", 3.25, *_MATERIALS_PROJECT),
    "Cr": _TabulatedU("3d", 3.7, *_MATERIALS_PROJECT),
    "Mn": _TabulatedU("3d", 3.9, *_MATERIALS_PROJECT),
    "Fe": _TabulatedU("3d", 5.3, *_MATERIALS_PROJECT),
    "Co": _TabulatedU("3d", 3.32, *_MATERIALS_PROJECT),
    "Ni": _TabulatedU("3d", 6.2, *_MATERIALS_PROJECT),
    "Cu": _TabulatedU("3d", 4.0, *_JAIN_2011),
    "Mo": _TabulatedU("4d", 4.38, *_MATERIALS_PROJECT_RELAX_SET),
    "W": _TabulatedU("5d", 6.2, *_MATERIALS_PROJECT_RELAX_SET),
    "Ce": _TabulatedU("4f", 5.0, *_LOSCHEN_2007),
    "Pr": _TabulatedU("4f", 4.0, *_TOPSAKAL_2014),
    "Nd": _TabulatedU("4f", 3.1, *_TOPSAKAL_2014),
    "Pm": _TabulatedU("4f", 3.4, *_TOPSAKAL_2014),
    "Sm": _TabulatedU("4f", 3.3, *_TOPSAKAL_2014),
    "Eu": _TabulatedU("4f", 3.0, *_TOPSAKAL_2014),
    "Gd": _TabulatedU("4f", 4.6, *_TOPSAKAL_2014),
    "Tb": _TabulatedU("4f", 5.0, *_TOPSAKAL_2014),
    "Dy": _TabulatedU("4f", 5.0, *_TOPSAKAL_2014),
    "Ho": _TabulatedU("4f", 4.9, *_TOPSAKAL_2014),
    "Er": _TabulatedU("4f", 4.2, *_TOPSAKAL_2014),
    "Tm": _TabulatedU("4f", 4.8, *_TOPSAKAL_2014),
    "Yb": _TabulatedU("4f", 3.0, *_TOPSAKAL_2014),
    "Pa": _TabulatedU("5f", 4.0, *_QMPY),
    "U": _TabulatedU("5f", 4.0, *_OQMD),
    "Np": _TabulatedU("5f", 4.0, *_OQMD),
    "Pu": _TabulatedU("5f", 4.0, *_OQMD),
    "Am": _TabulatedU("5f", 4.0, *_SUZUKI_2013),
    "Cm": _TabulatedU("5f", 4.0, *_SUZUKI_2013),
    "Bk": _TabulatedU("5f", 3.54, *_CHEN_2025),
}
"""element -> (manifold, Dudarev U_eff in eV, short citation, DOI); see the
module docstring for the conventions."""

_NO_U = frozenset(
    {
        *("Sc", "Ti", "Zn", "Y", "Zr", "Nb", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd"),
        *("Hf", "Ta", "Re", "Os", "Ir", "Pt", "Au", "Hg", "La", "Lu", "Th"),
    }
)
"""Correlated elements that deliberately get no U: plain DFT for that
element, no warning (module docstring)."""

_NO_HUBBARD_CHANNEL = {
    "La": "no installed La pseudopotential has an occupied 4f channel",
    "Ac": "no installed Ac pseudopotential has a 5f channel",
}
"""Elements whose Hubbard manifold no installed pseudopotential carries, so
pw.x stops on their U line whatever the value. SSSP's La has 4f occupation
0 (QE 7.3 PW/src/offset_atom_wfc.f90:104-110: "Hubbard manifold with zero
occupations is not allowed") and PseudoDojo's has no 4f channel; the only
Ac file (SSSP) has no 5f channel (PW/src/hubbard.f90:201-206: "Mismatch
between the requested and available manifolds")."""

_MANIFOLD_BY_BLOCK_AND_ROW = {
    ("d", 4): "3d",
    ("d", 5): "4d",
    ("d", 6): "5d",
    ("d", 7): "6d",
    ("f", 6): "4f",
    ("f", 7): "5f",
}
"""(pymatgen Element.block, Element.row) -> the valence d (row - 1) or f
(row - 2) manifold; s- and p-block elements use their row (O -> 2p).
pymatgen places La and Ac in the f block (4f, 5f) and Lu and Lr in the d
block (5d, 6d)."""

_VASP_DERIVED = ", ".join(
    symbol
    for symbol, row in _U_TABLE.items()
    if (row.citation, row.doi) in _VASP_PAW_SOURCES
)
_ALL_ELECTRON_DERIVED = ", ".join(
    symbol
    for symbol, row in _U_TABLE.items()
    if (row.citation, row.doi) in _ALL_ELECTRON_SOURCES
)

PROJECTOR_MISMATCH_WARNING = Warning(
    code="hubbard.projector_mismatch",
    level="warning",
    category="hubbard",
    message=(
        "A built-in U value was not derived with the Quantum ESPRESSO projectors "
        "this input uses (hubbard_projectors), so the same U need not give the "
        "same correction."
    ),
)
"""Catalogue entry; ``_PROJECTOR_MISMATCH`` words it for each projector
type."""

_PROJECTOR_MISMATCH: dict[HubbardProjectors, Warning] = {
    "ortho-atomic": PROJECTOR_MISMATCH_WARNING.model_copy(
        update={
            "message": (
                "No built-in U value was derived with the Quantum ESPRESSO "
                "ortho-atomic projectors this input uses, so the same U need not "
                "give the same correction. VASP-derived (PAW projectors): "
                f"{_VASP_DERIVED}. The other built-in values come from QE "
                "atomic-projector or all-electron calculations."
            )
        }
    ),
    "atomic": PROJECTOR_MISMATCH_WARNING.model_copy(
        update={
            "message": (
                f"The built-in U values of {_VASP_DERIVED} (VASP-derived, PAW "
                f"projectors) and {_ALL_ELECTRON_DERIVED} (all-electron) were not "
                "derived with the Quantum ESPRESSO atomic projectors this input "
                "uses, so the same U need not give the same correction."
            )
        }
    ),
}
"""The warning a built-in value not fitted with the projectors in use
(``_DERIVED_WITH``) adds, by projector type. Every table value mismatches
ortho-atomic projectors; the Pr-Yb values match atomic ones, so that text
names only the others."""

STARTING_NS_EIGENVALUE_WARNING = Warning(
    code="hubbard.starting_ns_eigenvalue_missing",
    level="warning",
    category="hubbard",
    message=(
        "No starting_ns_eigenvalue initial occupation-matrix guess is provided: "
        "+U calculations have multiple metastable occupation-matrix solutions and "
        "may converge to the wrong one silently. Supplying an explicit initial "
        "guess is recommended but not computed automatically here."
    ),
)
"""A10 (goldilocks-core-design.md:4465): a real initial guess needs a
crystal-field decomposition of the occupation matrix by spin channel, which
this package does not attempt, so it warns instead of guessing a number."""

U_VALUE_MISSING_WARNING = Warning(
    code="hubbard.u_value_missing",
    level="warning",
    category="hubbard",
    message=(
        "An element that would get +U has no published U value, so it gets "
        "plain DFT; u_by_element can apply one unless no installed "
        "pseudopotential carries that element's manifold."
    ),
)
"""Catalogue entry; ``_u_value_missing`` names the element, its manifold
and the u_by_element setting to use, or why it cannot apply one."""

U_BY_ELEMENT_UNUSED_WARNING = Warning(
    code="hubbard.u_by_element_unused",
    level="warning",
    category="hubbard",
    message=(
        "u_by_element names elements this structure does not contain, which "
        "are ignored."
    ),
)

WARNING_CATALOGUE = (
    PROJECTOR_MISMATCH_WARNING,
    STARTING_NS_EIGENVALUE_WARNING,
    U_VALUE_MISSING_WARNING,
    U_BY_ELEMENT_UNUSED_WARNING,
)
"""Every warning code this module can emit -- ``capabilities.py``'s
``warnings[]`` catalogue aggregates one of these tuples per advisor."""


@dataclass(frozen=True, slots=True)
class HubbardU:
    """One element's onsite Hubbard U_eff (Dudarev U - J, in eV) on
    ``manifold``. ``value_source`` is ``"table"`` for a built-in value,
    whose ``citation`` and ``doi`` name its source, or ``"human"`` for a
    ``u_by_element`` value (both ``None``)."""

    element: str
    manifold: str
    u_ev: float
    value_source: Literal["table", "human"]
    citation: str | None = None
    doi: str | None = None


@dataclass(frozen=True, slots=True)
class HubbardUDecision:
    """``u_values`` holds one entry per element that gets +U, sorted by
    element; the QE writers render a HUBBARD card iff it is non-empty, with
    ``projectors`` as its projector type: ortho-atomic unless the request
    asks for atomic, and ``None`` exactly when no element gets +U."""

    u_values: tuple[HubbardU, ...] = ()
    projectors: HubbardProjectors | None = None
    warnings: tuple[Warning, ...] = ()


def _u_by_element_key(symbol: str) -> str:
    if not Element.is_valid_symbol(symbol):
        raise ValueError(f"{symbol} is not an element symbol")
    if symbol in _NO_HUBBARD_CHANNEL:
        raise ValueError(
            f"{symbol} cannot take a Hubbard U: {_NO_HUBBARD_CHANNEL[symbol]}, "
            f"so pw.x stops on any {symbol}-{_manifold(symbol)} U"
        )
    return symbol


_UByElementKey = Annotated[str, AfterValidator(_u_by_element_key)]
_PositiveFiniteU = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class HubbardUHumanInput(HumanInput):
    needs_correlation: bool | None = None
    u_by_element: dict[_UByElementKey, _PositiveFiniteU] | None = None
    """Dudarev U_eff (eV) per element symbol, finite and > 0 (leave an
    element out for no U); replaces the built-in table, so only listed
    elements present in the structure get +U. La and Ac are rejected
    (``_NO_HUBBARD_CHANNEL``)."""
    hubbard_projectors: HubbardProjectors | None = None
    """The HUBBARD card's projector type when an element gets +U
    (``HubbardUDecision.projectors``). Named as the setting is published:
    a record's ``field_sources`` name settings by field name."""


class HubbardULlmInput(LlmInput):
    needs_correlation: bool | None = None


def hubbard_u(
    structure: Structure,
    needs_correlation: FieldState[bool],
    functional: str,
    human: HubbardUHumanInput | None = None,
    llm: HubbardULlmInput | None = None,
) -> FieldState[HubbardUDecision]:
    """Resolves in priority order: a hybrid functional (no +U), the human
    overrides (``needs_correlation=False``, then ``u_by_element``, then
    ``needs_correlation=True``), the LLM override, then the
    ``needs_correlation`` fact, which this propagates when it is blocked.
    A decision with a U takes the human ``hubbard_projectors``, else
    ortho-atomic. The provenance names the setting that decided and who set
    it, ``hubbard_projectors`` too when a U applies, and the record the rule
    followed (``_resolved``, #173)."""
    human = human or HubbardUHumanInput()
    llm = llm or HubbardULlmInput()
    projectors = human.hubbard_projectors or _DEFAULT_PROJECTORS

    if functional == HYBRID_FUNCTIONAL:
        return _resolved(_decision(), None, None, ("functional",))
    if human.needs_correlation is False:
        return _resolved(_decision(), human, llm)
    if human.u_by_element is not None:
        return _resolved(
            _from_u_by_element(structure, human.u_by_element, projectors),
            human,
            llm,
            setting="u_by_element",
        )
    if human.needs_correlation is True:
        return _resolved(_from_table(structure, projectors), human, llm)
    if llm.needs_correlation is False:
        return _resolved(_decision(), human, llm)
    if llm.needs_correlation is True:
        return _resolved(_from_table(structure, projectors), human, llm)

    if not needs_correlation.ok:
        return Blocked(by=blocked_by(needs_correlation))
    if not needs_correlation.value:
        return _resolved(_decision(), human, llm, ("needs_correlation",))
    return _resolved(
        _from_table(structure, projectors), human, llm, ("needs_correlation",)
    )


def _resolved(
    decision: HubbardUDecision,
    human: HubbardUHumanInput | None,
    llm: HubbardULlmInput | None,
    derived_from: tuple[str, ...] = (),
    *,
    setting: str = "needs_correlation",
) -> Resolved[HubbardUDecision]:
    """``decision`` with the provenance of the ``setting`` that decided it
    and, when it applies a U, of ``hubbard_projectors``: ``human`` or
    ``llm`` where that input set it, else ``heuristic``, with
    ``derived_from`` naming the record a heuristic rule followed (the
    ``needs_correlation`` fact, or ``functional`` for a hybrid, which reads
    neither input). Keyed by the attribute name ``needs_correlation``;
    ``/capabilities`` exposes it as ``hubbard_needs_correlation``."""
    fields = (setting, "hubbard_projectors") if decision.u_values else (setting,)
    return Resolved(
        decision,
        Provenance.from_field_sources(
            field_sources_from(human, llm, fields=fields), derived_from=derived_from
        ),
    )


def _from_table(
    structure: Structure, projectors: HubbardProjectors
) -> HubbardUDecision:
    """The built-in U for every tabulated correlated element, on
    ``projectors``. The others get plain DFT: silently for ``_NO_U``, with a
    warning otherwise. A structure with no correlated element (#36: a
    forced ``needs_correlation`` on plain Si) gets an empty decision."""
    correlated = _correlated_elements(composition(structure).value)
    u_values = tuple(_tabulated(symbol) for symbol in correlated if symbol in _U_TABLE)
    missing = tuple(
        symbol
        for symbol in correlated
        if symbol not in _U_TABLE and symbol not in _NO_U
    )
    return _decision(u_values, projectors, missing=missing)


def _tabulated(symbol: str) -> HubbardU:
    row = _U_TABLE[symbol]
    return HubbardU(symbol, row.manifold, row.u_eff_ev, "table", row.citation, row.doi)


def _from_u_by_element(
    structure: Structure, u_by_element: dict[str, float], projectors: HubbardProjectors
) -> HubbardUDecision:
    """Replace semantics: only listed elements present in ``structure`` get
    +U, on ``projectors``; listed elements it does not contain are reported,
    not refused, so one U table can serve many structures."""
    present = set(composition(structure).value.elements)
    u_values = tuple(
        HubbardU(symbol, _manifold(symbol), u_ev, "human")
        for symbol, u_ev in sorted(u_by_element.items())
        if symbol in present
    )
    unused = tuple(sorted(set(u_by_element) - present))
    return _decision(u_values, projectors, unused=unused)


def _decision(
    u_values: tuple[HubbardU, ...] = (),
    projectors: HubbardProjectors = _DEFAULT_PROJECTORS,
    *,
    missing: tuple[str, ...] = (),
    unused: tuple[str, ...] = (),
) -> HubbardUDecision:
    """Builds every resolved decision, so its projectors and warnings follow
    from its entries whichever branch produced them (#167): a decision with
    a U writes its card with ``projectors`` and one without has none, any
    applied U carries the starting-guess warning and a built-in one not
    fitted with ``projectors`` also the projector warning (a
    ``u_by_element`` value's source is unknown), each element without a
    published U adds ``hubbard.u_value_missing``, and unused
    ``u_by_element`` keys add ``hubbard.u_by_element_unused``."""
    warnings: list[Warning] = []
    if any(
        entry.value_source == "table"
        and (entry.citation, entry.doi) not in _DERIVED_WITH[projectors]
        for entry in u_values
    ):
        warnings.append(_PROJECTOR_MISMATCH[projectors])
    if u_values:
        warnings.append(STARTING_NS_EIGENVALUE_WARNING)
    warnings += [_u_value_missing(symbol, u_values, missing) for symbol in missing]
    if unused:
        warnings.append(_u_by_element_unused(unused, applied=bool(u_values)))
    return HubbardUDecision(
        u_values=u_values,
        projectors=projectors if u_values else None,
        warnings=tuple(warnings),
    )


def _u_value_missing(
    symbol: str, u_values: tuple[HubbardU, ...], missing: tuple[str, ...]
) -> Warning:
    """``u_by_element`` replaces the built-in table, so the suggested value
    keeps every U the decision already applies. It never suggests an
    element ``u_by_element`` rejects; that element's own warning says why
    no U can apply."""
    message = (
        f"No published Hubbard U value exists for {symbol} ({_manifold(symbol)}), "
        f"so {symbol} gets plain DFT"
    )
    if symbol in _NO_HUBBARD_CHANNEL:
        message += (
            f"; {_NO_HUBBARD_CHANNEL[symbol]}, so u_by_element cannot apply one either."
        )
    else:
        suggested = ", ".join(
            [f'"{entry.element}": {entry.u_ev:g}' for entry in u_values]
            + [
                f'"{element}": <U in eV>'
                for element in missing
                if element not in _NO_HUBBARD_CHANNEL
            ]
        )
        message += (
            f". To apply +U, set u_by_element={{{suggested}}}; u_by_element "
            "replaces the built-in table, so list every element that should "
            "get +U."
        )
    return U_VALUE_MISSING_WARNING.model_copy(update={"message": message})


def _u_by_element_unused(unused: tuple[str, ...], *, applied: bool) -> Warning:
    message = (
        "u_by_element names elements this structure does not contain, which "
        f"are ignored: {', '.join(unused)}."
    )
    if not applied:
        message += " No +U is applied."
    return U_BY_ELEMENT_UNUSED_WARNING.model_copy(update={"message": message})


def _correlated_elements(facts: CompositionFacts) -> tuple[str, ...]:
    return tuple(
        sorted({*facts.transition_metals, *facts.lanthanides, *facts.actinides})
    )


def _manifold(symbol: str) -> str:
    """The Hubbard manifold label of ``symbol``: the table's for a
    tabulated element, otherwise from its periodic-table block and row."""
    if symbol in _U_TABLE:
        return _U_TABLE[symbol].manifold
    element = Element(symbol)
    return _MANIFOLD_BY_BLOCK_AND_ROW.get(
        (element.block, element.row), f"{element.row}{element.block}"
    )
