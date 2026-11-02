"""How ``explain`` and ``run`` print the gate's findings (#151)."""

from __future__ import annotations

import shlex

from goldilocks_core.checks import Finding
from goldilocks_core.cli._common import finding_lines
from goldilocks_core.set_overrides import coerce_cli_assignments, parse_set_flags


def test_each_finding_is_followed_by_the_set_flags_of_its_remedies() -> None:
    finding = Finding(
        code="relax.slab_vc_relax_needs_2d_cell_dofree",
        message="vc-relax with isolation=slab needs a 2D cell_dofree.",
        summary="s",
        fields=("cell_dofree", "isolation"),
        remedies=(
            {"cell_dofree": "2Dxy"},
            {"isolation": "periodic", "cell_dofree": None},
        ),
    )
    blocked = Finding(code="advice.blocked", message="table missing", summary="s")

    assert finding_lines([blocked, finding]) == [
        "blocked: table missing",
        "blocked: vc-relax with isolation=slab needs a 2D cell_dofree.",
        "  try: --set cell_dofree=2Dxy",
        "  try: --set isolation=periodic, remove --set cell_dofree",
    ]


def test_a_cleared_key_says_to_remove_its_set_flag() -> None:
    """--set cannot clear a key; the default comes back without it."""
    finding = Finding(
        code="nbnd.too_few_bands",
        message="nbnd=2 cannot hold 8 electrons.",
        summary="s",
        fields=("nbnd", "extra_bands"),
        remedies=(
            {"nbnd": None, "extra_bands": None},
            {"occupations": "smearing", "npool": None},
        ),
    )

    assert finding_lines([finding])[1:] == [
        "  try: remove --set nbnd and --set extra_bands",
        "  try: --set occupations=smearing, remove --set npool",
    ]


def test_set_flags_read_back_as_the_remedy_values() -> None:
    """A value prints as --set parses it: booleans and arrays as JSON,
    quoted for the shell where it needs it."""
    remedy = {"spin_polarized": True, "k_grid": [4, 4, 4], "npool": 2}
    finding = Finding(
        code="example",
        message="m",
        summary="s",
        fields=tuple(remedy),
        remedies=(remedy,),
    )

    (_, line) = finding_lines([finding])
    flags = shlex.split(line.removeprefix("  try: "))

    assert flags == [
        "--set",
        "spin_polarized=true",
        "--set",
        "k_grid=[4, 4, 4]",
        "--set",
        "npool=2",
    ]
    assert coerce_cli_assignments(parse_set_flags(flags[1::2])) == remedy
