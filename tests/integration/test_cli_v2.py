"""Integration tests for the v2 CLI (v2 epic 8, #8), replacing
``test_cli_interface.py``: that file tested v1's ``compute``/
``capabilities``/preset/record-selection/model-legal-metadata surface,
none of which exists in the design doc's 6-command shape this rewrite
replaces it with (issue #8's own "v1 concepts this epic replaces"
section). Kept as a real subprocess-spawning integration suite, same
style as the file it replaces: ``goldilocks_core.cli.core:main`` is the
actual ``[project.scripts]`` entry point, so this is the only test
layer that exercises real argument parsing end to end.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure
from support import (
    run_cli as _run_cli,
    sssp_fixture_table_spec,
    strict_json,
    write_registry,
)

from goldilocks_core.advisors.magnetic_enumeration import enumlib_installed
from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.bundle import bundle_files
from goldilocks_core.capabilities import capabilities
from goldilocks_core.examples.structures import structure
from goldilocks_core.server import _handlers
from goldilocks_core.server.documents import ComputeRequestDocument


def test_help_lists_the_design_docs_commands() -> None:
    completed = _run_cli("--help")

    assert completed.returncode == 0, completed.stderr
    for command in (
        "run",
        "explain",
        "inspect",
        "settings",
        "capabilities",
        "models",
        "assets",
        "examples",
        "serve",
    ):
        assert command in completed.stdout


def test_serve_http_help_lists_static_root() -> None:
    """#59: restores the flag ``poe stage``/the README's local-dev
    instructions already assumed exists. Real end-to-end verification
    (a running server actually serving a built Workbench directory) was
    done manually, not here -- `serve http` blocks forever, so a
    subprocess integration test can only prove the flag parses, not
    that the server behaves correctly once it does."""
    completed = _run_cli("serve", "http", "--help")

    assert completed.returncode == 0, completed.stderr
    assert "--static-root" in completed.stdout


def test_inspect_reports_structure_in_json_and_human_forms() -> None:
    silicon = structure("Si.cif")

    human = _run_cli("inspect", str(silicon))
    assert human.returncode == 0, human.stderr
    assert "formula: Si" in human.stdout

    as_json = _run_cli("inspect", str(silicon), "--json")
    assert as_json.returncode == 0, as_json.stderr
    document = json.loads(as_json.stdout)
    assert document["structure"]["reduced_formula"] == "Si"


def test_inspect_prints_the_site_labels_starting_magnetization_takes(
    tmp_path: Path,
) -> None:
    """#185: the keys a starting_magnetization takes are discoverable
    before a request fails: the CIF's own site labels, in site order."""
    nio = Structure(
        Lattice.from_parameters(2.95, 2.95, 2.95, 60, 60, 60),
        ["Ni", "O"],
        [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]],
        labels=["Ni1", "O1"],
    )
    path = tmp_path / "NiO.cif"
    path.write_text(nio.to(fmt="cif"), encoding="utf-8")

    completed = _run_cli("inspect", str(path))

    assert completed.returncode == 0, completed.stderr
    assert "site labels: Ni1, O1\n" in completed.stdout


def test_inspect_missing_structure_is_an_operator_error_not_a_traceback() -> None:
    completed = _run_cli("inspect", "/no/such/structure.cif")

    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr
    assert "not found" in completed.stderr


def test_a_disordered_structure_is_refused_but_still_inspected(tmp_path) -> None:
    """#224: rock-salt Fe0.5Ni0.5O exits 2 with its partially occupied sites
    named, from explain, run and magnetic-orderings alike, where explain and
    run used to end in a traceback from the ML tiers. inspect still reads it,
    occupancies included."""
    path = tmp_path / "feni_o.cif"
    Structure.from_spacegroup(
        "Fm-3m",
        Lattice.cubic(4.2),
        [{"Fe": 0.5, "Ni": 0.5}, "O"],
        [[0, 0, 0], [0.5, 0, 0]],
    ).to(filename=str(path))

    for command in (
        ("explain", "--hpc", "scarf"),
        ("run", "--hpc", "scarf"),
        ("magnetic-orderings",),
    ):
        refused = _run_cli(*command, str(path))
        assert refused.returncode == 2, (command, refused.stderr)
        assert "Traceback" not in refused.stderr
        assert "partially occupied sites" in refused.stderr
        assert "site 1 (Fe0.5 Ni0.5)" in refused.stderr

    inspected = _run_cli("inspect", str(path), "--json")
    assert inspected.returncode == 0, inspected.stderr
    site = json.loads(inspected.stdout)["structure"]["sites"][0]
    assert [species["occupancy"] for species in site["species"]] == [0.5, 0.5]


def test_magnetic_orderings_lists_the_fm_identity_by_default() -> None:
    """The fm candidate is always listed first, regardless of whatever
    else enumlib (if present on this machine's real PATH -- this
    subprocess inherits it, unlike an in-process monkeypatch) finds for
    bcc Fe -- #87's listing never picks a winner on its own."""
    iron = structure("Fe_bcc.cif")

    completed = _run_cli("magnetic-orderings", str(iron))

    assert completed.returncode == 0, completed.stderr
    assert "fm" in completed.stdout


def test_magnetic_orderings_json_reports_every_candidate() -> None:
    iron = structure("Fe_bcc.cif")

    completed = _run_cli("magnetic-orderings", str(iron), "--json")

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert document["ranked"] is False
    assert document["candidates"][0]["label"] == "fm"
    assert document["candidates"][0]["formula"] == "Fe"
    assert document["candidates"][0]["energy_per_atom_ev"] is None
    # #170: each candidate is generated by `run <structure> --set
    # magnetic_ordering=<label>`; none carries a structure of its own.
    for candidate in document["candidates"]:
        assert candidate["overrides"] == {"magnetic_ordering": candidate["label"]}
        assert "structure_content" not in candidate


