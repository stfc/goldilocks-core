"""Tests for goldilocks_core.capabilities (v2 epic 8, #8)."""

from __future__ import annotations

import json
import re
import typing
from importlib.machinery import ModuleSpec
from importlib.metadata import version as package_version
from types import SimpleNamespace

from goldilocks_core.advisors import magnetic_ordering_ml
from goldilocks_core.capabilities import (
    SOURCES,
    VOCABULARY_VERSION,
    SettingBinding,
    _json_type,
    _unwrap_optional,
    bindings,
    capabilities,
)
from goldilocks_core.ml import predict as predict_module
from goldilocks_core.service import (
    AnalysisFacts,
    DosOverrides,
    JobOverrides,
    KPathOverrides,
    KpointsOverrides,
    PhononDosOverrides,
    PhOverrides,
    Q2rOverrides,
    RelaxOverrides,
    ResourceOverrides,
    RunOverrides,
    SystemOverrides,
)
from goldilocks_core.set_overrides import build_overrides

_ALL_TASKS = [
    "scf_single_point",
    "dos",
    "band",
    "relax",
    "vc-relax",
    "phonon",
    "relax-phonon",
    "vc-relax-phonon",
]
_PHONON_TASKS = ["phonon", "relax-phonon", "vc-relax-phonon"]


def _install_every_model(monkeypatch, root) -> None:
    """Every registered model asset resolves to ``root``, as if installed
    and verified, without installing anything (CI installs no assets)."""
    monkeypatch.setattr(
        predict_module,
        "AssetStore",
        lambda: SimpleNamespace(resolve_spec=lambda spec: SimpleNamespace(root=root)),
    )


def _record_value_type(key: str) -> object:
    """``T`` of the ``FieldState[T]`` ``AnalysisFacts`` declares for ``key``."""
    (value_type,) = typing.get_args(typing.get_type_hints(AnalysisFacts)[key])
    return value_type


def _advertised_values(entry: dict[str, object]) -> list[object]:
    """Every value a settings[] or facts[] entry tells a client it may send:
    each enum member, or true/false for a boolean."""
    if entry["type"] == "boolean":
        return [True, False]
    return list(entry.get("enum") or entry.get("values") or [])


def _accepted(binding: SettingBinding, value: object) -> object:
    """``value`` for ``binding``'s key through ``build_overrides``, for the
    first task the key applies to, read back from where it landed: the
    task-level overrides, or the first step of that task it applies to."""
    task = binding.tasks[0]
    overrides = build_overrides({binding.key: value}, task=task)
    branch = _branch(overrides, binding)
    outer = getattr(branch, binding.outer_field)
    return outer if binding.inner_field is None else getattr(outer, binding.inner_field)


def _branch(overrides: RunOverrides, binding: SettingBinding) -> object:
    if binding.steps is None:
        return getattr(overrides, binding.branch)
    step = next(purpose for purpose in overrides.steps if purpose in binding.steps)
    return getattr(overrides.steps[step], binding.branch)


def _expected_setting_field_count() -> int:
    """Independently recomputes how many settings should exist, by
    walking the same composing classes capabilities.py reflects
    over -- a completeness guard that fails loudly if the walker ever
    silently drops a field, without hardcoding a magic number that
    would need editing by hand every time an advisor gains a field."""
    total = 0
    for cls in (
        SystemOverrides,
        JobOverrides,
        KpointsOverrides,
        ResourceOverrides,
        RelaxOverrides,
        DosOverrides,
        KPathOverrides,
        PhOverrides,
        Q2rOverrides,
        PhononDosOverrides,
    ):
        hints = typing.get_type_hints(cls)
        for name, annotation in hints.items():
            if name.endswith("_llm"):
                continue
            inner = _unwrap_optional(annotation)
            if isinstance(inner, type) and hasattr(inner, "model_fields"):
                total += len(inner.model_fields)
            else:
                total += 1
    return total


