"""Expected operation failures and their safe, transport-independent description.

Native exception owners opt into this vocabulary without changing their identity
or their existing exception bases. Adapters do not infer user errors from broad
built-in exception classes; an unmarked failure is a programming/runtime defect.
"""

from __future__ import annotations

from typing import Any, Literal


class ExpectedFailure(Exception):
    """A named failure whose public description may be shown to remote callers.

    ``local`` failures are only part of local execution/publication operations,
    not a remote request-error contract. Dependency failures indicate unavailable
    or invalid operator-managed assets, rather than invalid user input.
    """

    kind: str
    category: Literal["input", "dependency", "local"] = "input"

    def public_error(self) -> dict[str, Any]:
        return {"kind": self.kind, "message": str(self)}
