"""Verifies the published electronic-character model for real (#174).

Downloads the PSDI record (data-collections.psdi.ac.uk/records/ba06w-n6a68)
through the normal asset-install path and runs it end to end. This is the
mechanism to self-verify against a live model as goldilocks-core adds more of
them, without committing weights to the repository -- so, unlike the rest of
the suite, this test is network-dependent by design. It skips rather than
fails when offline, the same way the fastapi/mcp extras skip when not
installed.
"""

from __future__ import annotations

import socket

import pytest
import requests
from pymatgen.core import Structure

from goldilocks_core.assets import AssetStore
from goldilocks_core.examples import structure
from goldilocks_core.ml import model_asset_specs
from goldilocks_core.runtime.models import Runtime

_PSDI_HOST = "data-collections.psdi.ac.uk"


def _psdi_is_reachable() -> bool:
    try:
        socket.create_connection((_PSDI_HOST, 443), timeout=3).close()
    except OSError:
        return False
    return True


@pytest.mark.skipif(not _psdi_is_reachable(), reason=f"{_PSDI_HOST} is not reachable")
def test_electronic_character_model_installs_and_predicts_for_real(tmp_path) -> None:
    store = AssetStore(tmp_path / "assets")
    specs = {spec.id: spec for spec in model_asset_specs()}
    try:
        installed = store.install(specs["models/metallicity-is-metal"])
    except requests.exceptions.HTTPError as error:
        # download()'s retry policy covers 429/502/503/504, not the plain 500
        # PSDI's S3-compatible backend occasionally returns for a presigned
        # URL; that is the backend having a bad moment, not a Core or model
        # regression, so this test tolerates it rather than failing on it.
        if error.response is not None and error.response.status_code == 500:
            pytest.skip(f"PSDI returned a transient 500: {error}")
        raise

    expected = {
        "Si.cif": "insulator",
        "Fe_bcc.cif": "metal",
        "Pt_fcc.cif": "metal",
    }

    with Runtime(metallicity_model_dir=installed.root) as runtime:
        for name, character_expected in expected.items():
            actual_structure = Structure.from_file(structure(name))
            character, source, confidence = runtime.metallicity(actual_structure)
            assert character == character_expected, name
            assert source == "model"
            assert confidence is not None
