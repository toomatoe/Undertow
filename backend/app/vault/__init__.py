"""Obsidian vault export: plain Markdown under <vault_dir>/Undertow/ (see AGENTS.md in this folder).

Never imports app.main; the caller passes evidence/paper callables and holds EXPORT_LOCK around export_vault.
"""

from app.vault.exporter import (
    DEFAULT_STUDY_FILES,
    EXPORT_LOCK,
    ExportResult,
    count_conflicts,
    export_vault,
    make_evidence_fn,
    read_state,
)
from app.vault.readback import read_theses

__all__ = [
    "DEFAULT_STUDY_FILES",
    "EXPORT_LOCK",
    "ExportResult",
    "count_conflicts",
    "export_vault",
    "make_evidence_fn",
    "read_state",
    "read_theses",
]