class TestTopLevelShape:
    def test_has_every_design_doc_key(self) -> None:
        caps = capabilities()

        for key in (
            "core_version",
            "vocabulary_version",
            "codes",
            "tasks",
            "facts",
            "settings",
            "pseudopotential_tables",
            "hpc_profiles",
            "models",
            "warnings",
            "sources",
        ):
            assert key in caps

    def test_core_version_matches_installed_package(self) -> None:
        assert capabilities()["core_version"] == package_version("goldilocks-core")

    def test_vocabulary_version_is_the_module_constant(self) -> None:
        """'4': the band task's path record, bands_k_path, was renamed
        k_path (#215)."""
        assert capabilities()["vocabulary_version"] == VOCABULARY_VERSION == "5"

    def test_sources_is_the_closed_priority_order(self) -> None:
        assert (
            capabilities()["sources"]
            == list(SOURCES)
            == [
                "human",
                "ml",
                "llm",
                "heuristic",
            ]
        )

    def test_is_fully_json_serializable(self) -> None:
        """Regression guard for the exact bug module 1's bundle.py hit:
        a stray non-JSON-safe object (e.g. a dataclass or Structure)
        anywhere in this tree would blow up json.dumps."""
        json.dumps(capabilities())

    def test_models_lists_every_registered_model(self) -> None:
        """v2 epic 11 (#11): models[] reflects ml/registry.toml, not
        fabricated -- registered, not necessarily installed (approaches
        below is the honest "is it actually usable right now" signal)."""
        ids = {model["id"] for model in capabilities()["models"]}
        assert ids == {
            "models/qrf-kpoints",
            "models/metallicity-cgcnn",
            "models/is-metal-classifier",
            "models/is-magnetic-classifier",
        }

    def test_warnings_catalogue_is_populated_from_every_advisor(self) -> None:
        caps = capabilities()

        assert caps["warnings"]
        for entry in caps["warnings"]:
            assert entry.keys() == {"code", "level", "category", "message"}
            assert entry["level"] in {"info", "warning", "error"}

    def test_warnings_catalogue_lists_the_hubbard_u_value_warnings(self) -> None:
        """#135: the missing-value and unused-element codes are published,
        so a frontend can filter on them before any run has emitted them."""
        by_code = {entry["code"]: entry for entry in capabilities()["warnings"]}

        for code in ("hubbard.u_value_missing", "hubbard.u_by_element_unused"):
            assert (by_code[code]["level"], by_code[code]["category"]) == (
                "warning",
                "hubbard",
            )

    def test_warnings_catalogue_lists_both_spin_orbit_notices(self) -> None:
        """#181: the notice that spin-orbit coupling cannot be served is
        published next to the suggestion, so a frontend can filter on it
        before any run has emitted it."""
        by_code = {entry["code"]: entry for entry in capabilities()["warnings"]}

        for code in ("magnetic.soc_suggested", "magnetic.soc_unavailable"):
            assert (by_code[code]["level"], by_code[code]["category"]) == (
                "info",
                "magnetic",
            )

    def test_warnings_catalogue_lists_the_hubbard_spin_polarization_warning(
        self,
    ) -> None:
        """#147: the warning that a U on an odd d or f count turned spin
        polarization on is published, so a frontend can filter on it before
        any run has emitted it."""
        by_code = {entry["code"]: entry for entry in capabilities()["warnings"]}

        entry = by_code["magnetic.spin_polarized_for_hubbard_open_shell"]
        assert (entry["level"], entry["category"]) == ("warning", "magnetic")

    def test_warnings_catalogue_lists_a_model_warning_per_ml_record(self) -> None:
        """#156: the caveat a model returns with a prediction is published
        under its record's code, so a frontend can filter on it before any
        run has emitted it."""
        by_code = {entry["code"]: entry for entry in capabilities()["warnings"]}

        for record in ("is_metal", "is_magnetic", "k_sampling"):
            entry = by_code[f"{record}.model_warning"]
            assert (entry["level"], entry["category"]) == ("warning", record)

    def test_warnings_catalogue_codes_are_unique(self) -> None:
        codes = [entry["code"] for entry in capabilities()["warnings"]]

        assert len(codes) == len(set(codes))

    def test_warnings_catalogue_lists_the_frozen_hubbard_occupations_warning(
        self,
    ) -> None:
        """#166: the convergence advisor's one code is published, so a
        frontend can filter on it before any run has emitted it."""
        by_code = {entry["code"]: entry for entry in capabilities()["warnings"]}

        entry = by_code["convergence.mixing_fixed_ns_freezes_hubbard_occupations"]
        assert (entry["level"], entry["category"]) == ("warning", "convergence")

    def test_warnings_catalogue_lists_the_band_path_notices(self) -> None:
        """#118: the band path's three notices are published, so a frontend
        can filter on them before any run has emitted them."""
        by_code = {entry["code"]: entry for entry in capabilities()["warnings"]}

        for code, level in (
            ("k_path.folded_bands", "info"),
            ("k_path.magnetic_noncollinear_symmetry", "warning"),
            ("k_path.non_special_vertices", "info"),
        ):
            assert (by_code[code]["level"], by_code[code]["category"]) == (
                level,
                "k_path",
            )

    def test_warnings_catalogue_lists_the_phonon_notices(self) -> None:
        """#215: the phonon tasks' notices are published under the record
        that carries each, so a frontend can filter on them before any run
        has emitted them; the k-mesh and force-threshold codes keep their
        phonon prefix."""
        by_code = {entry["code"]: entry for entry in capabilities()["warnings"]}

        for code, level, category in (
            ("phonon.relax_first", "info", "phonon"),
            ("phonon.vc_relax_input_cell", "info", "phonon"),
            ("phonon.slab_lo_to_needs_2d_truncation", "warning", "phonon"),
            ("phonon.magnetic_noncollinear_experimental", "warning", "phonon"),
            ("phonon.hubbard_experimental", "warning", "phonon"),
            ("phonon.d3_two_body", "info", "phonon"),
            ("phonon.loose_force_threshold", "warning", "relax"),
            ("phonon.k_mesh_raised", "info", "k_sampling"),
            ("phonon.k_grid_coarser_than_q", "warning", "k_sampling"),
            ("phonon.k_grid_not_commensurate", "warning", "k_sampling"),
            ("phonon.lanthanide_actinide_k", "info", "k_sampling"),
            ("q_sampling.grid_and_distance_conflict", "info", "q_sampling"),
        ):
            assert (by_code[code]["level"], by_code[code]["category"]) == (
                level,
                category,
            ), code

    def test_codes_and_tasks_reflect_only_what_actually_runs(self) -> None:
        """v2 epic 9 (#9, #28): ``dos`` joined ``scf_single_point`` once
        the delivery layers actually routed it, not before -- this list
        names every task a caller can request today, no more, no less.
        ``relax``/``vc-relax`` joined the same way in v2 epic 10 (#10),
        ``band`` with its scf, pw.x bands and bands.x steps (#118), and the
        three phonon tasks with their first pw.x step, ph.x, q2r.x and
        matdyn.x (#215)."""
        caps = capabilities()
        assert caps["codes"] == [
            {
                "id": "quantum_espresso",
                "name": "Quantum ESPRESSO",
                "tasks": _ALL_TASKS,
            }
        ]
        assert [task["id"] for task in caps["tasks"]] == _ALL_TASKS
        by_id = {task["id"]: task for task in caps["tasks"]}
        assert by_id["scf_single_point"]["executables"] == ["pw.x"]
        assert by_id["scf_single_point"]["step_count"] == 1
        assert by_id["dos"]["executables"] == ["pw.x", "pw.x", "dos.x"]
        assert by_id["dos"]["step_count"] == 3
        assert by_id["band"]["name"] == "Band structure"
        assert by_id["band"]["executables"] == ["pw.x", "pw.x", "bands.x"]
        assert by_id["band"]["step_count"] == 3
        for default in ("k_path_distance 0.025", "bands.yaml"):
            assert default in by_id["band"]["description"], default
        assert by_id["relax"]["executables"] == ["pw.x"]
        assert by_id["relax"]["step_count"] == 1
        assert by_id["vc-relax"]["executables"] == ["pw.x"]
        assert by_id["vc-relax"]["step_count"] == 1

    def test_the_phonon_tasks_name_their_relaxation_and_their_defaults(
        self,
    ) -> None:
        """#215: each phonon task runs its first pw.x step, then ph.x, q2r.x
        and matdyn.x for the phonon DOS and for the dispersion, with d3hess.x
        for DFT-D3; its description names the q-mesh and path protocols and,
        for the two relaxations, the force threshold's."""
        by_id = {task["id"]: task for task in capabilities()["tasks"]}

        assert [by_id[task]["name"] for task in _PHONON_TASKS] == [
            "Phonon (no relaxation)",
            "Phonon (incl. relaxation)",
            "Phonon (incl. vc-relaxation)",
        ]
        for task in _PHONON_TASKS:
            entry = by_id[task]
            assert entry["executables"] == [
                "pw.x",
                "ph.x",
                "q2r.x",
                "matdyn.x",
                "matdyn.x",
            ]
            assert entry["step_count"] == 5
            assert entry["codes"] == ["quantum_espresso"]
            for term in (
                "d3hess.x",
                "q_distance 0.3",
                "ph protocol",
                "dispersion",
                "k_path_distance 0.025",
            ):
                assert term in entry["description"], (task, term)
            assert ("forc_conv_thr 1e-4" in entry["description"]) is (
                task != "phonon"
            ), task
        assert "relax-phonon" in by_id["phonon"]["description"]
        assert "relax-phonon" in by_id["vc-relax-phonon"]["description"]


