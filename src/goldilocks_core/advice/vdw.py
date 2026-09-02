from __future__ import annotations

from typing import cast

from goldilocks_core.calculation import CalculationHints
from goldilocks_core.provenance import Provenance
from goldilocks_core.types import JsonDict, VdwMethod


def advise_vdw(
    analysis: JsonDict,
    hints: CalculationHints,
) -> JsonDict:
    """Low-dimensional structures default to D3BJ;
    3D/unknown defaults to no correction. Operator hints always win."""
    if hints.use_vdw is not None:
        method = _resolve_vdw_method(hints) if hints.use_vdw else None
        return {
            "use_vdw": hints.use_vdw,
            "method": method,
            "provenance": Provenance(
                source="user_hint",
                reason="Use the operator-provided vdW dispersion setting.",
            ),
        }

    if analysis["low_dimensional"]:
        method = _resolve_vdw_method(hints)
        reason = (
            f"Connectivity-derived {analysis['dimensionality']} classification "
            "indicates a low-dimensional heuristic; D3BJ is the "
            "conservative package default because dispersion may be important. "
            "Override with CalculationHints(use_vdw=..., vdw_method=...) as needed."
            if hints.vdw_method is None
            else (
                f"Connectivity-derived {analysis['dimensionality']} classification "
                "indicates a low-dimensional heuristic; use the "
                f"operator-provided {method} vdW method. Override with "
                "CalculationHints(use_vdw=...) as needed."
            )
        )
        return {
            "use_vdw": True,
            "method": method,
            "provenance": Provenance(
                source="analysis",
                reason=reason,
            ),
        }

    warnings: tuple[str, ...] = ()
    if hints.vdw_method is not None:
        warnings = (
            f"vdw_method={hints.vdw_method!r} was ignored because vdW is off for "
            "this 3D/undetermined system; pass use_vdw=True to force it.",
        )

    return {
        "use_vdw": False,
        "method": None,
        "provenance": Provenance(
            source="default",
            reason=(
                "3D bulk or undetermined dimensionality; no vdW correction by "
                "default. Set use_vdw=True for layered or molecular systems."
            ),
            warnings=warnings,
        ),
    }


def _resolve_vdw_method(hints: CalculationHints) -> VdwMethod:
    return cast(VdwMethod, hints.vdw_method or "d3bj")
