"""Tests for goldilocks_core.service._relax (v2 epic 10, #10)."""

from __future__ import annotations

import dataclasses

import pytest
from pymatgen.core import Lattice, Structure
from support import sssp_fixture_table_spec

from goldilocks_core.advisors.relax import VcRelaxOptions
from goldilocks_core.assets.pseudopotentials.importers import sssp_preparer
from goldilocks_core.assets.store import AssetStore
from goldilocks_core.inputs.hpc import Hardware, HpcProfile, Partition
from goldilocks_core.resolution import Blocked, Provenance, Resolved, Warning
from goldilocks_core.service import (
    RunOverrides,
    SystemOverrides,
    advise_relax,
    check_relax,
    generate_relax,
)
from goldilocks_core.set_overrides import build_overrides


def _findings(report, code: str) -> list:
    """The findings of ``report`` with ``code``; these tests have no table
    installed, which the report names too."""
    return [finding for finding in report.blocking if finding.code == code]


def _hpc() -> HpcProfile:
    hardware = Hardware(
        cores_per_node=64, mem_per_node_gb=250, max_nodes=100, max_walltime_h=168
    )
    return HpcProfile(
        name="test-cluster",
        scheduler="slurm",
        launcher="srun",
        modules={"quantum_espresso": ("qe/7.2",)},
        partitions={"scarf": Partition(name="scarf", hardware=hardware, default=True)},
    )


def _silicon() -> Structure:
    return Structure(Lattice.cubic(5.43), ["Si", "Si"], [[0, 0, 0], [0.25, 0.25, 0.25]])


def _silicon_slab() -> Structure:
    """A real, multi-layer 2D slab -- see
    ``test_generation_quantum_espresso_relax.py``'s own copy of this
    helper for why ``_silicon()`` (a bulk placeholder) can't stand in
    for layer-detection tests."""
    from pymatgen.core.surface import SlabGenerator

    bulk = Structure.from_spacegroup("Fd-3m", Lattice.cubic(5.43), ["Si"], [[0, 0, 0]])
    return SlabGenerator(
        bulk, (0, 0, 1), min_slab_size=10, min_vacuum_size=12, center_slab=True
    ).get_slab()


class TestAdviseRelaxDegradation:
    def test_relax_settings_resolve_with_heuristic_defaults(self) -> None:
        advice = advise_relax(_silicon(), calculation="relax", hpc=_hpc())

        assert advice.relax.ok
        assert advice.relax.value.ion_dynamics == "bfgs"
        assert advice.relax.value.nstep == 50

    def test_vc_relax_task_resolves_a_vc_relax_options(self) -> None:
        advice = advise_relax(_silicon(), calculation="vc-relax", hpc=_hpc())

        assert isinstance(advice.relax.value, VcRelaxOptions)

    def test_set_style_override_reaches_relax_settings(self) -> None:
        """Unlike DosHumanInput/DosLlmInput (v2 epic 9, #9, never wired
        to any transport), relax's own settings are real ``--set``/HTTP
        overrides -- capabilities.bindings() knows about them."""
        overrides = build_overrides(
            {"nstep": 200, "ion_dynamics": "fire"}, task="relax"
        )

        advice = advise_relax(
            _silicon(), calculation="relax", hpc=_hpc(), overrides=overrides
        )

        assert advice.relax.value.nstep == 200
        assert advice.relax.value.ion_dynamics == "fire"
        assert advice.relax.source == "human"

    def test_structural_override_reaches_relax_settings_too(self) -> None:
        overrides = build_overrides({"remove_rigid_rot": True}, task="relax")

        advice = advise_relax(
            _silicon(), calculation="relax", hpc=_hpc(), overrides=overrides
        )

        assert advice.relax.value.remove_rigid_rot is True

    def test_unknown_table_id_blocks_relax_and_check_relax_reports_it(self) -> None:
        overrides = RunOverrides(
            system=SystemOverrides(pseudo_table_id="does-not-exist")
        )

        advice = advise_relax(
            _silicon(), calculation="relax", hpc=_hpc(), overrides=overrides
        )

        assert isinstance(advice.advice.system.pseudo.metadata, Blocked)
        report = check_relax(advice)
        assert not report.ok
        assert any("does-not-exist" in finding.message for finding in report.blocking)

    @pytest.mark.parametrize(
        ("task", "settings", "code", "remedies"),
        [
            pytest.param(
                "vc-relax",
                {"ion_dynamics": "damp"},
                "relax.vc_relax_needs_bfgs",
                ({"ion_dynamics": "bfgs"},),
                id="vc-relax-needs-bfgs",
            ),
            pytest.param(
                "vc-relax",
                {"isolation": "isolated"},
                "boundary.isolated_forbids_vc_relax",
                (),
                id="isolated-forbids-vc-relax",
            ),
            pytest.param(
                "relax",
                {"functional": "LDA", "use_vdw": True},
                "vdw.use_vdw_without_d3bj_parameters",
                ({"use_vdw": False},),
                id="vdw-needs-d3bj-functional",
            ),
        ],
    )
    def test_a_cross_field_refusal_is_blocked_end_to_end(
        self, task, settings, code, remedies
    ) -> None:
        """check_relax reads the relax, boundary, vdw and functional records
        off the advice, so each cross-field rule refuses its request."""
        overrides = build_overrides(settings, task=task)

        advice = advise_relax(
            _silicon(), calculation=task, hpc=_hpc(), overrides=overrides
        )
        report = check_relax(advice)

        (finding,) = _findings(report, code)
        assert finding.remedies == remedies

    def test_set_style_override_reaches_fix_bottom_layers(self) -> None:
        """No registry entry was added for this: capabilities.py reflects
        ``RelaxHumanInput.fix_bottom_layers`` automatically (#44)."""
        overrides = build_overrides({"fix_bottom_layers": 2}, task="relax")

        advice = advise_relax(
            _silicon(), calculation="relax", hpc=_hpc(), overrides=overrides
        )

        assert advice.relax.value.fix_bottom_layers == 2
        assert advice.relax.source == "human"

    def test_fix_bottom_layers_on_bulk_silicon_is_blocked_end_to_end(self) -> None:
        overrides = build_overrides({"fix_bottom_layers": 1}, task="relax")

        advice = advise_relax(
            _silicon(), calculation="relax", hpc=_hpc(), overrides=overrides
        )
        report = check_relax(advice)

        (finding,) = _findings(report, "relax.fix_bottom_layers_needs_slab")
        assert "The cell to be written has no vacuum." in finding.message

    def test_fix_bottom_layers_beyond_the_slab_layers_is_blocked_end_to_end(
        self,
    ) -> None:
        """D16 (#160): the Si(001) slab has 8 atomic layers on the cell
        the writer renders, so check_relax refuses 9 instead of leaving
        generate_relax to raise."""
        overrides = build_overrides({"fix_bottom_layers": 9}, task="relax")

        advice = advise_relax(
            _silicon_slab(), calculation="relax", hpc=_hpc(), overrides=overrides
        )
        report = check_relax(advice)

        (finding,) = _findings(report, "relax.fix_bottom_layers_exceeds_layers")
        assert finding.message == (
            "fix_bottom_layers=9 exceeds the 8 atomic layers of the slab to be "
            "written. Set fix_bottom_layers to at most 8, or unset it."
        )