class TestSettingsCompleteness:
    def test_every_override_field_has_exactly_one_setting(self) -> None:
        caps = capabilities()

        assert len(caps["settings"]) == _expected_setting_field_count()

    def test_no_duplicate_keys(self) -> None:
        keys = [s["key"] for s in capabilities()["settings"]]

        assert len(keys) == len(set(keys))

    def test_every_setting_has_a_non_empty_description(self) -> None:
        """Every setting must be documented in _SETTING_META -- an empty
        description means a new advisor field was added and nobody
        wrote its capabilities metadata yet."""
        for setting in capabilities()["settings"]:
            assert setting["description"], setting["key"]

    def test_hubbard_needs_correlation_is_renamed_to_avoid_the_fact_collision(
        self,
    ) -> None:
        keys = {s["key"] for s in capabilities()["settings"]}

        assert "hubbard_needs_correlation" in keys
        assert "needs_correlation" not in keys  # only the fact owns this bare name

    def test_system_level_settings_apply_to_all_programs(self) -> None:
        settings = {s["key"]: s for s in capabilities()["settings"]}

        assert settings["functional"]["scope"] == "system"
        assert settings["functional"]["programs"] is None
        assert settings["ecutwfc_ry"]["scope"] == "system"

    def test_per_step_settings_are_scoped_to_pw_x(self) -> None:
        settings = {s["key"]: s for s in capabilities()["settings"]}

        for key in ("occupations", "k_grid", "nbnd", "npool", "nstep", "press"):
            assert settings[key]["scope"] == "per_step"
            assert settings[key]["programs"] == ["pw.x"]

    def test_functional_carries_enum_from_and_default(self) -> None:
        settings = {s["key"]: s for s in capabilities()["settings"]}

        expected = "pseudopotential_tables.functional"
        assert settings["functional"]["enum_from"] == expected
        assert settings["functional"]["default"] == "PBEsol"

    def test_hubbard_projectors_is_one_system_choice_for_every_task(self) -> None:
        settings = {s["key"]: s for s in capabilities()["settings"]}

        projectors = settings["hubbard_projectors"]
        assert (projectors["type"], projectors["enum"]) == (
            "string",
            ["atomic", "ortho-atomic"],
        )
        assert projectors["default"] == "ortho-atomic"
        assert (projectors["group"], projectors["scope"]) == ("hubbard", "system")
        assert projectors["tasks"] == _ALL_TASKS
        assert (projectors["steps"], projectors["programs"]) == (None, None)

    def test_occupations_enum_matches_the_literal_type(self) -> None:
        settings = {s["key"]: s for s in capabilities()["settings"]}

        assert settings["occupations"]["type"] == "string"
        assert set(settings["occupations"]["enum"]) == {
            "fixed",
            "smearing",
            "tetrahedra_opt",
        }

    def test_isolation_offers_three_code_neutral_categories(self) -> None:
        """#161: the boundary setting takes periodic/slab/isolated; the
        Quantum ESPRESSO writer owns the assume_isolated spelling."""
        settings = {s["key"]: s for s in capabilities()["settings"]}

        assert "assume_isolated" not in settings
        isolation = settings["isolation"]
        assert isolation["group"] == "boundary"
        assert isolation["scope"] == "system"
        assert isolation["type"] == "string"
        assert set(isolation["enum"]) == {"isolated", "periodic", "slab"}
        for term in ("'2D'", "'martyna-tuckerman'", "wire", "vc-relax"):
            assert term in isolation["description"], term

    def test_k_grid_is_a_fixed_length_integer_array(self) -> None:
        settings = {s["key"]: s for s in capabilities()["settings"]}

        assert settings["k_grid"]["type"] == "array"
        assert settings["k_grid"]["minItems"] == 3
        assert settings["k_grid"]["maxItems"] == 3

    def test_k_distance_declares_its_ml_target(self) -> None:
        settings = {s["key"]: s for s in capabilities()["settings"]}

        assert settings["k_distance"]["ml_target"] == "k_distance"

    def test_approaches_never_includes_ml_since_no_model_is_installed(self) -> None:
        """Design point (1)-b: ml_target is a static declaration,
        approaches is runtime-computed -- k_index declares an ml_target
        (a real, published goldilocks-ml ladder-rung model, #90) but
        must not claim "ml" is usable while that model stays
        registered-but-not-wired."""
        settings = {s["key"]: s for s in capabilities()["settings"]}

        assert settings["k_index"]["approaches"] == ["human", "heuristic"]
        assert settings["functional"]["approaches"] == ["human", "heuristic"]

    def test_k_distance_approaches_gains_ml_once_qrf95_is_installed(
        self, real_assets
    ) -> None:
        """v2 epic 11 follow-up (#92): QRF95 predates ML_CLASSIFIER_ROLES
        and is checked by its own branch in capabilities._ml_model_installed
        -- this exercises that branch is honestly wired end to end, not
        just is_metal/is_magnetic's shared table."""
        settings = {s["key"]: s for s in capabilities()["settings"]}

        assert settings["k_distance"]["approaches"] == ["human", "ml", "heuristic"]

    def test_units_are_present_where_physically_meaningful(self) -> None:
        settings = {s["key"]: s for s in capabilities()["settings"]}

        assert settings["ecutwfc_ry"]["unit"] == "Ry"
        assert settings["walltime_h"]["unit"] == "hours"
        assert settings["u_by_element"]["unit"] == "eV"
        assert settings["npool"]["unit"] is None


