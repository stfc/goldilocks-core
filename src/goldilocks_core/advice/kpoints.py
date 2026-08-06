"""K-point advice policy for the Advise stage."""

from __future__ import annotations

from goldilocks_core.contracts import (
    CalculationHints,
    KPointAdvice,
    Provenance,
)

DEFAULT_K_SPACING = 0.2


def advise_k_points(hints: CalculationHints) -> KPointAdvice:
    warnings: tuple[str, ...] = ()
    if hints.k_grid is not None:
        if hints.k_spacing is not None:
            warnings = ("Both k_grid and k_spacing were provided; explicit grid wins.",)
        return KPointAdvice(
            spacing=None,
            explicit_grid=hints.k_grid,
            mesh_type="monkhorst-pack",
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided explicit k-point grid.",
                warnings=warnings,
            ),
        )

    if hints.k_spacing is not None:
        return KPointAdvice(
            spacing=hints.k_spacing,
            explicit_grid=None,
            mesh_type="monkhorst-pack",
            provenance=Provenance(
                source="user_hint",
                reason="Use the operator-provided VASP-style k-point spacing.",
            ),
        )

    return KPointAdvice(
        spacing=DEFAULT_K_SPACING,
        explicit_grid=None,
        mesh_type="monkhorst-pack",
        provenance=Provenance(
            source="default",
            reason="Use the default VASP-style k-point spacing.",
        ),
    )
