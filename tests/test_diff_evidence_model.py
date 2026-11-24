import json

import pytest
from conftest import finding, make_scan

from accesspilot.diff import diff_scans, render_diff_markdown
from accesspilot.evidence import EvidenceLog
from accesspilot.model import Scan


def test_scan_roundtrip(tmp_path):
    scan = make_scan([finding(1)])
    digest = scan.save(tmp_path / "scan.json")
    again = Scan.load(tmp_path / "scan.json")
    assert again == scan and len(digest) == 64


def test_old_schema_is_refused(tmp_path):
    d = make_scan().to_dict()
    d["schema_version"] = 1
    (tmp_path / "s.json").write_text(json.dumps(d))
    with pytest.raises(ValueError, match="schema_version"):
        Scan.load(tmp_path / "s.json")


def test_diff_new_fixed_persisting():
    a, b, c = finding(1), finding(2, rule="label"), finding(3, rule="button-name")
    old = make_scan([a, b], scan_id="old")
    new = make_scan([b, c], scan_id="new", started="2026-02-01T10:00:00+00:00")
    d = diff_scans(old, new)
    assert [f.rule for f in d.introduced] == ["button-name"]
    assert [f.rule for f in d.fixed] == ["image-alt"]
    assert d.persisting == 1 and d.regressed
    assert "1** défauts corrigés" in render_diff_markdown(d)


def test_diff_ignores_templates_not_tested_in_both():
    old = make_scan([finding(1, template="cart")], templates=("home", "cart"))
    new = make_scan([], templates=("home",))  # the cart page failed to load this time
    d = diff_scans(old, new)
    assert d.fixed == [] and d.compared_templates == ["home"]


def test_diff_refuses_other_site():
    with pytest.raises(ValueError):
        diff_scans(make_scan(site="a.fr"), make_scan(site="b.fr"))


def test_evidence_chain_and_tamper_detection(tmp_path):
    log = EvidenceLog(tmp_path / "evidence.jsonl")
    scan_file = tmp_path / "scan.json"
    digest = make_scan().save(scan_file)
    log.append("scan", {"site": "x", "scan_file": "scan.json", "scan_sha256": digest})
    log.append("scan", {"site": "x"})
    assert log.verify()[0]

    scan_file.write_text(scan_file.read_text().replace("shop.example", "other.example"))
    ok, msgs = log.verify()
    assert not ok and "modified" in msgs[0]
    assert log.verify(check_files=False)[0]

    lines = log.path.read_text().splitlines()
    rec = json.loads(lines[0])
    rec["payload"]["site"] = "y"
    log.path.write_text(json.dumps(rec) + "\n" + lines[1] + "\n")
    ok, msgs = log.verify(check_files=False)
    assert not ok and any("edited" in m for m in msgs)

    log.path.write_text(lines[1] + "\n")  # first entry deleted
    ok, msgs = log.verify(check_files=False)
    assert not ok and "chain broken" in msgs[0]
