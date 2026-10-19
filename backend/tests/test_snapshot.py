import io
import json

from app.research import snapshot


def _study(**extra):
    return {
        "generated_at": "2026-10-19T00:00:00+00:00",
        "config": {"study": "in_sample", "design": {"float_year": 2023}},
        "results": [
            {"signal": "offering_priced", "bucket": "nano", "horizon_days": 20, "t_stat": -6.67},
            {"signal": "offering_priced", "bucket": "nano", "horizon_days": 5, "t_stat": -3.1},
        ],
        **extra,
    }


def _cache(tmp_path):
    (tmp_path / "submissions").mkdir()
    (tmp_path / "prices").mkdir()
    (tmp_path / "submissions" / "1.json").write_text('{"tickers": ["A"]}')
    (tmp_path / "prices" / "A_x_y.json").write_text('{"chart": {}}')
    (tmp_path / "public_float_CY2023Q2I.json").write_text('{"data": []}')
    study = tmp_path / "event_study.json"
    study.write_text(json.dumps(_study()))
    return study


def test_manifest_round_trip_and_tamper_detection(tmp_path):
    study = _cache(tmp_path)
    snapshot.start_tracking()
    snapshot.record_read(str(tmp_path / "submissions" / "1.json"))
    snapshot.record_read(str(tmp_path / "prices" / "A_x_y.json"))
    rel = snapshot.write_manifest(str(tmp_path), str(study))
    snapshot.stop_tracking()

    assert rel.startswith("snapshots/in_sample_")
    manifest = json.loads((tmp_path / rel).read_text())
    assert manifest["reads_source"] == "registry"
    assert set(manifest["files"]) == {"submissions/1.json", "prices/A_x_y.json", "public_float_CY2023Q2I.json"}
    assert manifest["frame"]["path"] == "public_float_CY2023Q2I.json"
    # Hashes only: no cached content leaks into the manifest
    text = (tmp_path / rel).read_text()
    assert "tickers" not in text and "chart" not in text
    assert all(len(h) == 64 for h in manifest["files"].values())

    report = snapshot.verify_manifest(str(tmp_path / rel))
    assert report["ok"] and report["checked"] == 3 and report["results_match"] is True

    (tmp_path / "prices" / "A_x_y.json").write_text('{"chart": {"tampered": true}}')
    report = snapshot.verify_manifest(str(tmp_path / rel))
    assert not report["ok"] and report["changed"] == ["prices/A_x_y.json"]

    (tmp_path / "submissions" / "1.json").unlink()
    assert snapshot.verify_manifest(str(tmp_path / rel))["missing"] == ["submissions/1.json"]


def test_verify_detects_changed_results(tmp_path):
    study = _cache(tmp_path)
    rel = snapshot.write_manifest(str(tmp_path), str(study), read_paths={str(tmp_path / "submissions" / "1.json")})
    changed = _study()
    changed["results"][0]["t_stat"] = -1.0
    study.write_text(json.dumps(changed))
    report = snapshot.verify_manifest(str(tmp_path / rel))
    assert report["results_match"] is False and not report["ok"]


def test_manifest_records_git_sha(tmp_path, monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)
    study = _cache(tmp_path)
    rel = snapshot.write_manifest(str(tmp_path), str(study), read_paths=set())
    assert json.loads((tmp_path / rel).read_text())["code_version"] == "unknown"
    monkeypatch.setenv("GIT_SHA", "abc123")
    rel = snapshot.write_manifest(str(tmp_path), str(study), read_paths=set())
    manifest = json.loads((tmp_path / rel).read_text())
    assert manifest["code_version"] == "abc123"
    assert manifest["reads_source"] == "all_cache_files" and manifest["n_files"] == 3


def test_registry_is_off_unless_tracking():
    snapshot.stop_tracking()
    snapshot.start_tracking()
    snapshot.stop_tracking()
    snapshot.record_read("/somewhere/file.json")
    assert snapshot.reads() == set()


def test_compare_ignores_generated_at_and_timing():
    a = _study()
    b = _study(inputs_manifest="snapshots/x.json")
    b["generated_at"] = "2030-01-01T00:00:00+00:00"
    b["elapsed_seconds"] = 12.5
    assert snapshot.compare_results(a, b) == []
    assert snapshot.results_sha256(a) == snapshot.results_sha256(b)


def test_compare_names_differing_cells_and_added_keys():
    a, b = _study(), _study()
    b["results"][0]["t_stat"] = -2.0
    b["results"][1]["t_stat_clustered"] = -1.5
    diffs = snapshot.compare_results(a, b)
    assert "results.offering_priced/nano/20.t_stat" in diffs
    assert "results.offering_priced/nano/5.t_stat_clustered (added)" in diffs
    assert snapshot.compare_results(a, b, ignore_added=True) == ["results.offering_priced/nano/20.t_stat"]
    del b["config"]["study"]
    assert "config.study (removed)" in snapshot.compare_results(a, b, ignore_added=True)