class TestSettingApplicability:
    """#154: every setting published codes: null, tasks: null, so nothing
    could reject or hide a key no step of a task reads. Each setting now
    names the code, the tasks and the steps it applies to and the program
    that reads it; system and job settings are task-level (steps null)."""

    def _settings(self) -> dict[str, dict[str, object]]:
        return {s["key"]: s for s in capabilities()["settings"]}

    def test_every_setting_declares_its_codes_tasks_steps_and_programs(
        self,
    ) -> None:
        for setting in capabilities()["settings"]:
            assert setting["codes"] == ["quantum_espresso"], setting["key"]
            assert setting["tasks"], setting["key"]
            if setting["scope"] == "per_step":
                assert setting["steps"], setting["key"]
                assert setting["programs"], setting["key"]
            else:
                assert setting["scope"] in ("system", "task"), setting["key"]
                assert setting["steps"] is None, setting["key"]
                assert setting["tasks"] == _ALL_TASKS, setting["key"]

    def test_pw_x_step_settings_apply_to_every_pw_x_step(self) -> None:
        settings = self._settings()

        for key in ("nbnd", "extra_bands", "conv_thr", "npool", "ndiag"):
            assert settings[key]["steps"] == [
                "scf",
                "nscf",
                "bands",
                "relax",
                "vc-relax",
            ], key
            assert settings[key]["tasks"] == _ALL_TASKS, key
            assert settings[key]["programs"] == ["pw.x"], key

    def test_mesh_and_occupations_settings_skip_the_bands_step(self) -> None:
        """#118: a bands step runs its band path with the scf step's
        occupations, so a plain k_grid or occupations on a band task sets its
        scf step only."""
        settings = self._settings()

        mesh = (
            "occupations",
            "smearing_type",
            "degauss",
            "k_grid",
            "k_index",
            "k_distance",
            "shift",
        )
        for key in mesh:
            assert settings[key]["steps"] == ["scf", "nscf", "relax", "vc-relax"], key
            assert settings[key]["tasks"] == _ALL_TASKS, key
            assert settings[key]["programs"] == ["pw.x"], key

    def test_the_path_spacing_is_published_on_the_bands_and_dispersion_steps(
        self,
    ) -> None:
        """#215: the phonon tasks' dispersion step follows the band task's
        path, so one spacing serves pw.x's bands step and matdyn.x's
        dispersion, resolved in each task's k_path record. The description
        says where the dispersion takes more steps into Gamma than the
        spacing needs."""
        k_path_distance = self._settings()["k_path_distance"]

        assert (k_path_distance["group"], k_path_distance["scope"]) == (
            "k_path",
            "per_step",
        )
        assert (k_path_distance["steps"], k_path_distance["tasks"]) == (
            ["bands", "dispersion"],
            ["band", *_PHONON_TASKS],
        )
        assert k_path_distance["programs"] == ["matdyn.x", "pw.x"]
        assert (k_path_distance["type"], k_path_distance["unit"]) == (
            "number",
            "1/Angstrom",
        )
        assert k_path_distance["structure_specific"] is False
        assert k_path_distance["resolved_in"] == {
            "record": "k_path",
            "path": ["k_path_distance"],
        }
        for term in (
            "2 pi included",
            "dispersion",
            "matdyn.x lands on Gamma exactly",
            "phonon branches",
        ):
            assert term in k_path_distance["description"], term

    def test_scf_loop_settings_skip_the_nscf_step(self) -> None:
        """An nscf step runs no SCF loop (QE 7.3 calls non_scf and sets
        niter = 1), yet these were published, accepted and recorded human
        for a dos task's nscf step, which ignores them."""
        settings = self._settings()

        scf_loop = ("mixing_beta", "mixing_mode", "mixing_fixed_ns", "electron_maxstep")
        for key in scf_loop:
            assert settings[key]["steps"] == ["scf", "relax", "vc-relax"], key
            assert settings[key]["tasks"] == _ALL_TASKS, key
            assert settings[key]["programs"] == ["pw.x"], key

    def test_relaxation_settings_apply_to_the_relax_tasks_only(self) -> None:
        """A relax-phonon or vc-relax-phonon task's first step is a relax or
        vc-relax step, so its settings reach it (#215)."""
        settings = self._settings()

        for key in ("nstep", "ion_dynamics", "fix_bottom_layers", "etot_conv_thr"):
            assert settings[key]["steps"] == ["relax", "vc-relax"], key
            assert settings[key]["tasks"] == [
                "relax",
                "vc-relax",
                "relax-phonon",
                "vc-relax-phonon",
            ], key

    def test_cell_settings_apply_to_vc_relax_only(self) -> None:
        settings = self._settings()

        for key in ("press", "cell_dofree", "press_conv_thr", "cell_factor"):
            assert settings[key]["steps"] == ["vc-relax"], key
            assert settings[key]["tasks"] == ["vc-relax", "vc-relax-phonon"], key
            assert settings[key]["programs"] == ["pw.x"], key

    def test_the_phonon_steps_settings_are_published_on_their_steps(self) -> None:
        """#215: the q-mesh and ph.x's linear-response settings on the ph
        step, the acoustic sum rule on the q2r step and the DOS spacing on
        the phonon_dos step, each for the three phonon tasks, read by the
        program that runs that step and resolved in that step's record. Both
        matdyn.x runs apply the q2r step's sum rule."""
        settings = self._settings()

        inverse_angstrom = "1/Angstrom"
        for key, group, step, program, default in (
            ("q_grid", "q_sampling", "ph", "ph.x", None),
            ("q_distance", "q_sampling", "ph", "ph.x", 0.3),
            ("tr2_ph", "phonon", "ph", "ph.x", 1e-18),
            ("alpha_mix", "phonon", "ph", "ph.x", 0.4),
            ("nmix_ph", "phonon", "ph", "ph.x", 8),
            ("asr", "q2r", "q2r", "q2r.x", "simple"),
            ("dos_q_distance", "phonon_dos", "phonon_dos", "matdyn.x", 0.1),
        ):
            setting = settings[key]
            assert (setting["group"], setting["scope"]) == (group, "per_step"), key
            assert (setting["steps"], setting["programs"]) == ([step], [program])
            assert setting["tasks"] == _PHONON_TASKS, key
            assert setting.get("default") == default, key
            assert setting["structure_specific"] is (key == "q_grid"), key
        assert [settings[key]["unit"] for key in ("q_distance", "dos_q_distance")] == [
            inverse_angstrom,
            inverse_angstrom,
        ]
        for key in ("q_grid", "tr2_ph", "alpha_mix", "nmix_ph", "asr"):
            assert settings[key]["unit"] is None, key
        assert (settings["q_grid"]["type"], settings["q_grid"]["items"]) == (
            "array",
            "integer",
        )
        assert (settings["q_grid"]["minItems"], settings["q_grid"]["maxItems"]) == (
            3,
            3,
        )
        assert settings["nmix_ph"]["type"] == "integer"
        assert (settings["asr"]["type"], settings["asr"]["enum"]) == (
            "string",
            ["crystal", "simple"],
        )
        assert "phonon DOS and the dispersion" in settings["asr"]["description"]

    def test_the_force_threshold_has_one_default_per_kind_of_task(self) -> None:
        """#215: QE's 1e-3 for the relax and vc-relax tasks, 1e-4 for the
        phonon tasks' relaxation, so no single default is published."""
        forc_conv_thr = self._settings()["forc_conv_thr"]

        assert "default" not in forc_conv_thr
        for term in ("1e-3", "1e-4", "relax-phonon", "vc-relax-phonon"):
            assert term in forc_conv_thr["description"], term

    def test_the_walltime_and_fix_bottom_layers_texts_name_the_phonon_tasks(
        self,
    ) -> None:
        """#215: a phonon job runs a timer in place of max_seconds, and the
        phonon tasks refuse fix_bottom_layers."""
        settings = self._settings()

        walltime = settings["walltime_h"]["description"]
        for term in ("max_seconds", "job timer", "<prefix>.EXIT", "95%"):
            assert term in walltime, term
        assert "phonon tasks refuse it" in settings["fix_bottom_layers"]["description"]

    def test_dos_x_settings_are_published_on_the_dos_step(self) -> None:
        settings = self._settings()

        delta_e = settings["delta_e"]
        assert (delta_e["group"], delta_e["scope"]) == ("dos", "per_step")
        assert (delta_e["steps"], delta_e["tasks"]) == (["dos"], ["dos"])
        assert delta_e["programs"] == ["dos.x"]
        assert delta_e["unit"] == "eV"
        assert (settings["emin"]["unit"], settings["emax"]["unit"]) == ("eV", "eV")
        assert settings["broadening"]["unit"] == "Ry"
        assert settings["ngauss"]["type"] == "integer"
        for key in ("delta_e", "emin", "emax", "broadening", "ngauss"):
            assert settings[key]["description"], key

    def test_job_settings_are_task_level(self) -> None:
        settings = self._settings()

        for key in ("partition", "nodes", "ntasks", "walltime_h", "account"):
            assert settings[key]["scope"] == "task", key
            assert settings[key]["steps"] is None, key

    def test_the_routing_notice_is_in_the_warnings_catalogue(self) -> None:
        by_code = {entry["code"]: entry for entry in capabilities()["warnings"]}

        entry = by_code["overrides.applies_to_multiple_steps"]
        assert (entry["level"], entry["category"]) == ("info", "overrides")

    def test_bindings_route_with_the_published_steps(self) -> None:
        catalogue = bindings()

        for setting in capabilities()["settings"]:
            binding = catalogue[setting["key"]]
            steps = None if binding.steps is None else list(binding.steps)
            assert steps == setting["steps"], setting["key"]


