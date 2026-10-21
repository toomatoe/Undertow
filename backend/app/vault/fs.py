"""The ONLY place the vault package touches the filesystem for writing.

Rules (vault/AGENTS.md):
- every target resolves inside `<vault_dir>/Undertow` after realpath (no `..`, no symlink escape, no writing
  through a symlinked file);
- filename components are sanitized (A-Z a-z 0-9 . _ -, length cap, no leading dot);
- writes are atomic (temp file in the same directory + os.replace) and happen only when the bytes change;
- nothing is ever deleted. There is deliberately no delete helper in this module.
"""

from __future__ import annotations

import os
import re
import tempfile

ROOT_NAME = "Undertow"
MAX_COMPONENT = 120
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class UnsafePath(ValueError):
    """A path would leave <vault_dir>/Undertow or is otherwise not writable safely."""


def sanitize(component: str, max_len: int = MAX_COMPONENT) -> str:
    """One safe filename component: unsafe runs -> '-', no leading dots, capped length, never empty/'.'/'..'."""
    s = _UNSAFE.sub("-", str(component)).lstrip(".-").rstrip("-")
    s = s[:max_len].rstrip("-.") if len(s) > max_len else s
    if not s or s in (".", ".."):
        s = "untitled"
    return s


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:  # different drives (Windows)
        return False


class VaultFS:
    def __init__(self, vault_dir: str):
        self.vault_dir = os.path.realpath(os.path.abspath(vault_dir))
        self.root = os.path.join(self.vault_dir, ROOT_NAME)

    # --- path resolution ---------------------------------------------------------------------------------------

    def _check_root(self) -> str:
        real_root = os.path.realpath(self.root)
        if os.path.islink(self.root) or not _inside(real_root, self.vault_dir) or real_root == self.vault_dir:
            raise UnsafePath(f"{self.root} must be a real directory inside the vault")
        return real_root

    def ensure_root(self) -> None:
        os.makedirs(self.vault_dir, exist_ok=True)
        if not os.path.exists(self.root):
            os.makedirs(self.root, exist_ok=True)
        self._check_root()

    def path(self, *parts: str) -> str:
        """Absolute path for Undertow/<parts...>. The LAST part is sanitized as a filename (extension kept);
        folder parts must already be safe names. Raises UnsafePath."""
        if not parts:
            raise UnsafePath("empty path")
        folders = list(parts[:-1])
        for f in folders:
            if f != sanitize(f) or f in (".", ".."):
                raise UnsafePath(f"unsafe folder {f!r}")
        name = parts[-1]
        stem, dot, ext = name.rpartition(".")
        if not dot or not stem:
            stem, ext = name, ""
        ext = _UNSAFE.sub("", ext)[:10]
        filename = sanitize(stem) + (f".{ext}" if ext else "")
        real_root = self._check_root()
        target = os.path.join(real_root, *folders, filename)
        parent = os.path.realpath(os.path.dirname(target))
        if not _inside(parent, real_root):
            raise UnsafePath(f"{target} resolves outside {real_root}")
        if os.path.islink(target):
            raise UnsafePath(f"{target} is a symlink")
        if os.path.exists(target) and not _inside(os.path.realpath(target), real_root):
            raise UnsafePath(f"{target} resolves outside {real_root}")
        return target

    def rel(self, abs_path: str) -> str:
        """Path relative to the vault root, forward slashes (for links and results)."""
        return os.path.relpath(abs_path, self.vault_dir).replace(os.sep, "/")

    # --- reading -----------------------------------------------------------------------------------------------

    @staticmethod
    def read_bytes(path: str) -> bytes | None:
        try:
            with open(path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def read_text(self, path: str) -> str | None:
        b = self.read_bytes(path)
        return None if b is None else b.decode("utf-8", errors="replace")

    def listdir(self, *folders: str) -> list[str]:
        """Sorted file names (not dirs, not dotfiles, not symlinks) in Undertow/<folders>."""
        real_root = self._check_root()
        d = os.path.join(real_root, *folders)
        if not os.path.isdir(d) or os.path.islink(d):
            return []
        return sorted(
            n for n in os.listdir(d)
            if not n.startswith(".") and os.path.isfile(os.path.join(d, n)) and not os.path.islink(os.path.join(d, n))
        )

    # --- writing -----------------------------------------------------------------------------------------------

    def write(self, path: str, data: bytes | str) -> str:
        """Atomically write `data` if it differs from what is there. Returns 'created' | 'updated' | 'unchanged'.

        `path` must come from self.path() (re-checked here)."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        real_root = self._check_root()
        parent = os.path.dirname(path)
        if not _inside(os.path.realpath(parent) if os.path.exists(parent) else os.path.abspath(parent), real_root):
            raise UnsafePath(f"{path} is outside {real_root}")
        if os.path.islink(path):
            raise UnsafePath(f"{path} is a symlink")
        existing = self.read_bytes(path)
        if existing == data:
            return "unchanged"
        os.makedirs(parent, exist_ok=True)
        if not _inside(os.path.realpath(parent), real_root):
            raise UnsafePath(f"{path} is outside {real_root}")
        fd, tmp = tempfile.mkstemp(dir=parent, prefix=".undertow-", suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)  # mkstemp creates 0600; the vault owner (Obsidian, on the host) must be able to read it
        os.replace(tmp, path)
        return "created" if existing is None else "updated"

    def append_line(self, path: str, line: str, header: str = "") -> None:
        """Append one line (append-only file such as log.md); writes `header` first when the file is new."""
        real_root = self._check_root()
        if not _inside(os.path.realpath(os.path.dirname(path)), real_root) or os.path.islink(path):
            raise UnsafePath(f"{path} is outside {real_root}")
        new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if new and header:
                f.write(header)
            f.write(line.rstrip("\n") + "\n")
