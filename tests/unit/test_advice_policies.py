"""Injectable AdvicePolicies swap tests."""

from __future__ import annotations

from goldilocks_core.advice import AdvicePolicies, advise_parameters
from goldilocks_core.contracts import (
    CalculationHints,
    MagnetismAdvice,
    Provenance,
    StructureAnalysisRecord,
)


def make_analysis() -> StructureAnalysisRecord:
    """Build a minimal analysis record for policy-swap tests."""
    return StructureAnalysisRecord(
        formula="Si1",
        reduced_formula="Si",
        site_count=1,
        elements=("Si",),
        contains_transition_metals=False,
        contains_lanthanides=False,
        contains_actinides=False,
        contains_heavy_elements=False,
        magnetic_elements=(),
        heavy_elements=(),
        electronic_character="unknown",
        dimensionality="unknown",
        has_vacuum=False,
    )


def test_swap_magnetism_policy_without_touching_others() -> None:
    """A single policy is swappable via AdvicePolicies without rewriting advice."""
    policies = AdvicePolicies(
        magnetism=lambda analysis, hints: MagnetismAdvice(
            spin_polarized=True,
            magnetic_elements=("Fe",),
            provenance=Provenance(source="user_hint", reason="stub"),
        ),
    )

    result = advise_parameters(
        make_analysis(),
        hints=CalculationHints(),
        policies=policies,
    )

    assert result.magnetism.spin_polarized is True
    assert result.magnetism.magnetic_elements == ("Fe",)
    assert result.magnetism.provenance.source == "user_hint"
    # Untouched policies still run with the built-in backends.
    assert result.k_points.provenance.source == "default"
    assert result.convergence.provenance.source == "default"
