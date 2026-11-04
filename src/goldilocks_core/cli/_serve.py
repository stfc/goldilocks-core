"""``goldilocks serve http|mcp``: now boots the v2-backed transports
(v2 epic 8, #8) -- ``server/http.py``/``server/mcp.py`` are rewired to
the ``service``/``capabilities``/``set_overrides`` stack in this same
epic. ``--static-root`` (#59) restores the Workbench static-file mount
CLI flag, once epic 12 (#12) actually wired the mount itself back up in
``server/http.py``'s ``create_app()`` -- the CLI-facing counterpart to
``GOLDILOCKS_WORKBENCH_STATIC_ROOT`` the Docker image sets instead
(see ``server/http.py``'s own docstring). P7's "optional deps imported
inside functions" applies here too: neither transport's extra needs to
be installed to run ``goldilocks run``/``explain``/etc.
"""

from __future__ import annotations

import argparse


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    serve = subparsers.add_parser("serve", help="Run an HTTP or MCP transport.")
    transports = serve.add_subparsers(dest="transport", required=True)
    http = transports.add_parser("http", help="Run the HTTP transport.")
    http.add_argument("--host", default="127.0.0.1")
    http.add_argument("--port", type=int, default=8000)
    http.add_argument(
        "--static-root",
        default=None,
        help=(
            "Serve the built Workbench frontend (a web/dist directory) at /. "
            "Defaults to the frontend bundled into this install, if this "
            "package was installed from a release build (#122)."
        ),
    )
    transports.add_parser("mcp", help="Run the MCP stdio transport.")


def run(args: argparse.Namespace) -> None:
    if args.transport == "http":
        from goldilocks_core.server.http import serve

        serve(host=args.host, port=args.port, static_root=args.static_root)
        return

    from goldilocks_core.server.mcp import serve

    serve()
