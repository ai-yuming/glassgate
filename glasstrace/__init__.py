"""glasstrace — Glassgate structured-event trace layer (v0.1).

JSONL is the single source of truth; SQLite is a rebuildable derived index.
Hooks only ever append text — they never touch the database, so a gate
decision can never fail because of a locked or corrupt index.

Named `glasstrace` (not `trace`) to avoid shadowing the Python stdlib
`trace` module.
"""

__version__ = "0.1.0"