class TestRelaxWarnings:
    def test_warnings_list_the_relax_record_s_own(self) -> None:
        """#152: ``relax`` reached ``records()`` as a raw decision next to
        the shared records' dict projections, and the dict-only collector
        skipped it, so the vc-relax notice 1T-PtSe2 (MC2D mc2d-fe145b4f)
        carried never reached ``warnings``. Every warning a relax decision
        carries now does, naming the record it came from."""
        advice = advise_relax(_silicon(), calculation="vc-relax", hpc=_hpc())
        notice = Warning(
            code="relax.notice",
            level="warning",
            category="relax",
            message="a notice the relax decision carries.",
        )
        advice = dataclasses.replace(
            advice,
            relax=Resolved(
                VcRelaxOptions(warnings=(notice,)), Provenance(source="heuristic")
            ),
        )

        warnings = advice.warnings()

        assert notice.message in [warning["message"] for warning in warnings]
        assert {**notice.model_dump(), "record": "relax"} in warnings


class TestGenerateRelaxEndToEnd:
    def _store(self, tmp_path, monkeypatch) -> AssetStore:
        spec, registry_table = sssp_fixture_table_spec(tmp_path / "sources")
        monkeypatch.setattr(
            "goldilocks_core.service._pseudo.load_tables",
            lambda *a, **kw: {registry_table.id: registry_table},
        )
        store = AssetStore(tmp_path / "store")
        store.install(spec, sssp_preparer(registry_table))
        return store

    def test_generate_relax_produces_one_step(self, tmp_path, monkeypatch) -> None:
        store = self._store(tmp_path, monkeypatch)

        advice = advise_relax(_silicon(), calculation="relax", hpc=_hpc(), store=store)
        report = check_relax(advice)
        assert report.ok, report.blocking

        steps = generate_relax(advice, report)

        assert [step.name for step in steps] == ["relax"]
        assert steps[0].executable == "pw.x"
        content = steps[0].files["relax.in"]
        assert "calculation      = 'relax'" in content
        assert "&IONS" in content
        assert "&CELL" not in content

    def test_generate_relax_with_fix_bottom_layers_writes_if_pos_end_to_end(
        self, tmp_path, monkeypatch
    ) -> None:
        """Proves the full wire: a raw ``--set``-style dict override
        reaches ``RelaxHumanInput`` (capabilities.py reflection), then
        ``relax_settings`` (advisor), then ``checks.check_all`` (passes,
        since this structure is a real 2D slab), then ``write_qe_relax``
        (generation) -- not just each layer's own unit tests in
        isolation."""
        store = self._store(tmp_path, monkeypatch)
        overrides = build_overrides({"fix_bottom_layers": 2}, task="relax")

        advice = advise_relax(
            _silicon_slab(),
            calculation="relax",
            hpc=_hpc(),
            overrides=overrides,
            store=store,
        )
        report = check_relax(advice)
        assert report.ok, report.blocking

        steps = generate_relax(advice, report)

        lines = steps[0].files["relax.in"].splitlines()
        start = lines.index("ATOMIC_POSITIONS crystal") + 1
        end = next(i for i in range(start, len(lines)) if not lines[i].strip())
        rows = lines[start:end]
        fixed_rows = [row for row in rows if row.split()[-3:] == ["0", "0", "0"]]
        assert fixed_rows, "expected at least one if_pos-fixed row"
        assert len(fixed_rows) < len(rows), "expected some atoms to stay free"

    def test_generate_vc_relax_produces_one_step_with_cell_namelist(
        self, tmp_path, monkeypatch
    ) -> None:
        store = self._store(tmp_path, monkeypatch)

        advice = advise_relax(
            _silicon(), calculation="vc-relax", hpc=_hpc(), store=store
        )
        report = check_relax(advice)
        assert report.ok, report.blocking

        steps = generate_relax(advice, report)

        assert [step.name for step in steps] == ["vc-relax"]
        content = steps[0].files["vc-relax.in"]
        assert "calculation      = 'vc-relax'" in content
        assert "&CELL" in content
