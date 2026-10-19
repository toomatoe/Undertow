"""Input manifests and result comparison for reproducible study runs.

A manifest records the SHA-256 of every cache file a run read (SEC submissions, the
public-float frame, Yahoo price files, SEC insider data set zips and Form 4 XML), the code version (env GIT_SHA) and the hash of
the canonical results. It holds hashes and relative paths only, never file contents:
cached Yahoo data is for personal research use and must not be committed or published.

Read tracking: `get_json` (eventstudy) and `load_prices` (prices) call `record_read` /
`record_miss`. Tracking is off unless a study run calls `start_tracking()`, so the
long-lived API process (journal, backtest) does not accumulate paths.

CLI:
  python -m app.research.snapshot write [--study PATH]   # manifest for a results file
  python -m app.research.snapshot verify MANIFEST        # exit 1 if any input changed
  python -m app.research.snapshot compare A B [--ignore-added]   # prints IDENTICAL or DIFF
  ("-" as A or B reads that JSON from stdin.)
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

SNAPSHOT_DIR = "snapshots"
MANIFEST_VERSION = 1
# Ignored by the canonical form / compare_results at any depth: run timing and pointers.
VOLATILE_KEYS = frozenset({"generated_at", "inputs_manifest", "elapsed_seconds", "duration_seconds",
                           "started_at", "finished_at"})
# Cache locations scanned when no in-process read registry is available (CLI `write`).
# insider_datasets: SEC Form 3/4/5 data set zips (app.insiders.datasets.CACHE_SUBDIR);
# insider_xml: Form 4 primary-document XML for the cross-check (app.insiders.study.XML_CACHE_SUBDIR).
CACHE_SUBDIRS = ("submissions", "prices", "insider_datasets", "insider_xml")
# Cache file types hashed in those directories (download temp files such as *.part are skipped).
CACHE_EXTENSIONS = (".json", ".zip", ".xml")

_tracking = False
_reads: set[str] = set()
_misses: list[str] = []


# --- Read registry ---------------------------------------------------------------


def start_tracking() -> None:
    """Reset and enable the registry for one study run."""
    global _tracking
    _reads.clear()
    _misses.clear()
    _tracking = True


def stop_tracking() -> None:
    global _tracking
    _tracking = False


def record_read(path: str) -> None:
    if _tracking and path:
        _reads.add(os.path.abspath(path))


def record_miss(path: str) -> None:
    """An offline cache miss. Always recorded (offline runs must be able to fail loudly)."""
    if path not in _misses:
        _misses.append(path)


def reads() -> set[str]:
    return set(_reads)


def misses() -> list[str]:
    return list(_misses)


def clear_misses() -> None:
    _misses.clear()


# --- Hashing ---------------------------------------------------------------------


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in VOLATILE_KEYS}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def canonical(study: dict) -> str:
    """Stable JSON of a results document without generated_at, timing fields or the manifest pointer."""
    return json.dumps(_strip(study), sort_keys=True, separators=(",", ":"))


def results_sha256(study: dict) -> str:
    return hashlib.sha256(canonical(study).encode("utf-8")).hexdigest()


def _rel(path: str, base: str) -> str:
    return os.path.relpath(os.path.abspath(path), os.path.abspath(base)).replace(os.sep, "/")


def _all_cache_files(data_dir: str) -> list[str]:
    found = []
    for sub in CACHE_SUBDIRS:
        for root, _, files in os.walk(os.path.join(data_dir, sub)):
            found += [os.path.join(root, f) for f in files if f.endswith(CACHE_EXTENSIONS)]
    found += [os.path.join(data_dir, f) for f in os.listdir(data_dir) if f.startswith("public_float_")] \
        if os.path.isdir(data_dir) else []
    return found


# --- Manifests -------------------------------------------------------------------


def write_manifest(data_dir: str, study_json_path: str, read_paths: set[str] | None = None) -> str:
    """Write {data_dir}/snapshots/<study>_<UTC stamp>.json and return its path relative to data_dir.

    read_paths defaults to the in-process registry; when that is empty (e.g. the CLI), every
    cache file under data_dir is hashed instead and `reads_source` says so.
    """
    with open(study_json_path, encoding="utf-8") as f:
        study = json.load(f)
    config = study.get("config") or {}
    name = config.get("study") or "study"
    float_year = (config.get("design") or {}).get("float_year")

    paths = set(read_paths) if read_paths is not None else reads()
    source = "registry"
    if not paths:
        paths, source = set(_all_cache_files(data_dir)), "all_cache_files"

    frame = None
    if float_year is not None:
        frame_path = os.path.join(data_dir, f"public_float_CY{float_year}Q2I.json")
        if os.path.exists(frame_path):
            frame = {"path": _rel(frame_path, data_dir), "sha256": sha256_file(frame_path)}
            paths.add(os.path.abspath(frame_path))

    files = {_rel(p, data_dir): sha256_file(p) for p in sorted(paths) if os.path.isfile(p)}
    now = datetime.now(timezone.utc)
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "created_at": now.isoformat(),
        "study": name,
        "code_version": os.environ.get("GIT_SHA") or "unknown",
        "data_dir": os.path.abspath(data_dir),
        "results_file": _rel(study_json_path, data_dir),
        "results_sha256": results_sha256(study),
        "frame": frame,
        "reads_source": source,
        "n_files": len(files),
        "files": files,
    }
    out_dir = os.path.join(data_dir, SNAPSHOT_DIR)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"{name}_{now.strftime('%Y%m%dT%H%M%S%fZ')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    return _rel(out, data_dir)


def verify_manifest(path: str, data_dir: str | None = None) -> dict:
    """Re-hash every input listed in a manifest. data_dir defaults to the manifest's snapshots/ parent."""
    with open(path, encoding="utf-8") as f:
        manifest = json.load(f)
    base = data_dir or os.path.dirname(os.path.dirname(os.path.abspath(path)))
    missing, changed = [], []
    for rel, digest in sorted(manifest.get("files", {}).items()):
        full = os.path.join(base, rel)
        if not os.path.isfile(full):
            missing.append(rel)
        elif sha256_file(full) != digest:
            changed.append(rel)
    results_ok = None
    results_path = os.path.join(base, manifest.get("results_file", ""))
    if manifest.get("results_file") and os.path.isfile(results_path):
        with open(results_path, encoding="utf-8") as f:
            results_ok = results_sha256(json.load(f)) == manifest.get("results_sha256")
    return {
        "ok": not missing and not changed and results_ok is not False,
        "checked": len(manifest.get("files", {})),
        "missing": missing,
        "changed": changed,
        "results_match": results_ok,
    }


