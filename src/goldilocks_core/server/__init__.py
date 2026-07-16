"""Transport surfaces over the fixed Core pipeline.

This package is intentionally thin. It owns request/structure deserialization
shared between transports and the HTTP server entry point. Core import surface
(``import goldilocks_core``) does not import this package, and HTTP
dependencies live behind the optional ``[http]`` extra.
"""
