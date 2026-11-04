"""Tests for goldilocks_core.set_overrides (v2 epic 8, #8)."""

from __future__ import annotations

import math

import pytest

from goldilocks_core.set_overrides import (
    InvalidSetting,
    build_overrides,
    build_overrides_from_cli,
    coerce_cli_assignments,
    coerce_cli_value,
    config_assignments,
    parse_set_flags,
)


class TestParseSetFlags:
    def test_splits_key_equals_value(self) -> None:
        assert parse_set_flags(["functional=PBE"]) == {"functional": "PBE"}

    def test_multiple_flags(self) -> None:
        result = parse_set_flags(["functional=PBE", "ecutwfc_ry=30"])

        assert result == {"functional": "PBE", "ecutwfc_ry": "30"}

    def test_value_may_itself_contain_an_equals_sign(self) -> None:
        result = parse_set_flags(['u_by_element={"Fe": 5.3}'])

        assert result == {"u_by_element": '{"Fe": 5.3}'}

    def test_repeating_the_same_key_with_the_same_value_is_fine(self) -> None:
        result = parse_set_flags(["functional=PBE", "functional=PBE"])

        assert result == {"functional": "PBE"}

    def test_repeating_the_same_key_with_a_different_value_raises(self) -> None:
        with pytest.raises(InvalidSetting, match="given twice"):
            parse_set_flags(["functional=PBE", "functional=LDA"])

    def test_missing_equals_sign_raises(self) -> None:
        with pytest.raises(InvalidSetting, match="KEY=VALUE"):
            parse_set_flags(["functional"])

    def test_empty_key_raises(self) -> None:
        with pytest.raises(InvalidSetting, match="empty key"):
            parse_set_flags(["=PBE"])

    def test_a_per_step_key_is_kept_as_given(self) -> None:
        """#154: the prefix used to be stripped here, so steps.nscf.k_grid
        reached every step; build_overrides routes it for the task now."""
        result = parse_set_flags(["steps.nscf.k_distance=0.12", "k_distance=0.2"])

        assert result == {"steps.nscf.k_distance": "0.12", "k_distance": "0.2"}


class TestCoerceCliValue:
    def _binding(self, key: str):
        from goldilocks_core.capabilities import bindings

        return bindings()[key]

    @pytest.mark.parametrize("raw", ["true", "True", "1", "yes", "on"])
    def test_boolean_true_spellings(self, raw: str) -> None:
        assert coerce_cli_value(self._binding("use_vdw"), "use_vdw", raw) is True

    @pytest.mark.parametrize("raw", ["false", "False", "0", "no", "off"])
    def test_boolean_false_spellings(self, raw: str) -> None:
        assert coerce_cli_value(self._binding("use_vdw"), "use_vdw", raw) is False

    def test_invalid_boolean_raises(self) -> None:
        with pytest.raises(InvalidSetting, match="not a boolean"):
            coerce_cli_value(self._binding("use_vdw"), "use_vdw", "maybe")

    def test_integer(self) -> None:
        assert coerce_cli_value(self._binding("nbnd"), "nbnd", "12") == 12

    def test_invalid_integer_raises(self) -> None:
        with pytest.raises(InvalidSetting, match="not an integer"):
            coerce_cli_value(self._binding("nbnd"), "nbnd", "12.5")

    def test_number(self) -> None:
        assert (
            coerce_cli_value(self._binding("ecutwfc_ry"), "ecutwfc_ry", "30.5") == 30.5
        )

    def test_invalid_number_raises(self) -> None:
        with pytest.raises(InvalidSetting, match="not a number"):
            coerce_cli_value(self._binding("ecutwfc_ry"), "ecutwfc_ry", "abc")

    def test_array_is_parsed_as_json(self) -> None:
        assert coerce_cli_value(self._binding("k_grid"), "k_grid", "[4, 4, 4]") == [
            4,
            4,
            4,
        ]

    def test_object_is_parsed_as_json(self) -> None:
        result = coerce_cli_value(
            self._binding("u_by_element"), "u_by_element", '{"Fe": 5.3}'
        )

        assert result == {"Fe": 5.3}

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(InvalidSetting, match="not valid JSON"):
            coerce_cli_value(self._binding("k_grid"), "k_grid", "not json")

    def test_string_passes_through(self) -> None:
        assert (
            coerce_cli_value(self._binding("functional"), "functional", "PBE") == "PBE"
        )


class TestCoerceCliAssignments:
    def test_unknown_key_raises_with_did_you_mean(self) -> None:
        with pytest.raises(InvalidSetting, match="did you mean: ecutwfc_ry"):
            coerce_cli_assignments({"ecutwf_ry": "30"})

    def test_unknown_key_with_no_close_match_has_a_generic_message(self) -> None:
        with pytest.raises(InvalidSetting, match="goldilocks settings"):
            coerce_cli_assignments({"totally_unrelated_nonsense_key": "1"})

    def test_a_malformed_per_step_key_raises(self) -> None:
        with pytest.raises(InvalidSetting, match="malformed"):
            coerce_cli_assignments({"steps.scf": "0.12"})


