"""The CLI's stdout carries only the command's own output (#183).

Libraries a command loads can write to stdout while it runs: mace prints a
notice when it is first imported, a C extension can write to fd 1 directly,
and a child process inherits fd 1. Any of that ahead of a ``--json``
document makes it unparseable, so ``cli.core`` reserves stdout before a
command runs and every command writes through the stream it gets back.
"""

from __future__ import annotations

import json
import os
import sys
from typing import TextIO


def command_stdout() -> TextIO:
    """Reserve the process's stdout for the command's output.

    Returns a UTF-8 text stream on a duplicate of fd 1 that child processes
    do not inherit, then points fd 1 and ``sys.stdout`` at stderr for the
    rest of the process. Every other write to stdout -- ``print``, a C
    extension writing to fd 1 or flushing its stdio buffer at exit, a child
    process, a stream object saved before this call -- lands on stderr.
    Nothing is restored afterwards: a restored fd 1 would hand output
    flushed at interpreter exit the real stdout, after the document. The
    caller closes the stream when the command is done.
    """
    out = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return out


def write_json(out: TextIO, document: object) -> None:
    """Write ``document`` to ``out`` as indented JSON with sorted keys (P2)
    and a trailing newline.

    Strict JSON: a non-finite float raises ``ValueError`` instead of being
    written as ``Infinity``/``NaN``, which strict parsers reject (#137)."""
    out.write(json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n")