class TestStructureSpecific:
    """#188: opening another structure reset the Workbench's task and every
    override, the account and the functional included. Each setting now says
    whether its value is a judgement about the structure (its elements,
    magnetism, geometry, size or k-mesh), which a client clears when the
    structure changes, or a method, accuracy or job choice, which it keeps."""

    def _settings(self) -> dict[str, dict[str, object]]:
        return {s["key"]: s for s in capabilities()["settings"]}

    def test_every_setting_declares_a_boolean(self) -> None:
        for setting in capabilities()["settings"]:
            assert type(setting.get("structure_specific")) is bool, setting["key"]

    def test_judgements_about_the_structure_are_structure_specific(self) -> None:
        settings = self._settings()

        # spin_orbit_coupling too: only a fully relativistic table that covers
        # the elements can serve it, so it is not a choice for any structure.
        for key in (
            "u_by_element",
            "hubbard_needs_correlation",
            "k_grid",
            "starting_magnetization",
            "magnetic_ordering",
            "spin_orbit_coupling",
            "pseudo_table_id",
            "isolation",
            "fix_bottom_layers",
            "emin",
            "q_grid",
        ):
            assert settings[key]["structure_specific"] is True, key

    def test_method_accuracy_and_job_choices_are_not(self) -> None:
        settings = self._settings()

        for key in (
            "account",
            "partition",
            "walltime_h",
            "functional",
            "conv_thr",
            "forc_conv_thr",
            "k_distance",
            "smearing_type",
            "delta_e",
            "hubbard_projectors",
            "q_distance",
            "tr2_ph",
            "asr",
            "dos_q_distance",
        ):
            assert settings[key]["structure_specific"] is False, key