class TestConfigAssignments:
    def test_steps_tables_become_per_step_keys(self) -> None:
        document = {"functional": "PBE", "steps": {"nscf": {"k_grid": [30, 30, 30]}}}

        assert config_assignments(document) == {
            "functional": "PBE",
            "steps.nscf.k_grid": [30, 30, 30],
        }

    @pytest.mark.parametrize("steps", [1, {"nscf": 1}])
    def test_steps_must_be_tables_of_settings(self, steps: object) -> None:
        with pytest.raises(InvalidSetting, match=r"\[steps.<step>\] tables"):
            config_assignments({"steps": steps})


class TestBuildOverrides:
    def test_system_level_setting_lands_in_the_right_human_input(self) -> None:
        overrides = build_overrides({"functional": "PBE"}, task="scf_single_point")

        assert overrides.system.functional.functional == "PBE"

    def test_plain_system_field_needs_no_human_input_wrapper(self) -> None:
        overrides = build_overrides(
            {"pseudo_table_id": "sssp-fixture"}, task="scf_single_point"
        )

        assert overrides.system.pseudo_table_id == "sssp-fixture"

    def test_two_fields_of_the_same_human_input_class_merge(self) -> None:
        overrides = build_overrides(
            {"ecutwfc_ry": 30.0, "ecutrho_ry": 120.0}, task="scf_single_point"
        )

        assert overrides.system.cutoffs.ecutwfc_ry == 30.0
        assert overrides.system.cutoffs.ecutrho_ry == 120.0

    def test_kpoints_setting_lands_under_step_kpoints(self) -> None:
        overrides = build_overrides({"k_distance": 0.12}, task="scf_single_point")

        assert overrides.steps["scf"].kpoints.k_sampling.k_distance == 0.12

    def test_job_setting_lands_under_the_task_s_job(self) -> None:
        overrides = build_overrides({"partition": "scarf"}, task="scf_single_point")

        assert overrides.job.job.partition == "scarf"

    def test_hubbard_needs_correlation_key_maps_back_to_the_real_field(self) -> None:
        overrides = build_overrides(
            {"hubbard_needs_correlation": True}, task="scf_single_point"
        )

        assert overrides.system.hubbard.needs_correlation is True

    def test_analysis_fact_settings_land_under_analysis(self) -> None:
        overrides = build_overrides(
            {
                "is_metal": "non_metal",
                "is_magnetic": "magnetic",
                "needs_correlation": True,
            },
            task="scf_single_point",
        )

        assert overrides.analysis.is_metal.is_metal == "non_metal"
        assert overrides.analysis.is_magnetic.is_magnetic == "magnetic"
        assert overrides.analysis.needs_correlation.needs_correlation is True

    def test_needs_soc_is_refused(self) -> None:
        """#186: only a notice read a human needs_soc, so it changed no
        generated file; spin_orbit_coupling is the one SOC setting."""
        with pytest.raises(InvalidSetting, match="unknown setting 'needs_soc'"):
            build_overrides({"needs_soc": True}, task="scf_single_point")

    @pytest.mark.parametrize(
        ("key", "values"),
        [("is_metal", "'metal' or 'non_metal'"), ("is_magnetic", "'magnetic' or")],
    )
    def test_a_boolean_metallicity_or_magnetism_is_refused(
        self, key: str, values: str
    ) -> None:
        """#139: these overrides take the record's own labels, the values
        /capabilities advertises; no boolean alias."""
        with pytest.raises(InvalidSetting, match=values):
            build_overrides({key: False}, task="scf_single_point")

    def test_needs_correlation_and_hubbard_needs_correlation_are_independent(
        self,
    ) -> None:
        """The two ``needs_correlation``-named fields (the general analysis
        fact and hubbard's own escalation override) share an inner Python
        field name but must not collide as `--set` keys -- see
        ``capabilities.py``'s own docstring on this exact collision."""
        overrides = build_overrides(
            {"needs_correlation": True, "hubbard_needs_correlation": False},
            task="scf_single_point",
        )

        assert overrides.analysis.needs_correlation.needs_correlation is True
        assert overrides.system.hubbard.needs_correlation is False

    def test_unknown_key_raises(self) -> None:
        with pytest.raises(InvalidSetting):
            build_overrides({"not_a_real_setting": 1}, task="scf_single_point")

    def test_enum_violation_raises_invalid_setting_not_a_raw_pydantic_error(
        self,
    ) -> None:
        with pytest.raises(InvalidSetting, match="occupations"):
            build_overrides({"occupations": "bogus"}, task="scf_single_point")

    def test_smearing_type_refuses_fixed_an_occupations_value(self) -> None:
        """#200: 'fixed' rendered smearing = 'fixed', which pw.x stops on
        (QE 7.3 set_occupations.f90:61-62, "smearing fixed unknown")."""
        with pytest.raises(InvalidSetting, match="smearing_type"):
            build_overrides({"smearing_type": "fixed"}, task="scf_single_point")

    @pytest.mark.parametrize("kind", ["gaussian", "mp", "cold", "fd"])
    def test_smearing_type_takes_quantum_espresso_s_four_kinds(self, kind) -> None:
        """#200: QE's short names for its four smearing functions
        (set_occupations.f90:48-59), Fermi-Dirac ('fd') included."""
        overrides = build_overrides({"smearing_type": kind}, task="scf_single_point")

        assert overrides.steps["scf"].kpoints.occupations.smearing_type == kind

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("npool", 0),
            ("npool", -1),
            ("ndiag", 0),
            ("nodes", 0),
            ("ntasks", 0),
            ("walltime_h", -5.0),
            ("nbnd", -5),
            ("degauss", -0.5),
            ("smearing_type", "totally-bogus-value"),
        ],
    )
    def test_physically_invalid_override_raises_invalid_setting_not_a_crash(
        self, key: str, value: object
    ) -> None:
        """Regression for #35 (v2 epic 9, #9): each of these used to
        either be accepted silently or crash downstream with an
        unrelated Python exception (ZeroDivisionError, a negative
        math.isqrt argument, ...) instead of a clean InvalidSetting at
        the same boundary an unknown key or a bad enum member already
        gets."""
        with pytest.raises(InvalidSetting):
            build_overrides({key: value}, task="scf_single_point")

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("k_distance", 0.0),
            ("k_distance", -0.3),
            ("k_grid", [0, 4, 4]),
            ("k_grid", [-1, 4, 4]),
            ("shift", [5, 5, 5]),
            ("shift", [-1, 0, 1]),
        ],
    )
    def test_k_sampling_invalid_override_raises_invalid_setting_not_a_crash(
        self, key: str, value: object
    ) -> None:
        """Regression for #48: each of these used to be accepted
        silently (k_grid/shift, written verbatim into the K_POINTS
        card) or crash downstream with a raw ZeroDivisionError
        (k_distance<=0), instead of a clean InvalidSetting -- the one
        advisor #35's sweep never touched."""
        with pytest.raises(InvalidSetting):
            build_overrides({key: value}, task="scf_single_point")

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("ecutwfc_ry", -30.0),
            ("ecutrho_ry", 0.0),
            ("nelec", 0.0),
            ("nelec", -4.0),
            ("conv_thr", -1e-8),
            ("etot_conv_thr", 0.0),
            ("mixing_beta", -0.1),
            ("electron_maxstep", 0),
            ("mixing_fixed_ns", -1),
        ],
    )
    def test_cutoffs_electron_count_convergence_invalid_override_raises(
        self, key: str, value: object
    ) -> None:
        """Regression for #50: none of these were validated at all --
        no crash was reproduced for this specific batch, but a bad value
        would either write a physically-meaningless value straight into
        the generated input or only surface as a confusing QE-side
        runtime error, instead of a clean InvalidSetting here. A relax
        task, which every one of these keys applies to."""
        with pytest.raises(InvalidSetting, match="invalid value"):
            build_overrides({key: value}, task="relax")

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("k_distance", math.inf),
            # gt=0 alone admits +inf.
            ("degauss", math.inf),
            ("tot_magnetization", math.nan),
            ("starting_magnetization", {"Fe": -math.inf}),
        ],
    )
    def test_non_finite_number_raises_invalid_setting(
        self, key: str, value: object
    ) -> None:
        """No setting has a meaningful infinite or NaN value: --set
        k_distance=1e999, a TOML inf or a JSON 1e999 must fail here, not
        reach a record that strict JSON cannot carry (#137)."""
        with pytest.raises(InvalidSetting, match="finite number"):
            build_overrides({key: value}, task="scf_single_point")

    @pytest.mark.parametrize(
        "u_by_element",
        [
            {"Ni": 0},
            {"Ni": -2.0},
            {"Ni": float("inf")},
            {"Ni": float("nan")},
            {"Ni1": 6.0},
            {"Xx": 4.0},
            {"ni": 6.0},
        ],
    )
    def test_u_by_element_needs_element_symbols_and_positive_finite_values(
        self, u_by_element: dict[str, float]
    ) -> None:
        """#135: a lone U <= 0 leaves QE's HUBBARD card without a positive
        value (pw.x stops in card_hubbard), a non-finite one renders 'inf',
        and a key that is not an element symbol never matches a species."""
        with pytest.raises(InvalidSetting, match="u_by_element"):
            build_overrides({"u_by_element": u_by_element}, task="scf_single_point")

    @pytest.mark.parametrize(
        ("u_by_element", "manifold"),
        [
            ({"La": 5.0}, "La-4f"),
            ({"Cu": 4.0, "La": 5.0}, "La-4f"),
            ({"Ac": 4.0}, "Ac-5f"),
        ],
    )
    def test_u_by_element_rejects_manifolds_no_installed_pseudopotential_carries(
        self, u_by_element: dict[str, float], manifold: str
    ) -> None:
        """#135: pw.x stops on a La-4f U (SSSP's La has 4f occupation 0,
        PseudoDojo's no 4f channel) and on an Ac-5f U (the only Ac file has
        no 5f channel) whatever the value, so neither key is accepted."""
        with pytest.raises(InvalidSetting, match=f"stops on any {manifold} U"):
            build_overrides({"u_by_element": u_by_element}, task="scf_single_point")

    def test_u_by_element_accepts_element_symbols_with_positive_values(
        self,
    ) -> None:
        overrides = build_overrides(
            {"u_by_element": {"Fe": 5.3, "O": 1.5}}, task="scf_single_point"
        )

        assert overrides.system.hubbard.u_by_element == {"Fe": 5.3, "O": 1.5}

    def test_u_by_element_rejects_infinity_from_the_cli(self) -> None:
        with pytest.raises(InvalidSetting, match="u_by_element"):
            build_overrides_from_cli(
                ['u_by_element={"Ni": Infinity}'], task="scf_single_point"
            )

    def test_empty_assignments_gives_all_defaults(self) -> None:
        overrides = build_overrides({}, task="scf_single_point")

        assert overrides.analysis.is_metal is None
        assert overrides.system.functional is None
        assert overrides.job.job is None
        assert overrides.steps == {}
        assert overrides.warnings == ()


