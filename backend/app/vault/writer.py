"""Note update policies on top of fs.VaultFS: write-once, machine notes, fenced notes and sealed (journal) notes.

Fence/hash mechanism: the generated part of a note lives between BEGIN and END marker lines. Its sha256 is stored
in the frontmatter (`undertow_hash`, or `outcome_hash` for journal notes). On re-export the stored hash must equal
the hash of the block currently in the file; otherwise a human edited inside the fence, the note is left
byte-for-byte untouched and the new content goes to `Undertow/_conflicts/<name>-<UTC ts>.md` instead. Everything
outside the fence (e.g. `## My notes`) is never modified once written.

Volatile keys (`generated_at`, `updated`) are copied from the existing file when the rest of the note is
unchanged, so a no-op export produces identical bytes. Frontmatter keys a human added are kept (raw text).
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass

from app.vault import frontmatter as fm
from app.vault.fs import VaultFS

log = logging.getLogger(__name__)

BEGIN = "<!-- undertow:begin -->"
END = "<!-- undertow:end -->"
VOLATILE = ("generated_at", "updated")
OUTCOME_PREFIX = "outcome_"
CONFLICTS = "_conflicts"


@dataclass
class Outcome:
    status: str  # created | updated | unchanged | conflict
    path: str
    conflict_path: str | None = None


def block_hash(block: str) -> str:
    return hashlib.sha256(block.encode("utf-8")).hexdigest()


def norm_block(block: str) -> str:
    return block.replace("\r\n", "\n").strip("\n")


def fenced(block: str) -> str:
    return f"{BEGIN}\n{block}\n{END}\n"


def _block_span(body: str) -> tuple[int, int] | None:
    if body.count(BEGIN) != 1 or body.count(END) != 1:
        return None
    start = body.find(BEGIN + "\n")
    if start < 0:
        return None
    start += len(BEGIN) + 1
    end = body.find("\n" + END, start - 1)
    if end < start - 1:
        return None
    return start, max(end, start)


def extract_block(body: str) -> str | None:
    span = _block_span(body)
    return None if span is None else body[span[0]:span[1]]


def replace_block(body: str, block: str) -> str:
    start, end = _block_span(body)  # callers check extract_block first
    return body[:start] + block + body[end:]


def assemble(chunk_texts: list[str]) -> str:
    return fm.FENCE + "\n" + "".join(chunk_texts) + fm.FENCE + "\n"


def _existing_chunks(text: str | None) -> tuple[list[tuple[str | None, str]] | None, str | None]:
    if text is None:
        return None, None
    fm_text, body = fm.split(text)
    if fm_text is None:
        return None, body
    return fm.chunks(fm_text), body


def merge_machine(fields: list[tuple[str, object]], existing: list[tuple[str | None, str]] | None, carry_volatile: bool) -> list[str]:
    """Machine keys in `fields` order (volatile ones optionally from `existing`), then a human's extra keys."""
    ex = {k: t for k, t in (existing or []) if k is not None}
    keys = {k for k, _ in fields}
    out = []
    for k, v in fields:
        if carry_volatile and k in VOLATILE and k in ex:
            out.append(ex[k] if ex[k].endswith("\n") else ex[k] + "\n")
        else:
            out.append(fm.emit_key(k, v))
    for k, t in existing or []:
        if k is None or k not in keys:
            out.append(t if t.endswith("\n") else t + "\n")
    return out


def _write_candidates(vfs: VaultFS, path: str, existing_text: str | None, build) -> str:
    """build(carry_volatile: bool) -> full note text. Keep the existing bytes when the carried-over version matches."""
    if existing_text is not None:
        candidate = build(True)
        if candidate == existing_text:
            return "unchanged"
    return vfs.write(path, build(False))


# --- policies ----------------------------------------------------------------------------------------------------


def write_once(vfs: VaultFS, path: str, text: str) -> Outcome:
    """Create the note if it does not exist; never rewrite it."""
    if vfs.read_bytes(path) is not None:
        return Outcome("unchanged", path)
    return Outcome(vfs.write(path, text), path)


def write_copy(vfs: VaultFS, path: str, data: bytes | str) -> Outcome:
    """Static file owned by Undertow (bases, AGENTS.md, the paper): rewritten only when the bytes differ."""
    return Outcome(vfs.write(path, data), path)


