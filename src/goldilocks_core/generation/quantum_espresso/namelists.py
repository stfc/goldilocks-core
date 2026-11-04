"""namelists: the one place QE namelist syntax gets generated.

New in v2 (v2 epic 7, #7). This is the design doc's own "insertion
point" for ASE (goldilocks-core-design.md:3872: "settings -> QE
keywords, the sole translation layer, the ASE insertion point"; :4220).
No underscore in the filename -- the design doc explicitly renames v1's
``_namelists.py`` sketch because a file this frequently edited should
not look like a private implementation detail (goldilocks-core-design.md
S4.4: "the same problem: the underscore in `_namelists.py` is also
hiding something", translated).

**Which part of ASE, and why not the rest.** ``ase.io.espresso`` has two
very different tools bundled under one name:

- ``write_espresso_in`` / the ``Espresso`` calculator: atoms-driven.
  Whenever ``nspin == 2`` (or ``noncolin``) it *unconditionally*
  recomputes every ``starting_magnetization(i)`` from
  ``atoms.get_initial_magnetic_moments()`` and overwrites whatever was
  already in ``input_data`` -- verified empirically against installed
  ase 3.28 (2026-09-14): passing
  ``{"nspin": 2, "starting_magnetization(1)": 0.55}`` through
  ``write_espresso_in`` with an ``Atoms`` carrying no magnetic moments
  silently rewrites it to ``starting_magnetization(1) = 0.0`` --
  reproducing v1's exact A2 bug (nspin=2 with implicitly-zero
  magnetization) even though ``advisors/magnetic_config.py`` already
  computed the real value. This is true *regardless* of whether
  ``atoms.set_initial_magnetic_moments`` was ever called -- the branch
  only checks the resolved ``nspin``, not how it got that way. So this
  half of ASE is not used here at all: this codebase's own
  ``magnetic_config.py`` is the only place magnetism is decided, never
  ASE's moment-guessing.
- ``ase.io.espresso_namelist.namelist.Namelist``: a plain
  ``UserDict`` subclass with zero knowledge of ``Atoms``, magnetic
  moments, or pseudopotentials. ``to_nested(binary)`` sorts a flat
  ``{keyword: value}`` dict into the right namelist section by name
  (looked up in ``ase.io.espresso_namelist.keys.ALL_KEYS``, matching a
  bracketed key like ``starting_magnetization(1)`` against its base
  keyword); ``to_string()`` formats values (``True``/``False`` ->
  ``.true.``/``.false.``, everything else via ``repr``) and preserves
  indexed keys verbatim. This is the only ASE entry point used here --
  pure formatting, no derivation, so ``advisors/magnetic_config.py``'s
  resolved ``starting_magnetization``/``angle1``/``angle2`` (already
  keyed by QE species index, see ``scf.py``) pass through unchanged.

**Floats are written to 12 significant digits** (#178). ``to_string``
writes a float's ``repr``, so float noise from upstream arithmetic
reached the input verbatim (``conv_thr = 2.8000000000000003e-09``).
``render_namelist`` rounds every float, indexed keys included, to 12
significant digits as a positive-zero Python float, whose ``repr`` is
the shortest decimal (``2.8e-09``). Nothing is snapped to zero: a
``conv_thr`` of ``1e-12`` is a legitimate request. Near-zero snapping
belongs to card geometry (``scf.py``).

**Empty sections are dropped.** ``to_nested`` always populates every
section ``ALL_KEYS['pw']`` knows about (``&IONS``/``&CELL``/``&FCP``/
``&RISM``), even when nothing was supplied for them -- confirmed
harmless to QE but pure noise for an ``scf`` calculation, which uses
none of those. ``render_namelist`` renders only the sections that
actually received a keyword.

**Unrecognized keywords are a ``GenerationError``, not a silent drop.**
``Namelist.to_nested(..., warn=True)`` only ever raises a ``UserWarning``
for a keyword matching no known ``pw.x`` section (default: silently
dropped) -- replaces v1's bare-``KeyError``-on-typo failure mode
(``generation/qe/scf.py:167,186-188,194-195,217-219``) with a named,
boundary-validated error either way, per this epic's own invariant that
generation validates at the boundary and never surfaces a raw
``KeyError``/``UserWarning`` to a caller.
"""

from __future__ import annotations

import warnings

from ase.io.espresso_namelist.namelist import Namelist

from goldilocks_core.generation.errors import GenerationError

_DEFAULT_BINARY = "pw"
_SIGNIFICANT_DIGITS = 12


def render_namelist(keywords: dict[str, object], binary: str = _DEFAULT_BINARY) -> str:
    """Render ``keywords`` (flat, QE-spelled, possibly-indexed like
    ``"starting_magnetization(1)"``) as ``binary.x`` namelist text, one
    section per namelist that actually received a keyword.

    ``binary`` selects which of ASE's ``ase.io.espresso_namelist.keys.
    ALL_KEYS`` schemas keywords are validated/sectioned against --
    defaults to ``"pw"`` (every existing caller). ``dos.x``'s ``&DOS``
    (v2 epic 9, #9) is the second binary this codebase renders: ASE's
    own registry already has its schema (``ALL_KEYS["dos"]`` --
    ``prefix``/``outdir``/``bz_sum``/``ngauss``/``degauss``/``emin``/
    ``emax``/``deltae``/``fildos``, confirmed against the installed ASE
    version 2026-09-14), a flat single-section list rather than pw.x's
    ``&CONTROL``/``&SYSTEM``/... split -- ``to_nested`` handles both
    shapes the same way, so no dos-specific branch is needed here.
    ``bands.x``'s ``&BANDS`` (#118) is the third, a single section too
    (``ALL_KEYS["bands"]``: ``prefix``/``outdir``/``filband``/
    ``spin_component``/``lsym``/...). The phonon tasks (#215) add four more
    single-section schemas: ``ph.x``'s ``&INPUTPH`` (``ALL_KEYS["ph"]``),
    and the ``&INPUT`` of ``d3hess.x``, ``q2r.x`` and ``matdyn.x``
    (``ALL_KEYS["d3hess"]``, ``["q2r"]``, ``["matdyn"]``). Each is checked
    the same way: a keyword outside the schema is refused, even one the
    program reads but the schema leaves out, such as d3hess.x's ``q_gamma``
    and q2r.x's ``prefix``, which the phonon writer leaves unset.

    Floats are written to 12 significant digits, never as ``-0.0``
    (module docstring).
    """
    if not keywords:
        raise GenerationError("no Quantum ESPRESSO namelist keywords to render")

    namelist = Namelist({key: _rounded(value) for key, value in keywords.items()})
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", UserWarning)
        namelist.to_nested(binary, warn=True)
    if caught:
        messages = "; ".join(str(warning.message) for warning in caught)
        raise GenerationError(
            f"unrecognized Quantum ESPRESSO {binary}.x namelist keyword(s): {messages}"
        )

    populated = Namelist(
        {section: values for section, values in namelist.items() if values}
    )
    if not populated:
        raise GenerationError(
            f"no keyword mapped to a known {binary}.x namelist section"
        )
    return populated.to_string()


def _rounded(value: object) -> object:
    """A float rounded to ``_SIGNIFICANT_DIGITS`` as a Python float, ``-0.0``
    as ``0.0``; any other value unchanged (``bool`` is not a float)."""
    if not isinstance(value, float):
        return value
    return float(f"{value:.{_SIGNIFICANT_DIGITS}g}") + 0.0