class TestResolvedIn:
    """#187: the Workbench looked a setting's resolved value up by the
    setting's own name and its record by the group's, so spin_orbit_coupling
    (recorded as spin_orbit_enabled), k_grid (mesh) and magnetic_ordering
    (ordering.applied) showed "—", and so did the knobs no record holds a
    value of, all under a tier caption. Each setting now names the record of
    the decision it feeds and the path of its resolved value in that
    record's value, or no path where the record holds none."""

    def _settings(self) -> dict[str, dict[str, object]]:
        return {s["key"]: s for s in capabilities()["settings"]}

    def test_every_setting_names_its_record_and_a_path_or_none(self) -> None:
        for setting in capabilities()["settings"]:
            resolved_in = setting["resolved_in"]
            assert resolved_in.keys() == {"record", "path"}, setting["key"]
            assert isinstance(resolved_in["record"], str), setting["key"]
            assert resolved_in["record"], setting["key"]
            path = resolved_in["path"]
            assert path is None or isinstance(path, list), setting["key"]
            assert all(isinstance(key, str) and key for key in path or ())

    def test_a_setting_resolves_in_its_group_s_record_under_its_own_name(
        self,
    ) -> None:
        settings = self._settings()

        for key in (
            "ecutwfc_ry",
            "nelec",
            "spin_polarized",
            "tot_magnetization",
            "isolation",
            "account",
            "occupations",
            "k_distance",
            "nbnd",
            "conv_thr",
            "npool",
            "press",
            "delta_e",
            "q_distance",
            "tr2_ph",
            "alpha_mix",
            "nmix_ph",
            "asr",
            "dos_q_distance",
        ):
            setting = settings[key]
            expected = {"record": setting["group"], "path": [key]}
            assert setting["resolved_in"] == expected, key

    def test_settings_recorded_under_another_name(self) -> None:
        settings = self._settings()

        assert settings["functional"]["resolved_in"] == {
            "record": "functional",
            "path": [],
        }
        assert settings["pseudo_table_id"]["resolved_in"] == {
            "record": "pseudo_table",
            "path": ["id"],
        }
        assert settings["spin_orbit_coupling"]["resolved_in"] == {
            "record": "magnetic",
            "path": ["spin_orbit_enabled"],
        }
        assert settings["magnetic_ordering"]["resolved_in"] == {
            "record": "magnetic",
            "path": ["ordering", "applied"],
        }
        assert settings["moment_direction"]["resolved_in"] == {
            "record": "magnetic",
            "path": ["moment_direction", "uvw"],
        }
        assert settings["k_grid"]["resolved_in"] == {
            "record": "k_sampling",
            "path": ["mesh"],
        }
        assert settings["hubbard_projectors"]["resolved_in"] == {
            "record": "hubbard",
            "path": ["projectors"],
        }
        assert settings["q_grid"]["resolved_in"] == {
            "record": "q_sampling",
            "path": ["mesh"],
        }

    def test_input_only_knobs_name_their_record_but_no_path(self) -> None:
        """extra_bands only shifts nbnd, and the Hubbard switches only decide
        which U values apply: no record holds a value of any of them."""
        settings = self._settings()

        for key, record in (
            ("extra_bands", "nbnd"),
            ("hubbard_needs_correlation", "hubbard"),
            ("u_by_element", "hubbard"),
        ):
            expected = {"record": record, "path": None}
            assert settings[key]["resolved_in"] == expected, key

    def test_a_renamed_setting_records_no_value(self) -> None:
        """A record's field_sources are keyed by the override's field name,
        so a client can read a setting's tier as field_sources[key] only
        where the published key is that name."""
        catalogue = bindings()

        for setting in capabilities()["settings"]:
            binding = catalogue[setting["key"]]
            if setting["key"] != (binding.inner_field or binding.outer_field):
                assert setting["resolved_in"]["path"] is None, setting["key"]


