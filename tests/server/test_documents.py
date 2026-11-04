"""Tests for goldilocks_core.server.documents (v2 epic 8, #8)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from goldilocks_core.server.documents import (
    ComputeRequestDocument,
    InlineStructureDocument,
    RunRequestDocument,
)


class TestInlineStructureDocument:
    def test_accepts_real_multiline_cif_text(self) -> None:
        document = InlineStructureDocument(
            structure_content="data_si\n_cell_length_a 5.43\n..."
        )

        assert document.structure_content.startswith("data_si")

    def test_rejects_a_bare_path_looking_value(self) -> None:
        with pytest.raises(ValidationError, match="not a path"):
            InlineStructureDocument(structure_content="/etc/passwd")

    def test_rejects_empty_content(self) -> None:
        with pytest.raises(ValidationError):
            InlineStructureDocument(structure_content="   ")

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            InlineStructureDocument(
                structure_content="line one\nline two", structure_path="/tmp/x.cif"
            )

    def test_defaults_name_and_format(self) -> None:
        document = InlineStructureDocument(structure_content="line one\nline two")

        assert document.structure_name == "structure"
        assert document.structure_format is None

    def test_rejects_an_invalid_format(self) -> None:
        with pytest.raises(ValidationError):
            InlineStructureDocument(
                structure_content="line one\nline two", structure_format="xyz"
            )


class TestComputeRequestDocument:
    def test_defaults_match_the_one_real_code_and_task(self) -> None:
        document = ComputeRequestDocument(structure_content="line one\nline two")

        assert document.code == "quantum_espresso"
        assert document.task == "scf_single_point"
        assert document.hpc is None
        assert document.overrides == {}
        assert document.fetch_missing is False

    def test_accepts_arbitrary_json_typed_overrides(self) -> None:
        document = ComputeRequestDocument(
            structure_content="line one\nline two",
            overrides={"ecutwfc_ry": 30.0, "k_grid": [4, 4, 4]},
        )

        assert document.overrides["ecutwfc_ry"] == 30.0
        assert document.overrides["k_grid"] == [4, 4, 4]

    def test_rejects_unknown_top_level_fields(self) -> None:
        with pytest.raises(ValidationError):
            ComputeRequestDocument(
                structure_content="line one\nline two", pseudo_root="/tmp"
            )


class TestRunRequestDocument:
    def test_defaults_to_json_response(self) -> None:
        document = RunRequestDocument(structure_content="line one\nline two")

        assert document.respond_with == "json"

    def test_rejects_an_unknown_respond_with_value(self) -> None:
        with pytest.raises(ValidationError):
            RunRequestDocument(
                structure_content="line one\nline two", respond_with="xml"
            )
