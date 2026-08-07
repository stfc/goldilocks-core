"""HTTP and MCP transports for the Core pipeline.

Transport only — no auth, persistence, queue, or pod management. HTTP and MCP
dependencies live behind optional extras (``[http]``, ``[mcp]``) and are
imported lazily inside the transport modules so ``import goldilocks_core``
stays clean without them.
"""