class TestBuildOverridesFromCli:
    def test_full_pipeline_from_raw_set_flags(self) -> None:
        overrides = build_overrides_from_cli(
            [
                "functional=PBE",
                "ecutwfc_ry=30.5",
                "k_grid=[4,4,4]",
                "spin_polarized=true",
            ],
            task="scf_single_point",
        )

        assert overrides.system.functional.functional == "PBE"
        assert overrides.system.cutoffs.ecutwfc_ry == 30.5
        assert overrides.steps["scf"].kpoints.k_sampling.k_grid == (4, 4, 4)
        assert overrides.system.magnetic.spin_polarized is True

    def test_the_removed_nosym_setting_is_refused(self) -> None:
        """#225: nosym changed only the recorded k-point count, never the
        input, so it is gone, and a request that sets it is told so."""
        with pytest.raises(InvalidSetting, match="unknown setting 'nosym'"):
            build_overrides_from_cli(["nosym=true"], task="scf_single_point")

    def test_steps_scf_prefix_lands_the_same_as_flat(self) -> None:
        flat = build_overrides_from_cli(["k_distance=0.12"], task="scf_single_point")
        scoped = build_overrides_from_cli(
            ["steps.scf.k_distance=0.12"], task="scf_single_point"
        )

        assert flat.steps == scoped.steps

    def test_typo_surfaces_as_invalid_setting(self) -> None:
        with pytest.raises(InvalidSetting):
            build_overrides_from_cli(["ecutwf_ry=30"], task="scf_single_point")

    def test_metallicity_and_magnetism_flags_take_the_advertised_labels(
        self,
    ) -> None:
        """#139: `--set is_metal=non_metal` exited 2 with "is not a boolean"."""
        overrides = build_overrides_from_cli(
            ["is_metal=non_metal", "is_magnetic=non_magnetic"],
            task="scf_single_point",
        )

        assert overrides.analysis.is_metal.is_metal == "non_metal"
        assert overrides.analysis.is_magnetic.is_magnetic == "non_magnetic"

    def test_a_boolean_metallicity_flag_is_refused(self) -> None:
        with pytest.raises(InvalidSetting, match="'metal' or 'non_metal'"):
            build_overrides_from_cli(["is_metal=false"], task="scf_single_point")