def _old_published():
    """A file published before the additive fields: 6 caveats, no clustered fields, no study/design."""
    return {
        "generated_at": "2026-10-15T20:21:42+00:00",
        "config": {"window": ["2023-10-01", "2026-08-31"], "horizons": [5, 20]},
        "caveats": [f"caveat {i}" for i in range(6)],
        "results": [
            {"signal": "offering_priced", "bucket": "nano", "horizon_days": 20, "t_stat": -6.67, "n": 300},
            {"signal": "offering_priced", "bucket": "nano", "horizon_days": 5, "t_stat": -3.1, "n": 300},
        ],
    }


def test_compare_ignore_added_tolerates_appended_caveat_and_additive_fields():
    old = _old_published()
    new = json.loads(json.dumps(old))
    new["generated_at"] = "2026-10-19T00:00:00+00:00"
    new["config"]["study"] = "in_sample"
    new["config"]["design"] = {"float_year": 2023}
    new["inputs_manifest"] = "snapshots/x.json"
    new["caveats"].append("t-stats clustered by company")
    for row in new["results"]:
        row["t_stat_clustered"] = row["t_stat"] / 2
        row["t_vs_baseline_clustered"] = 1.0
        row["clusters"] = 40
    assert snapshot.compare_results(old, new, ignore_added=True) == []
    # Without ignore_added the appended caveat is still reported.
    assert "caveats (length 6 -> 7)" in snapshot.compare_results(old, new)
    # A changed leading caveat, a removed caveat or a changed value is still a diff.
    changed = json.loads(json.dumps(new))
    changed["caveats"][0] = "different"
    assert snapshot.compare_results(old, changed, ignore_added=True) == ["caveats (length 6 -> 7)"]
    shorter = json.loads(json.dumps(new))
    shorter["caveats"] = shorter["caveats"][:5]
    assert snapshot.compare_results(old, shorter, ignore_added=True) == ["caveats (length 6 -> 5)"]
    changed = json.loads(json.dumps(new))
    changed["results"][0]["t_stat"] = -1.0
    assert snapshot.compare_results(old, changed, ignore_added=True) == ["results.offering_priced/nano/20.t_stat"]


def test_cli_compare_prints_identical_or_diff(tmp_path, capsys, monkeypatch):
    p1, p2 = tmp_path / "a.json", tmp_path / "b.json"
    p1.write_text(json.dumps(_study()))
    p2.write_text(json.dumps(_study(generated_at="later")))
    assert snapshot.main(["compare", str(p1), str(p2)]) == 0
    assert capsys.readouterr().out.strip() == "IDENTICAL"

    changed = _study()
    changed["results"][0]["t_stat"] = 0.0
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(changed)))
    assert snapshot.main(["compare", str(p1), "-"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("DIFF (1 keys)") and "results.offering_priced/nano/20.t_stat" in out


def test_cli_write_and_verify(tmp_path, capsys):
    study = _cache(tmp_path)
    assert snapshot.main(["write", "--data-dir", str(tmp_path), "--study", str(study)]) == 0
    rel = capsys.readouterr().out.strip()
    assert snapshot.main(["verify", str(tmp_path / rel)]) == 0
    (tmp_path / "public_float_CY2023Q2I.json").write_text("{}")
    assert snapshot.main(["verify", str(tmp_path / rel)]) == 1


def test_cache_subdirs_match_insider_caches():
    from app.insiders import datasets, study

    assert datasets.CACHE_SUBDIR in snapshot.CACHE_SUBDIRS
    assert study.XML_CACHE_SUBDIR in snapshot.CACHE_SUBDIRS


def test_cli_write_hashes_insider_caches(tmp_path, capsys):
    study = _cache(tmp_path)
    (tmp_path / "insider_datasets").mkdir()
    (tmp_path / "insider_datasets" / "2024q1_form345.zip").write_bytes(b"PK\x03\x04zip")
    (tmp_path / "insider_datasets" / "2024q2_form345.zip.part").write_bytes(b"PK partial")
    (tmp_path / "insider_xml").mkdir()
    (tmp_path / "insider_xml" / "0001-24-000001.xml").write_text("<ownershipDocument/>")
    assert snapshot.main(["write", "--data-dir", str(tmp_path), "--study", str(study)]) == 0
    rel = capsys.readouterr().out.strip()
    manifest = json.loads((tmp_path / rel).read_text())
    assert manifest["reads_source"] == "all_cache_files"
    assert "insider_datasets/2024q1_form345.zip" in manifest["files"]
    assert "insider_xml/0001-24-000001.xml" in manifest["files"]
    assert not any(p.endswith(".part") for p in manifest["files"])
    (tmp_path / "insider_xml" / "0001-24-000001.xml").write_text("<changed/>")
    assert snapshot.main(["verify", str(tmp_path / rel)]) == 1
