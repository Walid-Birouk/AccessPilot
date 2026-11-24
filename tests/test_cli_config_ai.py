import json

import pytest
from conftest import finding, make_scan

from accesspilot import ai
from accesspilot.cli import main
from accesspilot.config import load_settings
from accesspilot.plan import build_plan
from accesspilot.scan.crawler import canonical, followable, normalise_start_url, same_site

# ---- config

def test_settings_precedence(tmp_path):
    cfg = tmp_path / "a.toml"
    cfg.write_text('[scan]\nmax_pages = 7\nper_template = 1\n[templates]\nproduct = ["/item/"]\n')
    s = load_settings(cfg, per_template=4, max_depth=None)
    assert (s.max_pages, s.per_template, s.max_depth) == (7, 4, 2)
    assert s.templates == {"product": ["/item/"]}


def test_settings_reject_unknown_and_invalid(tmp_path):
    cfg = tmp_path / "a.toml"
    cfg.write_text("[scan]\nmax_pagez = 7\n")
    with pytest.raises(ValueError, match="unknown setting"):
        load_settings(cfg)
    with pytest.raises(ValueError, match="max_pages"):
        load_settings(None, max_pages=0)
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "none.toml")


# ---- crawler URL rules (no browser)

def test_url_rules():
    assert normalise_start_url("Shop.fr") == "https://shop.fr/"
    assert same_site("https://www.shop.fr/a", "https://shop.fr/")
    assert not same_site("https://shop.fr.evil.com/", "https://shop.fr/")
    assert canonical("https://shop.fr/cart/#x") == "https://shop.fr/cart"
    site = "https://shop.fr/"
    assert followable("https://shop.fr/products/robe", site)
    for bad in ("https://shop.fr/account/logout", "https://shop.fr/cart/add?id=1",
                "https://shop.fr/cat.pdf", "https://other.fr/", "mailto:a@b.fr",
                "https://shop.fr/p?action=delete"):
        assert not followable(bad, site), bad


# ---- CLI on saved scans (no browser)

def _write(tmp_path, scan, name):
    d = tmp_path / name
    d.mkdir()
    scan.save(d / "scan.json")
    return d / "scan.json"


def test_cli_report_writes_files(tmp_path, capsys):
    p = _write(tmp_path, make_scan([finding(1), finding(2, rule="label")]), "a")
    assert main(["report", str(p), "--json", "-q"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["defects"] == 2 and out["fixes"] == 2
    for f in ("rapport.html", "rapport.md", "declaration-accessibilite.BROUILLON.md", "plan.json"):
        assert (p.parent / f).exists()


def test_cli_diff_exit_codes(tmp_path, capsys):
    old = _write(tmp_path, make_scan([finding(1)], scan_id="o"), "old")
    new = _write(tmp_path, make_scan([finding(1), finding(2, rule="label")], scan_id="n"), "new")
    assert main(["diff", str(old), str(new)]) == 0
    assert main(["diff", str(old), str(new), "--fail-on-new"]) == 1
    assert main(["diff", str(new), str(old), "--fail-on-new"]) == 0


def test_cli_errors_are_one_line(tmp_path, capsys):
    assert main(["report", str(tmp_path / "missing.json")]) == 2
    assert "error:" in capsys.readouterr().err
    assert main(["verify", "--log", str(tmp_path / "nope.jsonl")]) == 2


def test_cli_exemption_rejects_bad_siren(capsys):
    assert main(["exemption", "123 456"]) == 2


# ---- optional AI step, with a fake LLM

def _plan():
    scan = make_scan([finding(1), finding(2, rule="label")])
    return build_plan(scan)


def test_ai_rewrites_only_guarded_text():
    plan = _plan()

    def fake(system, user):
        items = json.loads(user)["fixes"]
        return json.dumps({"fixes": [
            {"priority": items[0]["priority"], "instructions": "Ajouter alt=\"Robe rouge\" à l'image.",
             "evidence_ids": items[0]["evidence_ids"]},
            {"priority": items[1]["priority"], "instructions": "Le site est conforme au RGAA.",
             "evidence_ids": items[1]["evidence_ids"]},
        ]})

    n, rejected = ai.enrich(plan, fake, log=lambda m: None)
    assert n == 1 and len(rejected) == 1 and "G1" in rejected[0]
    assert plan[0].source == "ai" and plan[1].source == "rules"
    assert "conforme" not in plan[1].instructions


def test_ai_rejects_foreign_evidence_ids_and_bad_json():
    plan = _plan()
    before = plan[0].instructions
    fake = lambda s, u: json.dumps({"fixes": [{"priority": 1, "instructions": "x", "evidence_ids": ["zzz"]}]})  # noqa: E731
    assert ai.enrich(plan, fake, log=lambda m: None)[0] == 0
    assert ai.enrich(plan, lambda s, u: "not json", log=lambda m: None)[0] == 0
    assert plan[0].instructions == before


def test_ai_needs_configuration(monkeypatch):
    monkeypatch.delenv("ACCESSPILOT_LLM_API_KEY", raising=False)
    with pytest.raises(ai.AIError):
        ai.llm_from_env()


def test_scanned_page_text_cannot_break_the_statement(tmp_path):
    scan = make_scan([finding(1)])
    scan.pages[0].title = "Boutique 100% accessible, conforme au RGAA"
    p = _write(tmp_path, scan, "t")
    assert main(["report", str(p), "-q"]) == 0
    assert "conforme au RGAA" not in (p.parent / "declaration-accessibilite.BROUILLON.md").read_text()
