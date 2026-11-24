"""Report, statement and guard: what the tool writes must never overclaim."""
import pytest
from conftest import finding, make_scan

from accesspilot.guard import banned_hits, check_statement, check_text
from accesspilot.plan import build_plan
from accesspilot.report import render_html, render_markdown
from accesspilot.rgaa import NOT_TESTED_BY_AUTOMATION
from accesspilot.statement import render_statement


@pytest.mark.parametrize("text", ["Votre site est conforme au RGAA.", "100 % accessible !",
                                  "Site fully compliant", "Taux de conformité : 87 %"])
def test_guard_rejects_claims(text):
    assert not check_text(text).ok


@pytest.mark.parametrize("text", ["Le site est non conforme.", "Zoom à 200 % non testé.",
                                  "Ajouter un attribut alt."])
def test_guard_accepts_honest_text(text):
    assert check_text(text).ok, check_text(text).reasons


def test_guard_checks_citations():
    v = check_text("ok", valid_ids={"a"}, cited_ids=["a", "b"])
    assert not v.ok and "G2" in v.reasons[0]


def test_statement_is_honest_and_complete():
    scan = make_scan([finding(1), finding(2, rule="label")])
    st = render_statement(scan)
    assert check_statement(st).ok, check_statement(st).reasons
    assert "non conforme" in st and "[À COMPLÉTER]" in st
    assert all(item in st for item in NOT_TESTED_BY_AUTOMATION)
    assert "Défenseur des droits" in st


def test_statement_with_no_findings_does_not_claim_accessibility():
    st = render_statement(make_scan([]))
    assert check_statement(st).ok
    assert "ne signifie pas que le site est accessible" in st


def test_reports_pass_guard_and_list_limits():
    scan = make_scan([finding(i) for i in range(1, 6)])
    plan = build_plan(scan)
    for text in (render_markdown(scan, plan), render_html(scan, plan)):
        assert check_text(text).ok
        assert NOT_TESTED_BY_AUTOMATION[0].split(" (")[0] in text
        assert "pas un audit de conformité" in text


def test_html_report_escapes_page_content():
    evil = '<script>alert(1)</script>'
    scan = make_scan([finding(1, html=evil, selector='a[title="<b>"]')])
    out = render_html(scan, build_plan(scan))
    assert "<script>alert(1)</script>" not in out and "&lt;script&gt;" in out


def test_markdown_report_neutralises_html():
    scan = make_scan([finding(1, html="<template>x</template>")])
    md = render_markdown(scan, build_plan(scan))
    assert "`<template>x</template>`" in md


def test_banned_hits_masks_required_status():
    assert banned_hits("Le site est non conforme") == []
