"""Nulavio AI Bridge (ADR 0007): external agents drive an isolated AI Workspace through MCP.

`mcp` speaks the protocol, `tools` holds the browser tools and per-call
enforcement, `policy` and `registry` decide what each agent may do, `audit`
records what it did, `workspace` and `bidi` run and drive the engine.
"""