# --- Comparing results -----------------------------------------------------------


def _keyed(value):
    """Turn result rows into dicts keyed by (signal/bucket/horizon) so diffs name cells, not indexes."""
    if isinstance(value, list) and value and all(isinstance(r, dict) and "signal" in r for r in value):
        keyed = {}
        for r in value:
            k = "/".join(str(r.get(f)) for f in ("signal", "bucket", "horizon_days", "hypothesis") if f in r)
            keyed[k] = r
        return keyed
    return value


def _diff(a, b, path: str, out: list[str], ignore_added: bool) -> None:
    a, b = _keyed(a), _keyed(b)
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            p = f"{path}.{k}" if path else str(k)
            if k not in a:
                if not ignore_added:
                    out.append(f"{p} (added)")
            elif k not in b:
                out.append(f"{p} (removed)")
            else:
                _diff(a[k], b[k], p, out, ignore_added)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            # Under ignore_added a list in b that extends a (same leading items, extra tail) counts as
            # added, e.g. a caveat appended since the file was published. Leading items still compare.
            if ignore_added and len(b) > len(a):
                prefix: list[str] = []
                for i, (x, y) in enumerate(zip(a, b)):
                    _diff(x, y, f"{path}[{i}]", prefix, ignore_added)
                if not prefix:
                    return
            out.append(f"{path} (length {len(a)} -> {len(b)})")
            return
        for i, (x, y) in enumerate(zip(a, b)):
            _diff(x, y, f"{path}[{i}]", out, ignore_added)
    elif a != b:
        out.append(path)


def compare_results(a: dict, b: dict, ignore_added: bool = False) -> list[str]:
    """Differing key paths between two results documents (empty = identical).

    Ignores generated_at, timing fields and inputs_manifest at any depth. ignore_added skips keys
    present only in b, and list items appended at the end of b (the leading items must still match),
    e.g. when comparing a new run against a file published before additive fields and the extra caveat.
    """
    out: list[str] = []
    _diff(_strip(a), _strip(b), "", out, ignore_added)
    return out


# --- CLI -------------------------------------------------------------------------


def _load(path: str) -> dict:
    if path == "-":
        return json.load(sys.stdin)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Study input manifests and result comparison")
    sub = parser.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="write a manifest for a results file")
    w.add_argument("--data-dir", default=None)
    w.add_argument("--study", default=None, help="results JSON (default {DATA_DIR}/event_study.json)")
    v = sub.add_parser("verify", help="re-hash the inputs listed in a manifest")
    v.add_argument("manifest")
    v.add_argument("--data-dir", default=None)
    c = sub.add_parser("compare", help="canonical diff of two results files")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--ignore-added", action="store_true", help="ignore keys present only in B")
    args = parser.parse_args(argv)

    if args.cmd == "write":
        if args.data_dir is None:
            from app.config import get_settings
            args.data_dir = get_settings().data_dir
        study = args.study or os.path.join(args.data_dir, "event_study.json")
        print(write_manifest(args.data_dir, study, read_paths=set()))
        return 0
    if args.cmd == "verify":
        report = verify_manifest(args.manifest, args.data_dir)
        print(json.dumps(report, indent=1))
        return 0 if report["ok"] else 1
    diffs = compare_results(_load(args.a), _load(args.b), ignore_added=args.ignore_added)
    if not diffs:
        print("IDENTICAL")
        return 0
    print(f"DIFF ({len(diffs)} keys)")
    for d in diffs:
        print(f"  {d}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