class TestTaskRouting:
    """#154: overrides were task- and step-blind. build_overrides built one
    StepOverrides shared by every pw.x step, the CLI stripped the steps.
    prefix (so steps.nscf.k_grid also moved the scf mesh), dos.x keys were
    unknown, and keys no step of the task reads were dropped silently.
    build_overrides(..., task=) now routes each key to the steps of that
    task it applies to."""

    _NOTICE = "overrides.applies_to_multiple_steps"

    def test_a_flat_k_grid_on_dos_lands_on_both_pw_x_steps_with_one_notice(
        self,
    ) -> None:
        overrides = build_overrides({"k_grid": [6, 6, 6]}, task="dos")

        assert set(overrides.steps) == {"scf", "nscf"}
        for purpose in ("scf", "nscf"):
            k_sampling = overrides.steps[purpose].kpoints.k_sampling
            assert k_sampling.k_grid == (6, 6, 6)
        assert [warning.model_dump() for warning in overrides.warnings] == [
            {
                "code": self._NOTICE,
                "level": "info",
                "category": "overrides",
                "message": (
                    "k_grid was given without a step, so it applies to the "
                    "scf and nscf steps; set steps.<step>.k_grid to set one "
                    "step only."
                ),
            }
        ]

    def test_steps_nscf_k_grid_lands_on_the_nscf_step_only(self) -> None:
        overrides = build_overrides({"steps.nscf.k_grid": [30, 30, 30]}, task="dos")

        assert set(overrides.steps) == {"nscf"}
        assert overrides.steps["nscf"].kpoints.k_sampling.k_grid == (30, 30, 30)
        assert overrides.warnings == ()

    def test_a_scoped_value_beats_the_flat_one_for_its_step(self) -> None:
        overrides = build_overrides(
            {"k_grid": [10, 10, 10], "steps.nscf.k_grid": [21, 21, 21]}, task="dos"
        )

        assert overrides.steps["scf"].kpoints.k_sampling.k_grid == (10, 10, 10)
        assert overrides.steps["nscf"].kpoints.k_sampling.k_grid == (21, 21, 21)
        assert overrides.warnings == ()

    def test_scoped_and_flat_fields_of_one_group_merge_per_step(self) -> None:
        overrides = build_overrides(
            {"degauss": 0.02, "steps.scf.smearing_type": "mp"}, task="dos"
        )

        scf = overrides.steps["scf"].kpoints.occupations
        nscf = overrides.steps["nscf"].kpoints.occupations
        assert (scf.smearing_type, scf.degauss) == ("mp", 0.02)
        assert (nscf.smearing_type, nscf.degauss) == (None, 0.02)

    def test_a_single_step_task_takes_flat_step_keys_without_a_notice(self) -> None:
        overrides = build_overrides({"k_grid": [4, 4, 4], "npool": 2}, task="relax")

        assert set(overrides.steps) == {"relax"}
        assert overrides.steps["relax"].kpoints.k_sampling.k_grid == (4, 4, 4)
        assert overrides.steps["relax"].resources.parallelisation.npool == 2
        assert overrides.warnings == ()

    def test_dos_x_keys_land_on_the_dos_step(self) -> None:
        overrides = build_overrides(
            {"delta_e": 0.05, "ngauss": 1, "emin": -10.0}, task="dos"
        )

        assert set(overrides.steps) == {"dos"}
        dos = overrides.steps["dos"].dos.dos
        assert (dos.delta_e, dos.ngauss, dos.emin) == (0.05, 1, -10.0)
        assert overrides.warnings == ()

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("mixing_beta", 0.3),
            ("mixing_mode", "local-TF"),
            ("mixing_fixed_ns", 5),
            ("electron_maxstep", 200),
        ],
    )
    def test_an_scf_loop_key_on_dos_reaches_the_scf_step_only(
        self, key: str, value: object
    ) -> None:
        """The nscf step runs no SCF loop, so pw.x ignores these there: the
        plain key used to land on it too, with a notice naming both steps,
        and steps.nscf.<key> was accepted."""
        overrides = build_overrides({key: value}, task="dos")

        assert set(overrides.steps) == {"scf"}
        assert getattr(overrides.steps["scf"].kpoints.convergence, key) == value
        assert overrides.warnings == ()
        with pytest.raises(InvalidSetting) as error:
            build_overrides({f"steps.nscf.{key}": value}, task="dos")
        assert str(error.value) == (
            f"'{key}' does not apply to step 'nscf' (in 'steps.nscf.{key}'); "
            "it applies to steps scf, relax, vc-relax"
        )

    def test_a_flat_k_path_distance_lands_on_the_bands_step_only(self) -> None:
        overrides = build_overrides({"k_path_distance": 0.02}, task="band")

        assert set(overrides.steps) == {"bands"}
        assert overrides.steps["bands"].k_path.k_path.k_path_distance == 0.02
        assert overrides.warnings == ()

    def test_band_task_mesh_and_occupations_keys_reach_its_scf_step_only(
        self,
    ) -> None:
        """#118: the bands step runs its band path with the scf step's
        occupations, so these land on the scf step, with no notice."""
        overrides = build_overrides(
            {"k_grid": [6, 6, 6], "occupations": "smearing", "degauss": 0.02},
            task="band",
        )

        assert set(overrides.steps) == {"scf"}
        kpoints = overrides.steps["scf"].kpoints
        assert kpoints.k_sampling.k_grid == (6, 6, 6)
        assert (kpoints.occupations.occupations, kpoints.occupations.degauss) == (
            "smearing",
            0.02,
        )
        assert overrides.warnings == ()

    @pytest.mark.parametrize(
        ("key", "value"),
        [("nbnd", 40), ("extra_bands", 4), ("conv_thr", 1e-9), ("npool", 2)],
    )
    def test_band_task_band_and_solver_keys_reach_both_pw_x_steps(
        self, key: str, value: object
    ) -> None:
        overrides = build_overrides({key: value}, task="band")

        assert set(overrides.steps) == {"scf", "bands"}
        assert [warning.message for warning in overrides.warnings] == [
            f"{key} was given without a step, so it applies to the scf and bands "
            f"steps; set steps.<step>.{key} to set one step only."
        ]

    def test_steps_bands_nbnd_lands_on_the_bands_step_only(self) -> None:
        overrides = build_overrides({"steps.bands.nbnd": 40}, task="band")

        assert set(overrides.steps) == {"bands"}
        assert overrides.steps["bands"].kpoints.nbnd.nbnd == 40
        assert overrides.warnings == ()

    @pytest.mark.parametrize(
        ("task", "first_step"),
        [("phonon", "scf"), ("relax-phonon", "relax"), ("vc-relax-phonon", "vc-relax")],
    )
    def test_a_phonon_task_s_pw_x_keys_land_on_its_first_step_alone(
        self, task: str, first_step: str
    ) -> None:
        """#215: the first step is a phonon task's only pw.x step, whatever its
        purpose, so a flat k_grid or conv_thr lands there with no notice."""
        overrides = build_overrides({"k_grid": [6, 6, 6], "conv_thr": 1e-9}, task=task)

        assert set(overrides.steps) == {first_step}
        kpoints = overrides.steps[first_step].kpoints
        assert (kpoints.k_sampling.k_grid, kpoints.convergence.conv_thr) == (
            (6, 6, 6),
            1e-9,
        )
        assert overrides.warnings == ()

    def test_the_phonon_steps_keys_land_on_their_own_steps(self) -> None:
        """#215: the q-mesh and ph.x's settings on the ph step, the acoustic
        sum rule on q2r and the DOS spacing on phonon_dos."""
        overrides = build_overrides(
            {
                "q_grid": [4, 4, 4],
                "tr2_ph": 1e-16,
                "asr": "simple",
                "dos_q_distance": 0.2,
            },
            task="phonon",
        )

        assert set(overrides.steps) == {"ph", "q2r", "phonon_dos"}
        ph = overrides.steps["ph"].ph
        assert (ph.q_sampling.q_grid, ph.phonon.tr2_ph) == ((4, 4, 4), 1e-16)
        assert overrides.steps["q2r"].q2r.q2r.asr == "simple"
        assert overrides.steps["phonon_dos"].phonon_dos.phonon_dos.dos_q_distance == (
            0.2
        )
        assert overrides.warnings == ()

    @pytest.mark.parametrize("task", ["phonon", "relax-phonon", "vc-relax-phonon"])
    def test_k_path_distance_lands_on_a_phonon_task_s_dispersion_step(
        self, task: str
    ) -> None:
        """#215: the dispersion step follows the band task's path and is the
        only step of a phonon task that reads its spacing, so a flat value
        lands there with no notice, as steps.dispersion.k_path_distance
        does."""
        flat = build_overrides({"k_path_distance": 0.02}, task=task)
        scoped = build_overrides({"steps.dispersion.k_path_distance": 0.02}, task=task)

        for overrides in (flat, scoped):
            assert set(overrides.steps) == {"dispersion"}
            assert overrides.steps["dispersion"].k_path.k_path.k_path_distance == 0.02
            assert overrides.warnings == ()

    def test_vc_relax_keys_reach_vc_relax_phonon_only(self) -> None:
        """#215: press is a vc-relax setting, so vc-relax-phonon takes it,
        flat or on its vc-relax step, and relax-phonon refuses it."""
        flat = build_overrides({"press": 10.0}, task="vc-relax-phonon")
        scoped = build_overrides({"steps.vc-relax.press": 10.0}, task="vc-relax-phonon")

        for overrides in (flat, scoped):
            assert overrides.steps["vc-relax"].relax.relax.press == 10.0
        with pytest.raises(InvalidSetting) as error:
            build_overrides({"press": 10.0}, task="relax-phonon")
        assert str(error.value) == (
            "'press' does not apply to task 'relax-phonon'; "
            "it applies to tasks vc-relax, vc-relax-phonon"
        )

    @pytest.mark.parametrize(
        ("task", "first_step"),
        [("relax-phonon", "relax"), ("vc-relax-phonon", "vc-relax")],
    )
    def test_fix_bottom_layers_routes_to_a_phonon_relaxation(
        self, task: str, first_step: str
    ) -> None:
        """Routing accepts it, as for any relaxation step; the gate refuses it
        in the phonon tasks (``checks.with_phonon_findings``)."""
        overrides = build_overrides({"fix_bottom_layers": 2}, task=task)

        assert overrides.steps[first_step].relax.relax.fix_bottom_layers == 2

    def test_system_and_job_keys_are_task_level_and_raise_no_notice(self) -> None:
        overrides = build_overrides(
            {"functional": "PBE", "walltime_h": 4, "is_metal": "non_metal"},
            task="dos",
        )

        assert overrides.system.functional.functional == "PBE"
        assert overrides.job.job.walltime_h == 4
        assert overrides.analysis.is_metal.is_metal == "non_metal"
        assert overrides.steps == {}
        assert overrides.warnings == ()

    @pytest.mark.parametrize(
        ("assignments", "task", "message"),
        [
            pytest.param(
                {"press": 10},
                "scf_single_point",
                "'press' does not apply to task 'scf_single_point'; "
                "it applies to tasks vc-relax, vc-relax-phonon",
                id="press-on-scf",
            ),
            pytest.param(
                {"press": 10},
                "dos",
                "'press' does not apply to task 'dos'; "
                "it applies to tasks vc-relax, vc-relax-phonon",
                id="press-on-dos",
            ),
            pytest.param(
                {"nstep": 100},
                "scf_single_point",
                "'nstep' does not apply to task 'scf_single_point'; "
                "it applies to tasks relax, vc-relax, relax-phonon, vc-relax-phonon",
                id="nstep-on-scf",
            ),
            pytest.param(
                {"etot_conv_thr": 1e-4},
                "dos",
                "'etot_conv_thr' does not apply to task 'dos'; "
                "it applies to tasks relax, vc-relax, relax-phonon, vc-relax-phonon",
                id="etot-conv-thr-on-dos",
            ),
            pytest.param(
                {"cell_dofree": "2Dxy"},
                "relax",
                "'cell_dofree' does not apply to task 'relax'; "
                "it applies to tasks vc-relax, vc-relax-phonon",
                id="cell-dofree-on-relax",
            ),
            pytest.param(
                {"delta_e": 0.05},
                "scf_single_point",
                "'delta_e' does not apply to task 'scf_single_point'; "
                "it applies to task dos",
                id="delta-e-on-scf",
            ),
            pytest.param(
                {"steps.nscf.functional": "PBE"},
                "dos",
                "'functional' is set once per task, not per step: "
                "drop the 'steps.nscf.' prefix",
                id="system-key-scoped",
            ),
            pytest.param(
                {"steps.scf.k_grid": [4, 4, 4]},
                "relax",
                "unknown step 'scf' in 'steps.scf.k_grid'; "
                "task 'relax' has steps: relax",
                id="scf-step-on-relax",
            ),
            pytest.param(
                {"steps.no_such_step.k_grid": [4, 4, 4]},
                "dos",
                "unknown step 'no_such_step' in 'steps.no_such_step.k_grid'; "
                "task 'dos' has steps: scf, nscf, dos",
                id="unknown-step",
            ),
            pytest.param(
                {"steps.bands.k_grid": [4, 4, 4]},
                "dos",
                "unknown step 'bands' in 'steps.bands.k_grid'; "
                "task 'dos' has steps: scf, nscf, dos",
                id="bands-step-on-dos",
            ),
            pytest.param(
                {"k_path_distance": 0.02},
                "scf_single_point",
                "'k_path_distance' does not apply to task 'scf_single_point'; "
                "it applies to tasks band, phonon, relax-phonon, vc-relax-phonon",
                id="k-path-distance-on-scf",
            ),
            pytest.param(
                {"steps.bands.k_grid": [4, 4, 4]},
                "band",
                "'k_grid' does not apply to step 'bands' (in 'steps.bands.k_grid'); "
                "it applies to steps scf, nscf, relax, vc-relax",
                id="k-grid-on-the-bands-step",
            ),
            pytest.param(
                {"steps.bands.occupations": "smearing"},
                "band",
                "'occupations' does not apply to step 'bands' "
                "(in 'steps.bands.occupations'); "
                "it applies to steps scf, nscf, relax, vc-relax",
                id="occupations-on-the-bands-step",
            ),
            pytest.param(
                {"steps.bands.mixing_beta": 0.3},
                "band",
                "'mixing_beta' does not apply to step 'bands' "
                "(in 'steps.bands.mixing_beta'); "
                "it applies to steps scf, relax, vc-relax",
                id="scf-loop-key-on-the-bands-step",
            ),
            pytest.param(
                {"steps.bands_x.nbnd": 40},
                "band",
                "'nbnd' does not apply to step 'bands_x' (in 'steps.bands_x.nbnd'); "
                "it applies to steps scf, nscf, bands, relax, vc-relax",
                id="pw-key-on-the-bands-x-step",
            ),
            pytest.param(
                {"steps.scf.k_path_distance": 0.02},
                "band",
                "'k_path_distance' does not apply to step 'scf' "
                "(in 'steps.scf.k_path_distance'); it applies to steps bands, "
                "dispersion",
                id="k-path-distance-on-the-scf-step",
            ),
            pytest.param(
                {"steps.nscf.walltime_h": 4},
                "dos",
                "'walltime_h' is set once per task, not per step: "
                "drop the 'steps.nscf.' prefix",
                id="job-key-scoped-to-nscf",
            ),
            pytest.param(
                {"steps.scf.ntasks": 64},
                "dos",
                "'ntasks' is set once per task, not per step: "
                "drop the 'steps.scf.' prefix",
                id="job-key-scoped-to-scf",
            ),
            pytest.param(
                {"steps.dos.k_grid": [4, 4, 4]},
                "dos",
                "'k_grid' does not apply to step 'dos' (in 'steps.dos.k_grid'); "
                "it applies to steps scf, nscf, relax, vc-relax",
                id="pw-key-on-the-dos-step",
            ),
            pytest.param(
                {"steps.nscf.delta_e": 0.05},
                "dos",
                "'delta_e' does not apply to step 'nscf' "
                "(in 'steps.nscf.delta_e'); it applies to step dos",
                id="dos-key-on-the-nscf-step",
            ),
            pytest.param(
                {"steps.scf.k_grid": [4, 4, 4]},
                "relax-phonon",
                "unknown step 'scf' in 'steps.scf.k_grid'; "
                "task 'relax-phonon' has steps: relax, ph, q2r, phonon_dos, "
                "dispersion",
                id="scf-step-on-relax-phonon",
            ),
            pytest.param(
                {"steps.vc-relax.press": 10},
                "relax-phonon",
                "unknown step 'vc-relax' in 'steps.vc-relax.press'; "
                "task 'relax-phonon' has steps: relax, ph, q2r, phonon_dos, "
                "dispersion",
                id="vc-relax-step-on-relax-phonon",
            ),
            pytest.param(
                {"delta_e": 0.05},
                "phonon",
                "'delta_e' does not apply to task 'phonon'; it applies to task dos",
                id="delta-e-on-phonon",
            ),
            pytest.param(
                {"steps.phonon_dos.k_path_distance": 0.02},
                "vc-relax-phonon",
                "'k_path_distance' does not apply to step 'phonon_dos' "
                "(in 'steps.phonon_dos.k_path_distance'); it applies to steps "
                "bands, dispersion",
                id="k-path-distance-on-the-phonon-dos-step",
            ),
            pytest.param(
                {"q_grid": [4, 4, 4]},
                "scf_single_point",
                "'q_grid' does not apply to task 'scf_single_point'; "
                "it applies to tasks phonon, relax-phonon, vc-relax-phonon",
                id="q-grid-on-scf",
            ),
            pytest.param(
                {"steps.ph.k_grid": [4, 4, 4]},
                "phonon",
                "'k_grid' does not apply to step 'ph' (in 'steps.ph.k_grid'); "
                "it applies to steps scf, nscf, relax, vc-relax",
                id="pw-key-on-the-ph-step",
            ),
            pytest.param(
                {"steps.q2r.q_grid": [4, 4, 4]},
                "phonon",
                "'q_grid' does not apply to step 'q2r' (in 'steps.q2r.q_grid'); "
                "it applies to step ph",
                id="ph-key-on-the-q2r-step",
            ),
            pytest.param(
                {"steps.nscf": 1},
                "dos",
                "malformed steps.<name>.<key> setting: 'steps.nscf'",
                id="malformed",
            ),
        ],
    )
    def test_a_key_no_step_of_the_task_reads_is_refused(
        self, assignments: dict[str, object], task: str, message: str
    ) -> None:
        with pytest.raises(InvalidSetting) as error:
            build_overrides(assignments, task=task)

        assert str(error.value) == message

    @pytest.mark.parametrize(
        ("assignments", "task", "steps"),
        [
            pytest.param(
                {
                    "k_grid": [6, 6, 6],
                    "steps.scf.k_grid": [4, 4, 4],
                    "steps.nscf.k_grid": [8, 8, 8],
                },
                "dos",
                "steps scf, nscf",
                id="dos",
            ),
            pytest.param(
                {"k_grid": [6, 6, 6], "steps.scf.k_grid": [4, 4, 4]},
                "scf_single_point",
                "step scf",
                id="scf",
            ),
        ],
    )
    def test_a_flat_key_every_step_also_sets_by_step_is_refused(
        self, assignments: dict[str, object], task: str, steps: str
    ) -> None:
        """The flat value reached no step, with no error and no notice."""
        with pytest.raises(InvalidSetting) as error:
            build_overrides(assignments, task=task)

        assert str(error.value) == (
            "'k_grid' given without a step reaches no step: the request also "
            f"sets it for {steps} (steps.<step>.k_grid); drop one of the two"
        )

    def test_an_unknown_task_is_refused(self) -> None:
        """expand_task planned any other task string as the dos task, so
        'scf' got a nscf step and a routing notice."""
        with pytest.raises(InvalidSetting) as error:
            build_overrides({"k_grid": [4, 4, 4]}, task="scf")

        assert str(error.value) == (
            "unknown task 'scf'; tasks: scf_single_point, dos, band, relax, "
            "vc-relax, phonon, relax-phonon, vc-relax-phonon"
        )

    def test_flat_walltime_on_dos_adds_no_notice(self) -> None:
        overrides = build_overrides({"walltime_h": 4, "ntasks": 64}, task="dos")

        assert overrides.warnings == ()

    def test_an_unknown_scoped_key_gets_the_did_you_mean(self) -> None:
        with pytest.raises(InvalidSetting, match="did you mean: k_grid"):
            build_overrides({"steps.nscf.k_gird": [4, 4, 4]}, task="dos")

    def test_a_scoped_value_is_validated_like_a_flat_one(self) -> None:
        with pytest.raises(InvalidSetting, match="ngauss"):
            build_overrides({"steps.dos.ngauss": 11}, task="dos")

    def test_the_cli_coerces_a_scoped_key_through_its_setting(self) -> None:
        typed = coerce_cli_assignments(
            parse_set_flags(["steps.nscf.k_grid=[30,30,30]"])
        )

        assert typed == {"steps.nscf.k_grid": [30, 30, 30]}

    def test_the_cli_takes_a_flat_and_a_scoped_value_of_one_key(self) -> None:
        """Both used to strip to 'k_grid', and the CLI exited 2 with
        "--set 'k_grid' given twice with different values"."""
        overrides = build_overrides_from_cli(
            ["k_grid=[10,10,10]", "steps.nscf.k_grid=[30,30,30]"], task="dos"
        )

        assert overrides.steps["scf"].kpoints.k_sampling.k_grid == (10, 10, 10)
        assert overrides.steps["nscf"].kpoints.k_sampling.k_grid == (30, 30, 30)