def test_magnetic_orderings_rank_degrades_without_a_configured_checkpoint(
    monkeypatch,
) -> None:
    """``--rank-with-mmace`` without ``GOLDILOCKS_MACE_BACKBONE`` configured
    (the real state of this test machine, and of CI) reports the
    candidates unranked with a warning, not a failure."""
    monkeypatch.delenv("GOLDILOCKS_MACE_BACKBONE", raising=False)
    iron = structure("Fe_bcc.cif")

    completed = _run_cli("magnetic-orderings", str(iron), "--rank-with-mmace", "--json")

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert document["ranked"] is False
    # Not an exact warnings count: this subprocess inherits the real
    # machine's PATH, so whether AFM enumeration also warns
    # (magnetic.afm_ordering_unavailable) depends on whether enum.x
    # happens to be installed here -- only ranking degradation is this
    # test's own concern.
    codes = {warning["code"] for warning in document["warnings"]}
    assert "magnetic.ordering_ranking_unavailable" in codes


def test_settings_json_matches_the_capabilities_contract() -> None:
    """Every --set-able key: capabilities' settings[] and its overridable
    facts[] (#139), the same objects /capabilities publishes."""
    completed = _run_cli("settings", "--json")

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    caps = capabilities()
    assert document == {
        "settings": caps["settings"],
        "facts": [fact for fact in caps["facts"] if fact["overridable"]],
    }
    keys = {setting["key"] for setting in document["settings"]}
    assert "functional" in keys
    assert "ecutwfc_ry" in keys
    facts = {fact["key"]: fact for fact in document["facts"]}
    assert facts["is_metal"]["values"] == ["metal", "non_metal"]
    assert facts["is_magnetic"]["values"] == ["magnetic", "non_magnetic"]


def test_settings_human_output_lists_sources() -> None:
    completed = _run_cli("settings")

    assert completed.returncode == 0, completed.stderr
    assert "sources: human . heuristic" in completed.stdout


def test_settings_human_output_names_the_steps_a_setting_applies_to() -> None:
    """#154: a step setting lists the steps ``steps.<step>.KEY`` can name;
    a task-level setting (the job's walltime) lists none."""
    completed = _run_cli("settings")

    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    press = lines.index("press [relax] number (default 0.0)")
    assert lines[press + 2] == "  steps: vc-relax"
    delta_e = lines.index("delta_e [dos] number")
    assert lines[delta_e + 2] == "  steps: dos"
    walltime = lines.index("walltime_h [job] number")
    assert not lines[walltime + 2].startswith("  steps:")


def test_settings_human_output_lists_the_facts_and_their_values() -> None:
    """#139: is_metal/is_magnetic are --set-able, but `goldilocks settings`,
    which an unknown key points to, never listed them or their values."""
    completed = _run_cli("settings")

    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    is_metal = lines.index("is_metal [analysis] enum")
    assert lines[is_metal + 1] == "  values: metal, non_metal"
    is_magnetic = lines.index("is_magnetic [analysis] enum")
    assert lines[is_magnetic + 1] == "  values: magnetic, non_magnetic"
    assert "needs_correlation [analysis] boolean" in lines
    # #186: needs_soc is advice, not a --set key.
    assert not any(line.startswith("needs_soc ") for line in lines)


def test_capabilities_json_matches_the_real_capabilities_payload() -> None:
    """#62: the CLI must be a thin third entry point onto the same
    ``capabilities()`` HTTP's ``GET /capabilities`` and MCP's
    ``capabilities`` tool already call, not a re-derived subset."""
    completed = _run_cli("capabilities", "--json")

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == capabilities()


def test_capabilities_human_output_summarizes_every_section() -> None:
    completed = _run_cli("capabilities")

    assert completed.returncode == 0, completed.stderr
    for expected in (
        "core_version:",
        "code: quantum_espresso",
        "task: scf_single_point",
        "task: dos",
        "pseudopotential_table:",
        "hpc_profile:",
        "warnings:",
    ):
        assert expected in completed.stdout


def test_models_list_reports_every_registered_model() -> None:
    """v2 epic 11 (#11): models[] lists what registry.toml declares
    regardless of install status (an isolated, per-test asset root has
    nothing installed) -- "is it actually usable" lives in a fact's own
    ``approaches`` instead, not here."""
    completed = _run_cli("models", "--json", "list")

    assert completed.returncode == 0, completed.stderr
    ids = {model["id"] for model in json.loads(completed.stdout)}
    assert ids == {
        "models/qrf-kpoints",
        "models/metallicity-cgcnn",
        "models/is-metal-classifier",
        "models/is-magnetic-classifier",
    }


def test_assets_status_prints_the_asset_root() -> None:
    completed = _run_cli("assets", "status")

    assert completed.returncode == 0, completed.stderr
    assert "asset root:" in completed.stdout


def test_assets_status_json_carries_asset_root_and_a_list() -> None:
    completed = _run_cli("assets", "status", "--json")

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert document["asset_root"]  # isolated per-test root; just non-empty
    assert isinstance(document["assets"], list)


def test_examples_path_prints_a_real_directory() -> None:
    completed = _run_cli("examples", "path")

    assert completed.returncode == 0, completed.stderr
    assert Path(completed.stdout.strip()).is_dir()


def test_examples_path_json_carries_the_same_directory() -> None:
    completed = _run_cli("examples", "path", "--json")

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert Path(document["path"]).is_dir()


# Runs the real CLI with structure loading wrapped in a stand-in for a
# library that prints mid-command, as mace does when it is first imported
# (#183): through Python's sys.stdout, straight to fd 1, through C stdio
# (buffered until the process exits), and from a child process that
# inherits fd 1.
_NOISY_LIBRARY_DRIVER = """
import ctypes
import os
import subprocess
import sys

from goldilocks_core.cli import _common, core

real_normalize_structure = _common.normalize_structure


def noisy_normalize_structure(source):
    print("python stdout marker")
    os.write(1, b"fd 1 marker\\n")
    ctypes.CDLL(None).printf(b"c stdio marker\\n")
    subprocess.run([sys.executable, "-c", "print('child process marker')"], check=True)
    return real_normalize_structure(source)


_common.normalize_structure = noisy_normalize_structure
core.main()
"""
_NOISE_MARKERS = (
    "python stdout marker",
    "fd 1 marker",
    "c stdio marker",
    "child process marker",
)