def write_machine(vfs: VaultFS, path: str, fields: list[tuple[str, object]], body: str) -> Outcome:
    """Whole note regenerated (index, studies); volatile keys carried over, a human's extra keys kept."""
    existing_text = vfs.read_text(path)
    ex_chunks, _ = _existing_chunks(existing_text)
    status = _write_candidates(vfs, path, existing_text, lambda carry: assemble(merge_machine(fields, ex_chunks, carry)) + body)
    return Outcome(status, path)


def _sans_volatile(data: bytes | None) -> bytes | None:
    """Content without volatile frontmatter lines, so a pending conflict is not written again on every run."""
    if data is None:
        return None
    return b"".join(line for line in data.splitlines(keepends=True) if not line.startswith((b"generated_at:", b"updated:")))


def write_conflict(vfs: VaultFS, name: str, rel_target: str, new_text: str, ts: str) -> str:
    """Write the would-be content to Undertow/_conflicts/<name>-<ts>.md (skipped when an identical one exists)."""
    header = (
        f"<!-- Undertow could not update {rel_target}: its generated block (between the undertow markers) was edited "
        f"by hand, so the note was left untouched. This is the new content. Merge what you need and delete this file "
        f"(and keep your edits outside the markers, e.g. under ## My notes). -->\n"
    )
    content = (header + new_text).encode("utf-8")
    prefix = os.path.basename(vfs.path(CONFLICTS, f"{name}.md"))[:-3] + "-"  # sanitized name
    for existing in vfs.listdir(CONFLICTS):
        if existing.startswith(prefix) and _sans_volatile(vfs.read_bytes(vfs.path(CONFLICTS, existing))) == _sans_volatile(content):
            return vfs.path(CONFLICTS, existing)
    target = vfs.path(CONFLICTS, f"{name}-{ts}.md")
    n = 2
    while vfs.read_bytes(target) is not None:
        target = vfs.path(CONFLICTS, f"{name}-{ts}-{n}.md")
        n += 1
    vfs.write(target, content)
    return target


def write_fenced(
    vfs: VaultFS,
    path: str,
    *,
    fields: list[tuple[str, object]],
    block: str,
    head: str = "",
    tail: str = "",
    hash_key: str = "undertow_hash",
    conflict_name: str,
    ts: str,
    sealed: bool = False,
    fill_once: tuple[str, ...] = (),
) -> Outcome:
    """Note whose generated part lives in a fence. New notes get `head + fence + tail` (tail = `## My notes`).

    sealed=False: machine keys are regenerated (volatile carried over), extra keys kept.
    sealed=True (journal): every existing non-`outcome_` key is copied verbatim; keys in `fill_once` may go from
    null to a value exactly once; `outcome_*` keys (incl. hash_key) are regenerated.
    """
    block = norm_block(block)
    fields = [*fields, (hash_key, block_hash(block))]
    existing_text = vfs.read_text(path)
    if existing_text is None:
        text = assemble([fm.emit_key(k, v) for k, v in fields]) + head + fenced(block) + tail
        return Outcome(vfs.write(path, text), path)

    existing_text = existing_text.replace("\r\n", "\n")
    fm_text, body = fm.split(existing_text)
    stored = None
    ok = fm_text is not None
    if ok:
        try:
            stored = fm.parse(fm_text).get(hash_key)
        except fm.FrontmatterError:
            ok = False
    old_block = extract_block(body) if ok else None
    if not ok or old_block is None or block_hash(old_block) != stored:
        new_text = assemble([fm.emit_key(k, v) for k, v in fields]) + head + fenced(block) + tail
        cpath = write_conflict(vfs, conflict_name, vfs.rel(path), new_text, ts)
        log.warning("Vault: %s was edited inside the generated block; new content in %s", vfs.rel(path), vfs.rel(cpath))
        return Outcome("conflict", path, cpath)

    ex_chunks = fm.chunks(fm_text)
    new_body = replace_block(body, block)

    if not sealed:
        status = _write_candidates(vfs, path, existing_text, lambda carry: assemble(merge_machine(fields, ex_chunks, carry)) + new_body)
        return Outcome(status, path)

    new_values = dict(fields)
    parsed_existing = fm.parse(fm_text)
    kept: list[str] = []
    for k, t in ex_chunks:
        if k is not None and k.startswith(OUTCOME_PREFIX):
            continue
        if k in fill_once and parsed_existing.get(k) is None and new_values.get(k) is not None:
            kept.append(fm.emit_key(k, new_values[k]))
        else:
            kept.append(t if t.endswith("\n") else t + "\n")
    outcome = [fm.emit_key(k, v) for k, v in fields if k.startswith(OUTCOME_PREFIX)]
    text = assemble(kept + outcome) + new_body
    return Outcome(vfs.write(path, text), path)
