"""Exercise the image test entry point without Docker or a browser."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "image_e2e.sh"


@pytest.mark.parametrize("skip_build", [False, True])
def test_image_e2e_runs_tests_and_cleans_up(tmp_path, skip_build):
    commands = tmp_path / "commands"
    for name in ("docker", "curl", "npm"):
        stub = tmp_path / name
        stub.write_text(f'#!/bin/sh\necho "{name} $*" >> "$COMMAND_LOG"\n')
        stub.chmod(0o755)
    (tmp_path / "web").mkdir()
    result = subprocess.run(
        ["bash", str(SCRIPT), *(["--skip-build"] if skip_build else [])],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "COMMAND_LOG": str(commands),
            "IMAGE_TAG": "test-image:local",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    calls = commands.read_text().splitlines()
    assert "docker build --check ." in calls
    assert ("docker build --tag test-image:local ." in calls) is not skip_build
    assert (
        "docker run --detach --name goldilocks-workbench-e2e "
        "--publish 8000:8000 test-image:local"
    ) in calls
    assert "npm run test:e2e" in calls
    assert calls[-1] == "docker rm --force goldilocks-workbench-e2e"


def test_image_e2e_rejects_unknown_arguments():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--unknown"], capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "Usage:" in result.stderr