@pytest.mark.parametrize(
    ("command", "example", "document_key"),
    [
        ("explain", "Si.cif", "records"),
        ("magnetic-orderings", "Fe_bcc.cif", "candidates"),
    ],
)
def test_json_stdout_is_only_the_document_when_a_library_prints(
    command: str, example: str, document_key: str, tmp_path: Path
) -> None:
    """Library output lands on stderr, never in the ``--json`` document."""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            _NOISY_LIBRARY_DRIVER,
            command,
            str(structure(example)),
            "--json",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    document = json.loads(completed.stdout)
    assert document_key in document
    assert completed.stdout == json.dumps(document, indent=2, sort_keys=True) + "\n"
    stderr = completed.stderr
    assert all(marker in stderr for marker in _NOISE_MARKERS), stderr
    # A Python print reaches stderr when it happens, not when stdout's
    # buffer is flushed at exit.
    assert stderr.index("python stdout marker") < stderr.index("child process marker")


def test_serve_mcp_answers_initialize_on_stdout() -> None:
    """``serve`` runs outside the CLI's stdout redirect: MCP's stdio
    transport takes fd 1 for JSON-RPC only while ``sys.stdout`` is fd 1."""
    pytest.importorskip("mcp")
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "goldilocks-tests", "version": "0"},
        },
    }

    completed = subprocess.run(
        [sys.executable, "-m", "goldilocks_core.cli.core", "serve", "mcp"],
        input=json.dumps(initialize) + "\n",
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert len(lines) == 1, completed.stderr
    response = json.loads(lines[0])
    assert response["id"] == 1
    assert response["result"]["serverInfo"]["name"] == "goldilocks-core"


def test_unknown_set_key_is_a_did_you_mean_operator_error() -> None:
    silicon = structure("Si.cif")

    completed = _run_cli("run", str(silicon), "--hpc", "scarf", "--set", "ecutwf_ry=30")

    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr
    assert "did you mean: ecutwfc_ry" in completed.stderr


def test_a_quantum_espresso_isolation_spelling_lists_the_allowed_values() -> None:
    """#161: isolation takes the code-neutral category; '2D' is what the
    writer emits for 'slab'."""
    silicon = structure("Si.cif")

    completed = _run_cli(
        "explain", str(silicon), "--hpc", "scarf", "--set", "isolation=2D"
    )

    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr
    assert "'periodic', 'slab' or 'isolated'" in completed.stderr


def test_unknown_hpc_profile_is_an_operator_error() -> None:
    silicon = structure("Si.cif")

    completed = _run_cli("explain", str(silicon), "--hpc", "does-not-exist")

    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr


def test_explain_json_is_strict_json_for_a_gamma_only_mesh() -> None:
    """Rung 1's open k-distance bound prints as null, never Infinity
    (#137). Rung 1 of Si.cif's ladder (cubic, a = 5.431 A) is every
    k-distance above |b| = 2 pi / a. No real assets needed: explain
    reports every record either way."""
    silicon = structure("Si.cif")

    completed = _run_cli(
        "explain", str(silicon), "--hpc", "scarf", "--set", "k_grid=[1,1,1]", "--json"
    )

    assert completed.returncode == 0, completed.stderr
    k_sampling = strict_json(completed.stdout)["records"]["k_sampling"]["value"]
    assert k_sampling["k_index"] == 1
    assert k_sampling["k_distance_interval"] == [round(2 * math.pi / 5.431, 8), None]


def test_a_non_finite_set_value_is_an_operator_error() -> None:
    """``1e999`` parses as inf: an invalid setting, not a k-distance (#137)."""
    silicon = structure("Si.cif")

    completed = _run_cli(
        "explain", str(silicon), "--hpc", "scarf", "--set", "k_distance=1e999"
    )

    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr
    assert "finite number" in completed.stderr


def test_a_metallicity_override_takes_the_advertised_label() -> None:
    """#139: `--set is_metal=non_metal`, a value capabilities advertises,
    exited 2 with "is not a boolean (true/false)". explain reports the
    record without real assets."""
    silicon = structure("Si.cif")

    completed = _run_cli(
        "explain", str(silicon), "--hpc", "scarf", "--set", "is_metal=non_metal"
    )

    assert completed.returncode == 0, completed.stderr
    assert "is_metal: 'non_metal' (source=human)" in completed.stdout


def test_a_boolean_metallicity_override_is_an_operator_error() -> None:
    silicon = structure("Si.cif")

    completed = _run_cli(
        "explain", str(silicon), "--hpc", "scarf", "--set", "is_metal=false"
    )

    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr
    assert "'metal' or 'non_metal'" in completed.stderr


def test_blocked_pipeline_reports_deduplicated_reasons_and_exits_nonzero() -> None:
    """No real assets needed: an unknown pseudo_table_id fails inside
    the bundled registry lookup, before ever touching the asset store."""
    silicon = structure("Si.cif")

    completed = _run_cli(
        "run",
        str(silicon),
        "--hpc",
        "scarf",
        "--set",
        "pseudo_table_id=does-not-exist",
    )

    assert completed.returncode == 2
    lines = [
        line for line in completed.stderr.splitlines() if line.startswith("blocked:")
    ]
    assert len(lines) == 1, completed.stderr
    assert "does-not-exist" in lines[0]


@pytest.mark.parametrize(
    ("task_arguments", "expected"),
    [
        pytest.param([], [("is not installed", [])], id="scf"),
        pytest.param(["--task", "dos"], [("is not installed", [])], id="dos"),
        pytest.param(["--task", "band"], [("is not installed", [])], id="band"),
        pytest.param(
            ["--task", "vc-relax", "--set", "ion_dynamics=damp"],
            [
                ("is not installed", []),
                (
                    "vc-relax is generated only with ion_dynamics=bfgs",
                    ["  try: --set ion_dynamics=bfgs"],
                ),
            ],
            id="vc-relax",
        ),
        pytest.param(
            ["--task", "phonon"],
            [
                ("is not installed", []),
                (
                    "The phonon tasks need this structure on fixed occupations, or "
                    "confirmed as a metal",
                    ["  try: --set is_metal=non_metal", "  try: --set is_metal=metal"],
                ),
            ],
            id="phonon",
        ),
        pytest.param(
            [
                "--task",
                "relax-phonon",
                "--set",
                "is_metal=non_metal",
                "--set",
                "fix_bottom_layers=1",
            ],
            [
                ("is not installed", []),
                (
                    "fix_bottom_layers=1 pins atoms in the relaxation",
                    ["  try: remove --set fix_bottom_layers"],
                ),
            ],
            id="relax-phonon",
        ),
        pytest.param(
            ["--task", "vc-relax-phonon", "--set", "is_metal=non_metal"],
            [("is not installed", [])],
            id="vc-relax-phonon",
        ),
    ],
)
def test_explain_reports_the_reasons_run_refuses_with_and_still_exits_zero(
    task_arguments: list[str], expected: list[tuple[str, list[str]]]
) -> None:
    """#165: no real assets, so the isolated asset root's uninstalled
    default table is a deterministic blocker (vc-relax adds its named
    check rule, and the phonon task, run on Si without is_metal, which no
    model decides here, its metallicity rule). explain prints run's verdict
    (diagnosis output, on stdout) and still exits 0; run refuses with the
    same lines on stderr: each finding's message, then one ``try:`` line per
    remedy (#151)."""
    arguments = [str(structure("Si.cif")), "--hpc", "scarf", *task_arguments]

    as_json = _run_cli("explain", *arguments, "--json")
    as_text = _run_cli("explain", *arguments)
    refused = _run_cli("run", *arguments)

    assert as_json.returncode == 0, as_json.stderr
    blocking = json.loads(as_json.stdout)["blocking"]
    assert len(blocking) == len(expected)
    lines = []
    for finding, (fragment, remedies) in zip(blocking, expected, strict=True):
        assert fragment in finding["message"]
        lines += [f"blocked: {finding['message']}", *remedies]
    assert as_text.returncode == 0, as_text.stderr
    assert refused.returncode == 2
    assert as_text.stdout.splitlines()[-len(lines) :] == lines
    assert refused.stderr.splitlines()[-len(lines) :] == lines


@pytest.mark.parametrize(
    ("task_arguments", "remedy"),
    [
        pytest.param(
            ["--task", "relax", "--set", "fix_bottom_layers=1"],
            "  try: remove --set fix_bottom_layers",
            id="clear",
        ),
        pytest.param(
            ["--task", "vc-relax", "--set", "cell_dofree=2Dxy"],
            "  try: --set cell_dofree=all",
            id="set",
        ),
    ],
)
def test_a_refused_run_names_the_override_that_resolves_it(
    task_arguments: list[str], remedy: str, tmp_path: Path
) -> None:
    """#151: each finding is followed by the --set flags of its remedies,
    and --set cannot clear a key, so a remedy that clears one says to remove
    that --set. No real assets: these rules read the written cell, which
    needs no pseudopotential. Diamond Si's primitive cell has no vacuum and
    a and b out of the xy plane."""
    path = tmp_path / "Si-primitive.cif"
    Structure(
        Lattice([[0, 2.7155, 2.7155], [2.7155, 0, 2.7155], [2.7155, 2.7155, 0]]),
        ["Si", "Si"],
        [[0, 0, 0], [0.25, 0.25, 0.25]],
    ).to(filename=str(path))

    refused = _run_cli("run", str(path), "--hpc", "scarf", *task_arguments)

    assert refused.returncode == 2
    lines = refused.stderr.splitlines()
    assert remedy in lines
    assert lines[lines.index(remedy) - 1].startswith("blocked: ")


class TestRunAndExplainAgainstRealAssets:
    """Skips itself when the default pseudopotential profile isn't
    installed (same convention as test_docs_executable.py's
    real_assets fixture) -- these are the only tests in this file that
    need a real, resolvable pseudopotential."""

    def test_explain_prints_every_decision_with_its_source(
        self, real_assets: None
    ) -> None:
        silicon = structure("Si.cif")

        completed = _run_cli("explain", str(silicon), "--hpc", "scarf")

        assert completed.returncode == 0, completed.stderr
        assert "functional: 'PBEsol' (source=heuristic)" in completed.stdout
        # v2 epic 11 (#11): the real, installed CGCNN classifier resolves
        # Si confidently (elemental Si gives composition-only heuristics
        # nothing to exclude, so that tier alone would say unavailable --
        # ml is strictly more capable here, not a fallback).
        assert "is_metal: 'non_metal' (source=ml)" in completed.stdout

    def test_explain_json_carries_a_structured_top_level_warnings_array(
        self, real_assets: None
    ) -> None:
        """Matches HTTP/MCP's own ``/explain`` shape
        (``{"records", "warnings", "blocking", "layout"}``) -- v2 epic 8's own
        "warnings array in every CLI/HTTP/MCP response" requirement, and the
        tier and step of every record (#187)."""
        silicon = structure("Si.cif")

        completed = _run_cli("explain", str(silicon), "--hpc", "scarf", "--json")

        assert completed.returncode == 0, completed.stderr
        document = json.loads(completed.stdout)
        assert document.keys() == {"records", "warnings", "blocking", "layout"}
        assert document["blocking"] == []
        assert [step["name"] for step in document["layout"]["steps"]] == ["scf"]
        assert document["warnings"]
        assert any(
            warning["code"] == "job.walltime_defaulted"
            for warning in document["warnings"]
        )
        assert all(
            warning.keys() == {"code", "level", "category", "message", "record"}
            for warning in document["warnings"]
        )

    def test_run_with_an_npool_that_does_not_divide_ntasks_says_to_remove_it(
        self, real_assets: None
    ) -> None:
        """#151: npool=7 never divides scarf's 64 tasks; the default does."""
        silicon = structure("Si.cif")

        completed = _run_cli("run", str(silicon), "--hpc", "scarf", "--set", "npool=7")

        assert completed.returncode == 2
        # mace's own import notices reach stderr too, from the is_magnetic
        # worker, at no fixed position (docs/mmace-setup.md).
        lines = completed.stderr.splitlines()
        blocked = lines.index(
            "blocked: npool=7 does not divide ntasks=64, and pw.x refuses that "
            "layout. Unset npool for the default, or set npool to a divisor of "
            "ntasks."
        )
        assert lines[blocked + 1] == "  try: remove --set npool"

    def test_run_without_out_previews_without_touching_disk(
        self, real_assets: None, tmp_path: Path
    ) -> None:
        silicon = structure("Si.cif")

        completed = _run_cli("run", str(silicon), "--hpc", "scarf", cwd=tmp_path)

        assert completed.returncode == 0, completed.stderr
        assert "memory-only preview" in completed.stdout
        assert "scf.in" in completed.stdout
        assert list(tmp_path.iterdir()) == []

    def test_explain_dos_task_reports_nscf_prefixed_records(
        self, real_assets: None
    ) -> None:
        """v2 epic 9 (#9, #28): --task dos used to be silently accepted
        and ignored by every delivery layer -- this confirms it now
        actually routes to advise_dos through the real CLI subprocess."""
        silicon = structure("Si.cif")

        completed = _run_cli(
            "explain", str(silicon), "--hpc", "scarf", "--task", "dos", "--json"
        )

        assert completed.returncode == 0, completed.stderr
        records = json.loads(completed.stdout)["records"]
        # v2 epic 11 (#11): the real, installed CGCNN classifier now
        # resolves Si confidently non-metal (source=ml), so the scf
        # step's own occupations correctly follows the non-metal branch
        # -- unlike nscf_occupations below, which dos's own advisor
        # always pins to tetrahedra_opt regardless of metallicity.
        assert records["occupations"]["value"]["occupations"] == "fixed"
        assert records["nscf_occupations"]["value"]["occupations"] == ("tetrahedra_opt")
        assert records["dos"]["value"]["delta_e"] == 0.01

    def test_run_dos_task_publishes_all_three_steps(
        self, real_assets: None, tmp_path: Path
    ) -> None:
        silicon = structure("Si.cif")
        destination = tmp_path / "out"

        completed = _run_cli(
            "run",
            str(silicon),
            "--hpc",
            "scarf",
            "--task",
            "dos",
            "-o",
            str(destination),
        )

        assert completed.returncode == 0, completed.stderr
        assert (destination / "scf.in").exists()
        assert (destination / "nscf.in").exists()
        assert (destination / "dos.in").exists()
        assert (destination / "submit.sh").exists()

    def test_explain_relax_task_reports_the_relax_record(
        self, real_assets: None
    ) -> None:
        """v2 epic 10 (#10): confirms --task relax actually routes to
        advise_relax through the real CLI subprocess, the same
        end-to-end check #28 added for --task dos."""
        silicon = structure("Si.cif")

        completed = _run_cli(
            "explain", str(silicon), "--hpc", "scarf", "--task", "relax", "--json"
        )

        assert completed.returncode == 0, completed.stderr
        records = json.loads(completed.stdout)["records"]
        assert records["relax"]["value"]["ion_dynamics"] == "bfgs"

    def test_run_relax_task_publishes_relax_in(
        self, real_assets: None, tmp_path: Path
    ) -> None:
        silicon = structure("Si.cif")
        destination = tmp_path / "out"

        completed = _run_cli(
            "run",
            str(silicon),
            "--hpc",
            "scarf",
            "--task",
            "relax",
            "-o",
            str(destination),
        )

        assert completed.returncode == 0, completed.stderr
        assert (destination / "relax.in").exists()
        content = (destination / "relax.in").read_text()
        assert "calculation      = 'relax'" in content

    def test_run_vc_relax_task_publishes_vc_relax_in(
        self, real_assets: None, tmp_path: Path
    ) -> None:
        silicon = structure("Si.cif")
        destination = tmp_path / "out"

        completed = _run_cli(
            "run",
            str(silicon),
            "--hpc",
            "scarf",
            "--task",
            "vc-relax",
            "-o",
            str(destination),
        )

        assert completed.returncode == 0, completed.stderr
        assert (destination / "vc-relax.in").exists()
        content = (destination / "vc-relax.in").read_text()
        assert "calculation      = 'vc-relax'" in content
        assert "&CELL" in content

    def test_set_nstep_reaches_the_generated_relax_input(
        self, real_assets: None, tmp_path: Path
    ) -> None:
        """Regression-shaped guard, same class of bug #34 fixed for
        other settings: an accepted --set must actually reach the
        rendered file, not just validate and get dropped."""
        silicon = structure("Si.cif")
        destination = tmp_path / "out"

        completed = _run_cli(
            "run",
            str(silicon),
            "--hpc",
            "scarf",
            "--task",
            "relax",
            "--set",
            "nstep=123",
            "-o",
            str(destination),
        )

        assert completed.returncode == 0, completed.stderr
        content = (destination / "relax.in").read_text()
        assert "nstep            = 123" in content

    def test_explain_band_task_reports_bands_prefixed_records(
        self, real_assets: None
    ) -> None:
        """#118: --task band routes to advise_band: the bands step's path is
        published as k_path and its other decisions under bands_ names, and
        the 8-atom cubic Si.cif gets the fcc path, folded."""
        silicon = structure("Si.cif")

        completed = _run_cli(
            "explain", str(silicon), "--hpc", "scarf", "--task", "band", "--json"
        )

        assert completed.returncode == 0, completed.stderr
        document = json.loads(completed.stdout)
        path = document["records"]["k_path"]["value"]
        assert (path["lattice_type"], path["primitive_cells"]) == ("FCC", 4)
        assert document["records"]["bands_nbnd"]["status"] == "resolved"
        assert document["blocking"] == []
        assert [step["name"] for step in document["layout"]["steps"]] == [
            "scf",
            "bands",
        ]

    def test_run_band_task_publishes_every_step(
        self, real_assets: None, tmp_path: Path
    ) -> None:
        silicon = structure("Si.cif")
        destination = tmp_path / "out"

        completed = _run_cli(
            "run",
            str(silicon),
            "--hpc",
            "scarf",
            "--task",
            "band",
            "-o",
            str(destination),
        )

        assert completed.returncode == 0, completed.stderr
        for name in ("scf.in", "bands.in", "bands_x.in", "submit.sh"):
            assert (destination / name).exists(), name
        assert "calculation      = 'bands'" in (destination / "bands.in").read_text()

    def test_explain_vc_relax_phonon_reports_every_step_s_records(
        self, real_assets: None
    ) -> None:
        """#215: --task vc-relax-phonon routes to advise_phonon: the vc-relax
        step relaxes to the phonon protocol's 1e-4, and the ph, q2r,
        phonon_dos and dispersion steps follow it in the layout."""
        silicon = structure("Si.cif")

        completed = _run_cli(
            "explain",
            str(silicon),
            "--hpc",
            "scarf",
            "--task",
            "vc-relax-phonon",
            "--json",
        )

        assert completed.returncode == 0, completed.stderr
        document = json.loads(completed.stdout)
        records = document["records"]
        assert records["relax"]["value"]["forc_conv_thr"] == 1e-4
        assert records["q_sampling"]["value"]["mesh"] == [4, 4, 4]
        assert document["blocking"] == []
        assert [step["name"] for step in document["layout"]["steps"]] == [
            "vc-relax",
            "ph",
            "q2r",
            "phonon_dos",
            "dispersion",
        ]

    @pytest.mark.parametrize(
        ("task", "first_step"),
        [("phonon", "scf"), ("relax-phonon", "relax"), ("vc-relax-phonon", "vc-relax")],
    )
    def test_run_phonon_task_publishes_every_step(
        self, real_assets: None, tmp_path: Path, task: str, first_step: str
    ) -> None:
        silicon = structure("Si.cif")
        destination = tmp_path / "out"

        completed = _run_cli(
            "run",
            str(silicon),
            "--hpc",
            "scarf",
            "--task",
            task,
            "-o",
            str(destination),
        )

        assert completed.returncode == 0, completed.stderr
        for name in (
            f"{first_step}.in",
            "ph.in",
            "q2r.in",
            "phonon_dos.in",
            "dispersion.in",
            "submit.sh",
        ):
            assert (destination / name).exists(), name
        assert "ldisp            = .true." in (destination / "ph.in").read_text()
        dispersion = (destination / "dispersion.in").read_text()
        assert "q_in_band_form   = .true." in dispersion

    def test_unknown_task_is_an_operator_error_not_a_silent_fallback(self) -> None:
        silicon = structure("Si.cif")

        completed = _run_cli(
            "run", str(silicon), "--hpc", "scarf", "--task", "no_such_task"
        )

        assert completed.returncode == 2
        assert "Traceback" not in completed.stderr

    def test_run_with_out_publishes_a_complete_bundle(
        self, real_assets: None, tmp_path: Path
    ) -> None:
        silicon = structure("Si.cif")
        destination = tmp_path / "out"

        completed = _run_cli(
            "run", str(silicon), "--hpc", "scarf", "-o", str(destination)
        )

        assert completed.returncode == 0, completed.stderr
        assert (destination / ".complete").exists()
        assert (destination / "scf.in").exists()
        assert (destination / "submit.sh").exists()
        manifest = json.loads((destination / "goldilocks.json").read_text())
        assert manifest["records"]["functional"]["value"] == "PBEsol"
        assert any(
            warning["code"] == "job.walltime_defaulted"
            for warning in manifest["warnings"]
        )

    @pytest.mark.skipif(
        not enumlib_installed(),
        reason="needs the enumlib executables (enum.x, makeStr.py) on PATH",
    )
    def test_run_afm_ordering_publishes_without_crashing(
        self, real_assets: None, tmp_path: Path
    ) -> None:
        """Regression for #27: an AFM-relabeled structure used to crash
        ``goldilocks run`` with an uncaught ``KeyError`` (write_qe_scf
        looked up QE species labels in a dict keyed by real elements) --
        this reproduces the exact failing case through the real CLI
        subprocess, not just the writer function in isolation.

        The applied AFM cell has 4 sites against the uploaded 2, and the
        deck is counted on it: neutral, with no ``tot_charge`` (#128)."""
        rock_salt_feo = tmp_path / "FeO.cif"
        Structure(
            Lattice.cubic(4.3), ["Fe", "O"], [[0.0, 0.0, 0.0], [0.5, 0.5, 0.5]]
        ).to(filename=str(rock_salt_feo))
        destination = tmp_path / "out"

        completed = _run_cli(
            "run",
            str(rock_salt_feo),
            "--hpc",
            "scarf",
            "--set",
            "magnetic_ordering=afm",
            "--set",
            "hubbard_needs_correlation=false",
            "-o",
            str(destination),
        )

        assert completed.returncode == 0, completed.stderr
        content = (destination / "scf.in").read_text()
        assert "ntyp             = 3" in content
        assert "nat              = 4" in content
        assert "tot_charge" not in content
        assert "  Fe1  " in content
        assert "  Fe2  " in content

    def test_run_default_magnetic_structure_publishes_without_crashing(
        self, real_assets: None, tmp_path: Path
    ) -> None:
        """Regression for #32: the bundled Fe_bcc.cif example (like every
        structure loaded through pymatgen's own CIF reader) carries
        per-site labels ('Fe0'/'Fe1') distinct from its element symbol
        ('Fe') even with zero --set flags and no AFM relabeling -- this
        used to crash goldilocks run with an uncaught KeyError on the
        plain default heuristic path, a regression #27 introduced while
        fixing the AFM-specific case.

        Both sites get the identical heuristic-default fraction (no AFM
        requested), so generation collapses 'Fe0'/'Fe1' back to one 'Fe'
        species with one shared starting_magnetization -- not two
        redundant, identically-valued ATOMIC_SPECIES entries just because
        the source CIF happened to label its two sites separately."""
        destination = tmp_path / "out"

        completed = _run_cli(
            "run",
            str(structure("Fe_bcc.cif")),
            "--hpc",
            "scarf",
            "-o",
            str(destination),
        )

        assert completed.returncode == 0, completed.stderr
        content = (destination / "scf.in").read_text()
        assert "ntyp             = 1" in content
        assert "starting_magnetization(1)" in content
        assert "starting_magnetization(2)" not in content

    def test_run_json_output_is_stable_and_sorted(self, real_assets: None) -> None:
        silicon = structure("Si.cif")

        completed = _run_cli("run", str(silicon), "--hpc", "scarf", "--json")

        assert completed.returncode == 0, completed.stderr
        document = json.loads(completed.stdout)
        assert document.keys() == {"files", "records", "warnings", "layout"}
        assert "scf.in" in document["files"]
        assert any(
            warning["code"] == "job.walltime_defaulted"
            for warning in document["warnings"]
        )
        assert [step["name"] for step in document["layout"]["steps"]] == ["scf"]
        # P2: sort_keys=True -- re-serializing must reproduce the same text.
        assert json.dumps(
            document, indent=2, sort_keys=True
        ) == completed.stdout.rstrip("\n")


class TestPerStepOverrides:
    """#154 on the CLI: `--set steps.nscf.k_grid=...` was stripped to a flat
    `k_grid`, so it also moved the scf mesh (752 irreducible k-points instead
    of 47 on diamond Si); a flat plus a per-step value of one key exited 2;
    dos.x keys were unknown; and a key no step of the task reads was dropped.
    No real assets needed: explain reports every record either way."""

    def _explain_dos(self, *settings: str) -> dict[str, object]:
        silicon = structure("Si.cif")
        flags = [part for setting in settings for part in ("--set", setting)]
        completed = _run_cli(
            "explain", str(silicon), "--hpc", "scarf", "--task", "dos", *flags, "--json"
        )
        assert completed.returncode == 0, completed.stderr
        return strict_json(completed.stdout)

    def test_steps_nscf_k_grid_changes_only_the_nscf_mesh(self) -> None:
        default = self._explain_dos()["records"]
        records = self._explain_dos("steps.nscf.k_grid=[30,30,30]")["records"]

        assert records["nscf_k_sampling"]["value"]["mesh"] == [30, 30, 30]
        assert records["nscf_k_sampling"]["source"] == "human"
        assert records["k_sampling"] == default["k_sampling"]
        assert records["n_irr_k"] == default["n_irr_k"]

    def test_a_flat_and_a_per_step_value_of_one_key_both_apply(self) -> None:
        records = self._explain_dos("k_grid=[4,4,4]", "steps.nscf.k_grid=[30,30,30]")[
            "records"
        ]

        assert records["k_sampling"]["value"]["mesh"] == [4, 4, 4]
        assert records["nscf_k_sampling"]["value"]["mesh"] == [30, 30, 30]

    def test_a_flat_k_grid_names_both_steps_it_lands_on(self) -> None:
        document = self._explain_dos("k_grid=[4,4,4]")

        notices = [
            warning
            for warning in document["warnings"]
            if warning["code"] == "overrides.applies_to_multiple_steps"
        ]
        assert notices == [
            {
                "code": "overrides.applies_to_multiple_steps",
                "level": "info",
                "category": "overrides",
                "message": (
                    "k_grid was given without a step, so it applies to the "
                    "scf and nscf steps; set steps.<step>.k_grid to set one "
                    "step only."
                ),
                "record": "overrides",
            }
        ]

    _K_GRID_NOTICE = (
        "notice: k_grid was given without a step, so it applies to the scf and "
        "nscf steps; set steps.<step>.k_grid to set one step only."
    )

    def test_the_text_report_prints_the_notice_before_the_blocked_lines(
        self,
    ) -> None:
        """The notice belongs to no record, and the text report printed only
        records and blocked lines, so it never showed."""
        silicon = structure("Si.cif")

        completed = _run_cli(
            "explain",
            str(silicon),
            "--hpc",
            "scarf",
            "--task",
            "dos",
            "--set",
            "k_grid=[4,4,4]",
        )

        assert completed.returncode == 0, completed.stderr
        lines = completed.stdout.splitlines()
        notice = lines.index(self._K_GRID_NOTICE)
        after = lines[notice + 1 :]
        assert all(not line.startswith("blocked:") for line in lines[:notice])
        # Only the findings follow: each blocked: line with its try: lines.
        assert all(line.startswith(("blocked:", "  try: ")) for line in after), after

    def test_a_shift_keeps_the_protocol_nscf_mesh(self) -> None:
        default = self._explain_dos()["records"]["nscf_k_sampling"]["value"]
        nscf = self._explain_dos("shift=[1,1,1]")["records"]["nscf_k_sampling"]["value"]

        assert (nscf["k_distance"], nscf["mesh"]) == (0.1, default["mesh"])
        assert nscf["shift"] == [1, 1, 1]

    def test_a_dos_x_setting_reaches_the_dos_record(self) -> None:
        dos = self._explain_dos(
            "delta_e=0.05", "steps.dos.ngauss=1", "steps.dos.broadening=0.01"
        )["records"]["dos"]

        assert (dos["value"]["delta_e"], dos["value"]["ngauss"]) == (0.05, 1)
        assert dos["field_sources"]["delta_e"] == "human"
        assert dos["field_sources"]["ngauss"] == "human"

    def test_steps_in_a_config_file_are_per_step_settings(self, tmp_path: Path) -> None:
        config = tmp_path / "dos.toml"
        config.write_text("[steps.nscf]\nk_grid = [30, 30, 30]\n")
        silicon = structure("Si.cif")

        completed = _run_cli(
            "explain",
            str(silicon),
            "--hpc",
            "scarf",
            "--task",
            "dos",
            "--config",
            str(config),
            "--json",
        )

        assert completed.returncode == 0, completed.stderr
        records = strict_json(completed.stdout)["records"]
        assert records["nscf_k_sampling"]["value"]["mesh"] == [30, 30, 30]
        assert records["k_sampling"]["value"]["mesh"] != [30, 30, 30]

    def test_a_band_task_s_path_spacing_and_bands_step_table(
        self, tmp_path: Path
    ) -> None:
        """#118: k_path_distance spaces the bands step's path, and a
        [steps.bands] table sets that step only."""
        config = tmp_path / "band.toml"
        config.write_text("k_path_distance = 0.05\n\n[steps.bands]\nconv_thr = 1e-11\n")
        silicon = structure("Si.cif")

        completed = _run_cli(
            "explain",
            str(silicon),
            "--hpc",
            "scarf",
            "--task",
            "band",
            "--config",
            str(config),
            "--json",
        )

        assert completed.returncode == 0, completed.stderr
        records = strict_json(completed.stdout)["records"]
        k_path = records["k_path"]
        assert k_path["value"]["k_path_distance"] == 0.05
        assert k_path["field_sources"] == {"k_path_distance": "human"}
        assert records["bands_convergence"]["value"]["conv_thr"] == 1e-11
        assert records["convergence"]["value"]["conv_thr"] != 1e-11

    def test_a_band_task_names_both_pw_x_steps_a_plain_nbnd_lands_on(self) -> None:
        silicon = structure("Si.cif")

        completed = _run_cli(
            "explain",
            str(silicon),
            "--hpc",
            "scarf",
            "--task",
            "band",
            "--set",
            "nbnd=40",
        )

        assert completed.returncode == 0, completed.stderr
        assert (
            "notice: nbnd was given without a step, so it applies to the scf and "
            "bands steps; set steps.<step>.nbnd to set one step only."
        ) in completed.stdout.splitlines()

    @pytest.mark.parametrize(
        ("task", "setting", "message"),
        [
            (
                "scf_single_point",
                "press=10",
                "'press' does not apply to task 'scf_single_point'; "
                "it applies to tasks vc-relax, vc-relax-phonon",
            ),
            (
                "relax-phonon",
                "steps.scf.k_grid=[4,4,4]",
                "unknown step 'scf' in 'steps.scf.k_grid'; "
                "task 'relax-phonon' has steps: relax, ph, q2r, phonon_dos, "
                "dispersion",
            ),
            (
                "dos",
                "steps.nscf.walltime_h=4",
                "'walltime_h' is set once per task, not per step",
            ),
            (
                "band",
                "steps.bands.k_grid=[4,4,4]",
                "'k_grid' does not apply to step 'bands'",
            ),
        ],
    )
    def test_a_setting_no_step_of_the_task_reads_is_an_operator_error(
        self, task: str, setting: str, message: str
    ) -> None:
        silicon = structure("Si.cif")

        completed = _run_cli(
            "explain", str(silicon), "--hpc", "scarf", "--task", task, "--set", setting
        )

        assert completed.returncode == 2
        assert "Traceback" not in completed.stderr
        assert message in completed.stderr


def test_run_out_records_the_request_the_http_path_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#176: ``goldilocks run -o`` wrote a goldilocks.json with no code, task,
    version, overrides or structure hash. It now records the same request
    block ``/run`` does for the same structure and overrides: the CLI's are
    its ``--config`` then ``--set`` assignments as typed, step prefixes kept.
    Offline: one synthetic Si table, registered for the subprocess."""
    spec, table = sssp_fixture_table_spec(tmp_path / "sources")
    AssetStore().install(spec, sssp_preparer(table))
    registry = tmp_path / "registry.toml"
    write_registry(registry, table)
    monkeypatch.setenv("GOLDILOCKS_PSEUDO_REGISTRY", str(registry))
    content = structure("Si.cif").read_text()
    path = tmp_path / "Si.cif"
    path.write_text(content)
    config = tmp_path / "dos.toml"
    config.write_text("k_distance = 0.3\n\n[steps.dos]\ndelta_e = 0.05\n")

    completed = _run_cli(
        "run",
        str(path),
        "--hpc",
        "scarf",
        "--task",
        "dos",
        "--config",
        str(config),
        "--set",
        "k_distance=0.2",
        "-o",
        str(tmp_path / "out"),
    )

    assert completed.returncode == 0, completed.stderr
    published = strict_json((tmp_path / "out" / "goldilocks.json").read_text())
    _summary, bundle_input = _handlers.run(
        ComputeRequestDocument(
            structure_content=content,
            structure_name="Si.cif",
            hpc="scarf",
            task="dos",
            overrides={"k_distance": 0.2, "steps.dos.delta_e": 0.05},
        )
    )
    (answered,) = (
        strict_json(file["content"])
        for file in bundle_files(bundle_input)
        if file["path"] == "goldilocks.json"
    )
    assert published["request"] == answered["request"]
    assert published["request"]["overrides"] == {
        "k_distance": 0.2,
        "steps.dos.delta_e": 0.05,
    }
    assert published["request"]["task"] == "dos"