class TestFacts:
    def test_exactly_the_four_scalar_facts(self) -> None:
        keys = {f["key"] for f in capabilities()["facts"]}

        assert keys == {"is_metal", "is_magnetic", "needs_soc", "needs_correlation"}

    def test_needs_soc_is_published_as_read_only_advice(self) -> None:
        """#186: only the magnetic.soc_suggested notice reads needs_soc, so a
        human value changed no generated file while the Workbench offered it
        as an On/Off switch. spin_orbit_coupling is the one SOC setting."""
        facts = {f["key"]: f for f in capabilities()["facts"]}

        assert facts["needs_soc"]["overridable"] is False
        assert facts["needs_soc"]["approaches"] == ["heuristic"]
        assert "needs_soc" not in bindings()
        assert "spin_orbit_coupling" in facts["needs_soc"]["description"]
        assert {key for key, fact in facts.items() if fact["overridable"]} == {
            "is_metal",
            "is_magnetic",
            "needs_correlation",
        }

    def test_is_metal_values_match_the_real_metallicity_type(self) -> None:
        facts = {f["key"]: f for f in capabilities()["facts"]}

        assert set(facts["is_metal"]["values"]) == {"metal", "non_metal"}
        assert facts["is_metal"]["ml_target"] == "is_metal"

    def test_is_metal_approaches_gains_ml_once_its_model_is_installed(
        self, real_assets
    ) -> None:
        """v2 epic 11 (#11): approaches is the honest "is it actually
        usable right now" signal, checked per asset -- real_assets is
        this test suite's own existing "is the default profile actually
        installed on this machine" gate."""
        facts = {f["key"]: f for f in capabilities()["facts"]}

        assert facts["is_metal"]["approaches"] == ["human", "ml", "heuristic"]

    def test_is_magnetic_approaches_omit_ml_without_the_mmace_backbone(
        self, monkeypatch, tmp_path
    ) -> None:
        """#130: ``approaches`` lists ``ml`` only when ml.predict would run
        the model. is_magnetic's installed asset alone is not enough: without
        its mMACE backbone, every prediction falls back to the heuristic."""
        _install_every_model(monkeypatch, tmp_path)
        monkeypatch.delenv("GOLDILOCKS_MACE_BACKBONE", raising=False)

        facts = {f["key"]: f for f in capabilities()["facts"]}

        assert facts["is_metal"]["approaches"] == ["human", "ml", "heuristic"]
        assert facts["is_magnetic"]["approaches"] == ["human", "heuristic"]

    def test_is_magnetic_approaches_gain_ml_once_mmace_is_set_up(
        self, monkeypatch, tmp_path
    ) -> None:
        _install_every_model(monkeypatch, tmp_path)
        checkpoint = tmp_path / "backbone.model"
        checkpoint.write_bytes(b"stub")
        monkeypatch.setenv("GOLDILOCKS_MACE_BACKBONE", str(checkpoint))
        monkeypatch.setattr(
            magnetic_ordering_ml, "find_spec", lambda name: ModuleSpec(name, None)
        )

        facts = {f["key"]: f for f in capabilities()["facts"]}

        assert facts["is_magnetic"]["approaches"] == ["human", "ml", "heuristic"]

    def test_a_fact_is_overridable_exactly_when_it_has_an_analysis_binding(
        self,
    ) -> None:
        """`overridable` is a promise about `--set`/override support, not a
        display flag: it once shipped True for all four facts while
        `bindings()` had no entry for any of them, so `--set is_metal=...`
        failed with "unknown setting"."""
        analysis_keys = {
            binding.key
            for binding in bindings().values()
            if binding.branch == "analysis"
        }
        facts = {f["key"]: f for f in capabilities()["facts"]}

        for key, fact in facts.items():
            assert fact["overridable"] is (key in analysis_keys), key
        assert facts["is_metal"]["overridable"] is True
        assert facts["is_magnetic"]["overridable"] is True

    def test_no_fact_description_names_a_resolution_method(self) -> None:
        """#175: is_metal read "..., from composition alone." while the CGCNN
        tier produced the value, so NaCl showed non_metal under a caption
        naming the tier that says metal. A description says what the fact
        means; the record's source and provenance say how it was resolved."""
        method_word = re.compile(
            r"\b(" + "|".join(("composition", "model", *SOURCES)) + r")\b",
            re.IGNORECASE,
        )

        for fact in capabilities()["facts"]:
            assert method_word.search(fact["description"]) is None, fact

    def test_is_metal_description_is_the_model_target_contract(self) -> None:
        """The is_metal model's target contract is
        goldilocks.is_metal.dft_band_gap_zero.v1; every tier answers that."""
        facts = {f["key"]: f for f in capabilities()["facts"]}

        assert facts["is_metal"]["description"] == (
            "Whether the structure is metallic (zero DFT band gap)."
        )


