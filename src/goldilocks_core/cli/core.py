"""``goldilocks``: the v2 CLI entry point (v2 epic 8, #8).

Replaces v1's 30+-flag, per-advisor-option surface
(``cli/core.py``:167-230+, one ``add_argument`` per backend/pseudo/model
option) with the design doc's 6-command shape (``run``/``explain``/
``inspect``/``settings``/``models``/``assets``; ``serve`` and
``examples`` are the two "small, thoughtful" extras the design doc's
own P1-P8 section calls out to keep, and ``capabilities`` is a third,
added in #62 as a thin CLI entry point onto the same ``capabilities()``
HTTP/MCP already exposed) -- adding an advisor never touches this file
again, since every override surfaces through ``--set``, itself
reflected from ``capabilities.bindings()`` (``set_overrides.py``'s own
docstring).

Split into one module per command (``_run.py``/``_explain.py``/etc.),
not kept flat here: this project's own import-surface ceiling
(``scripts/check_complexity.py``) sets ``cli.core`` specifically to a
*tighter* limit (11 origins/16 symbols) than the default, so the
dispatcher stays thin and every command's real logic lives in its own
file -- one origin per command module plus ``failures`` and
``cli._output``, so a new command always needs this ceiling bumped by
exactly one (see #62's own bump from 8).

stdout carries only the command's own output (#183): ``main()`` reserves
it with ``cli._output.command_stdout`` before running any command but
``serve``, and each command's ``run(args, out)`` writes there, so library
prints, C extensions writing to fd 1 and child processes land on stderr.
``serve`` runs unredirected because MCP's stdio transport claims fd 1
itself, and only while ``sys.stdout`` is still fd 1.

P1-P8 (goldilocks-core-design.md:3577-3584), carried forward:
P1 every command has ``--json``; P2 JSON output is ``sort_keys=True``
(``cli._output.write_json``, the one place a command's JSON is
serialized); P3 ``--set``'s keys come from ``capabilities()``, never
hand-typed (``set_overrides.py``); P4 mutually
-exclusive semantics via argparse subparsers; P5 ``--set``/``--config``
validate immediately, before ``Service`` is ever reached
(``set_overrides.build_overrides``); P6 user errors (any
``ExpectedFailure``, or ``FileExistsError`` from ``bundle.publish``'s
no-overwrite guarantee) print usage + exit 2, anything else keeps its
traceback; P7 ``serve``'s HTTP/MCP imports stay inside their own
function (``_serve.py``); P8 ``--fetch-missing`` must be explicit
(``run``/``explain``).
"""

from __future__ import annotations

import argparse
import sys

from goldilocks_core.cli import (
    _assets,
    _capabilities,
    _explain,
    _inspect,
    _magnetic_orderings,
    _models,
    _run,
    _serve,
    _settings,
)
from goldilocks_core.cli._output import command_stdout
from goldilocks_core.failures import ExpectedFailure

_COMMANDS = {
    "run": _run,
    "explain": _explain,
    "inspect": _inspect,
    "settings": _settings,
    "capabilities": _capabilities,
    "models": _models,
    "assets": _assets,
    "examples": _assets,
    "magnetic-orderings": _magnetic_orderings,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="goldilocks", description="Generate and submit DFT calculations."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _run.add_subparser(subparsers)
    _explain.add_subparser(subparsers)
    _inspect.add_subparser(subparsers)
    _settings.add_subparser(subparsers)
    _capabilities.add_subparser(subparsers)
    _models.add_subparser(subparsers)
    _assets.add_subparser(subparsers)
    _serve.add_subparser(subparsers)
    _magnetic_orderings.add_subparser(subparsers)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "serve":
            _serve.run(args)
        else:
            with command_stdout() as out:
                _COMMANDS[args.command].run(args, out)
    except (ExpectedFailure, FileExistsError) as error:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
