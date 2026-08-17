"""Van der Waals dispersion advice policy for the Advise stage."""

from __future__ import annotations

from typing import cast

from goldilocks_core.contracts import (
    Provenance,
    StructureAnalysisRecord,
    VdwAdvice,
    VdwHints,
    VdwMethod,
)


def advise_vdw(
    analysis: StructureAnalysisRecord,
    hints: VdwHints,
) -> VdwAdvice:
    """Return vdW dispersion advice.

    User hints win. Otherwise, a connectivity-derived low-dimensional
    heuristic makes D3BJ a conservative package default because dispersion may
    be important for slabs, wires, and molecules. It does not establish that
    dispersion dominates; the operator can override the setting or method with
    ``CalculationHints``. Fully connected 3D or unknown structures get no
    correction by default.
    """
    if hints.use_vdw is not None:
        method = _resolve_vdw_method(hints) if hints.use_vdw else None
        return VdwAdvice(
            use_vdw=hints.use_vdw,
            method=method,
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided vdW dispersion setting.",
            ),
        )

    if analysis.low_dimensional:
        method = _resolve_vdw_method(hints)
        if hints.vdw_method is None:
            reason = (
                f"Low-dimensional {analysis.dimensionality} structure; D3BJ is the "
                "conservative default because dispersion may be important."
            )
        else:
            reason = (
                f"Low-dimensional {analysis.dimensionality} structure; use the "
                f"operator-provided {method} vdW method."
            )
        return VdwAdvice(
            use_vdw=True,
            method=method,
            provenance=Provenance(
                source="analysis",
                reason=reason,
            ),
        )

    warnings: tuple[str, ...] = ()
    if hints.vdw_method is not None:
        warnings = (
            f"vdw_method={hints.vdw_method!r} was ignored because vdW is off for "
            "this 3D/undetermined system; pass use_vdw=True to force it.",
        )

    return VdwAdvice(
        use_vdw=False,
        method=None,
        provenance=Provenance(
            source="default",
            reason=(
                "3D bulk or undetermined dimensionality; no vdW correction by default."
            ),
            warnings=warnings,
        ),
    )


def _resolve_vdw_method(hints: VdwHints) -> VdwMethod:
    """Return the validated vdW method, defaulting to D3BJ.

    ``CalculationHints`` validates ``vdw_method`` at construction, so the cast
    is safe.
    """
    return cast(VdwMethod, hints.vdw_method or "d3bj")