class TestOverrideContract:
    """#139: /capabilities advertised is_metal/is_magnetic as the enums
    metal/non_metal and magnetic/non_magnetic, while their overrides took
    only booleans, so every advertised value was a 422. Every value a
    client is told it may send must be accepted, on every key."""

    def test_each_fact_publishes_its_record_s_type_and_values(self) -> None:
        for fact in capabilities()["facts"]:
            value_type = _record_value_type(fact["key"])
            if typing.get_origin(value_type) is typing.Literal:
                expected = ("enum", sorted(typing.get_args(value_type)))
            else:
                assert value_type is bool, fact["key"]
                expected = ("boolean", None)
            assert (fact["type"], fact["values"]) == expected, fact["key"]

    def test_metallicity_and_magnetism_are_the_record_labels(self) -> None:
        facts = {f["key"]: f for f in capabilities()["facts"]}

        assert (facts["is_metal"]["type"], facts["is_metal"]["values"]) == (
            "enum",
            ["metal", "non_metal"],
        )
        assert (facts["is_magnetic"]["type"], facts["is_magnetic"]["values"]) == (
            "enum",
            ["magnetic", "non_magnetic"],
        )

    def test_an_overridable_fact_s_binding_takes_its_record_s_type(self) -> None:
        catalogue = bindings()

        for fact in capabilities()["facts"]:
            if fact["overridable"]:
                expected = _json_type(_record_value_type(fact["key"]))
                assert catalogue[fact["key"]].json_type == expected, fact["key"]

    def test_every_advertised_fact_value_is_accepted(self) -> None:
        catalogue = bindings()
        overridable = [f for f in capabilities()["facts"] if f["overridable"]]

        assert overridable
        for fact in overridable:
            for value in _advertised_values(fact):
                assert _accepted(catalogue[fact["key"]], value) == value

    def test_every_advertised_setting_value_is_accepted(self) -> None:
        """For a task the setting applies to (#154: no other accepts it)."""
        catalogue = bindings()
        checked = 0

        for setting in capabilities()["settings"]:
            for value in _advertised_values(setting):
                assert _accepted(catalogue[setting["key"]], value) == value
                checked += 1
        assert checked > 0


class TestPseudopotentialTablesAndHpcProfiles:
    def test_pseudopotential_tables_are_populated_from_the_real_registry(self) -> None:
        tables = capabilities()["pseudopotential_tables"]

        assert tables
        assert all("id" in t and "elements" in t for t in tables)

    def test_hpc_profiles_include_scarf(self) -> None:
        profiles = capabilities()["hpc_profiles"]

        assert any(p["id"] == "scarf" for p in profiles)
        scarf = next(p for p in profiles if p["id"] == "scarf")
        assert scarf["scheduler"] == "slurm"
        assert "scarf" in scarf["partitions"]


class TestTypeHelpers:
    def test_unwrap_optional_strips_none(self) -> None:
        assert _unwrap_optional(int | None) is int
        assert _unwrap_optional(str) is str

    def test_json_type_maps_python_primitives(self) -> None:
        assert _json_type(bool) == {"type": "boolean"}
        assert _json_type(int) == {"type": "integer"}
        assert _json_type(float) == {"type": "number"}
        assert _json_type(str) == {"type": "string"}

    def test_json_type_maps_literal_to_string_enum(self) -> None:
        result = _json_type(typing.Literal["a", "b"] | None)

        assert result == {"type": "string", "enum": ["a", "b"]}

    def test_json_type_maps_dict_to_object(self) -> None:
        assert _json_type(dict[str, float] | None) == {"type": "object"}

    def test_json_type_maps_fixed_tuple_to_array(self) -> None:
        result = _json_type(tuple[int, int, int] | None)

        assert result == {
            "type": "array",
            "items": "integer",
            "minItems": 3,
            "maxItems": 3,
        }
