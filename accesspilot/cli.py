"""Command line: ``accesspilot scan | report | diff | exemption | verify | ui``.

Exit codes: 0 success, 1 a --fail-on / --fail-on-new threshold was hit,
2 usage or runtime error.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .model import IMPACTS, Scan, impact_rank

EXIT_OK, EXIT_THRESHOLD, EXIT_ERROR = 0, 1, 2


def _log(quiet: bool):
    return (lambda _msg: None) if quiet else (lambda msg: print(msg, file=sys.stderr))


def _write_outputs(scan: Scan, out: Path, baseline: Scan | None, use_ai: bool,
                   statement: bool, log) -> dict:
    from .diff import diff_scans, render_diff_html, render_diff_markdown
    from .guard import check_statement
    from .plan import build_plan
    from .report import render_html, render_markdown, summary
    from .statement import render_statement

    out.mkdir(parents=True, exist_ok=True)
    plan = build_plan(scan)
    if use_ai and plan:
        from .ai import enrich, llm_from_env
        _, rejected = enrich(plan, llm_from_env(), log)
        for r in rejected:
            log(f"    guard: {r}")

    d = None
    if baseline is not None:
        d = diff_scans(baseline, scan)
    md = render_markdown(scan, plan, render_diff_markdown(d) if d else None)
    html = render_html(scan, plan, render_diff_html(d) if d else None)
    (out / "rapport.md").write_text(md, encoding="utf-8")
    (out / "rapport.html").write_text(html, encoding="utf-8")
    written = ["rapport.html", "rapport.md"]
    if statement:
        st = render_statement(scan)
        v = check_statement(st)
        if not v.ok:
            raise RuntimeError(f"claim guard rejected the statement: {v.reasons}")
        (out / "declaration-accessibilite.BROUILLON.md").write_text(st, encoding="utf-8")
        written.append("declaration-accessibilite.BROUILLON.md")
    plan_json = [fx.__dict__ for fx in plan]
    (out / "plan.json").write_text(json.dumps(plan_json, ensure_ascii=False, indent=1), encoding="utf-8")
    written.append("plan.json")
    result = {"out": str(out), "files": written, **summary(scan, plan)}
    if d:
        result["diff"] = {"baseline": d.old.scan_id, "introduced": len(d.introduced),
                          "fixed": len(d.fixed), "persisting": d.persisting}
    return result


def _latest_scan(site_dir: Path, exclude: Path | None = None) -> Path | None:
    if not site_dir.is_dir():
        return None
    found = sorted(p for p in site_dir.glob("*/scan.json") if p.parent != exclude)
    return found[-1] if found else None


def _threshold_hit(scan: Scan, fail_on: str) -> int:
    if fail_on == "none":
        return 0
    limit = impact_rank(fail_on)
    return sum(1 for f in scan.findings if impact_rank(f.impact) >= limit)


def run_scan(url: str, settings, reports_dir: Path, log, *, out: Path | None = None,
             baseline_path: Path | None = None, use_baseline: bool = True, use_ai: bool = False,
             statement: bool = True, evidence: bool = True,
             log_path: Path | None = None) -> tuple[Scan, dict]:
    """Scan, compare with the previous scan of the site, write every output, log it.

    Shared by ``accesspilot scan`` and the local web UI. Returns (scan, summary).
    """
    from .scan.crawler import scan_site

    scan = scan_site(url, settings, log)
    site_dir = reports_dir / scan.site
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    if out is None:
        out = site_dir / stamp
        n = 2
        while (out / "scan.json").exists():  # two scans in the same second
            out = site_dir / f"{stamp}-{n}"
            n += 1
    out.mkdir(parents=True, exist_ok=True)

    baseline = None
    if baseline_path:
        baseline = Scan.load(baseline_path)
    elif use_baseline:
        prev = _latest_scan(site_dir, exclude=out)
        if prev:
            try:
                baseline = Scan.load(prev)
                log(f"  comparing with previous scan {prev.parent.name}")
            except ValueError as e:
                log(f"  previous scan ignored: {e}")
    if baseline is not None and baseline.site != scan.site:
        log(f"  baseline is of {baseline.site}, not {scan.site}: not compared")
        baseline = None

    scan_path = out / "scan.json"
    digest = scan.save(scan_path)
    result = _write_outputs(scan, out, baseline, use_ai, statement, log)
    result["files"].insert(0, "scan.json")

    if evidence:
        from .evidence import EvidenceLog
        log_path = log_path or reports_dir / "evidence.jsonl"
        EvidenceLog(log_path).append("scan", {
            "site": scan.site, "scan_id": scan.scan_id, "started": scan.started,
            "pages_tested": result["pages_tested"], "defects": result["defects"],
            "by_impact": result["by_impact"], "tool_versions": scan.tool_versions,
            "scan_file": os.path.relpath(scan_path.resolve(), log_path.parent.resolve()),
            "scan_sha256": digest,
        })
        result["evidence_log"] = str(log_path)
    return scan, result


def cmd_scan(args: argparse.Namespace) -> int:
    from .config import load_settings

    log = _log(args.quiet)
    settings = load_settings(
        args.config, max_pages=args.max_pages, max_depth=args.max_depth,
        per_template=args.per_template, time_budget_s=args.time_budget,
        respect_robots=False if args.ignore_robots else None,
        locale=args.locale, chromium_path=args.chromium,
        extra_urls=args.page or None,
    )
    log(f"Scanning {args.url} (up to {settings.max_pages} pages, "
        f"{settings.per_template} per template)...")
    scan, result = run_scan(
        args.url, settings, Path(args.reports_dir), log,
        out=Path(args.out) if args.out else None,
        baseline_path=Path(args.baseline) if args.baseline else None,
        use_baseline=not args.no_baseline, use_ai=args.ai, statement=not args.no_statement,
        evidence=not args.no_log, log_path=Path(args.log) if args.log else None)

    _print_result(result, args.json)
    code = EXIT_OK
    hit = _threshold_hit(scan, args.fail_on)
    if hit:
        log(f"FAIL: {hit} defect(s) at or above '{args.fail_on}'")
        code = EXIT_THRESHOLD
    if args.fail_on_new and result.get("diff", {}).get("introduced"):
        log(f"FAIL: {result['diff']['introduced']} new defect(s) since the baseline")
        code = EXIT_THRESHOLD
    return code


def _print_result(result: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return
    bi = result["by_impact"]
    print(f"\n{result['site']}: {result['defects']} defects on {result['pages_tested']} pages "
          f"({', '.join(f'{bi.get(i, 0)} {i}' for i in IMPACTS)}), {result['fixes']} fixes.")
    if result.get("pages_failed"):
        print(f"{result['pages_failed']} page(s) could not be tested (see the report).")
    if "diff" in result:
        d = result["diff"]
        print(f"Since the previous scan: {d['fixed']} fixed, {d['introduced']} new.")
    print(f"Report: {Path(result['out']) / 'rapport.html'}")


def cmd_report(args: argparse.Namespace) -> int:
    scan = Scan.load(Path(args.scan))
    baseline = Scan.load(Path(args.baseline)) if args.baseline else None
    out = Path(args.out) if args.out else Path(args.scan).parent
    result = _write_outputs(scan, out, baseline, args.ai, not args.no_statement, _log(args.quiet))
    _print_result(result, args.json)
    return EXIT_OK


def cmd_diff(args: argparse.Namespace) -> int:
    from .diff import diff_scans, render_diff_markdown
    d = diff_scans(Scan.load(Path(args.old)), Scan.load(Path(args.new)))
    if args.json:
        print(json.dumps({"introduced": [f.__dict__ for f in d.introduced],
                          "fixed": [f.__dict__ for f in d.fixed], "persisting": d.persisting,
                          "compared_templates": d.compared_templates}, ensure_ascii=False, indent=1))
    else:
        print(render_diff_markdown(d))
    return EXIT_THRESHOLD if (args.fail_on_new and d.regressed) else EXIT_OK


def cmd_exemption(args: argparse.Namespace) -> int:
    from .exemption import check_target

    res = check_target(args.target, log=lambda m: print(m, file=sys.stderr))
    if args.json:
        print(json.dumps(res.__dict__, ensure_ascii=False, indent=1))
    else:
        label = {"likely_exempt": "LIKELY EXEMPT", "not_exempt": "NOT EXEMPT",
                 "unknown": "UNKNOWN"}[res.status]
        print(f"{label}: {res.company or '?'} (SIREN {res.siren or '?'})")
        for r in res.reasons:
            print(f"  - {r}")
        print("Orientation only, from public register data; not legal advice. The exemption "
              "covers services, not products.")
    return EXIT_OK


def cmd_ui(args: argparse.Namespace) -> int:
    from .ui.server import serve
    return serve(Path(args.reports_dir), port=args.port, open_browser=not args.no_browser,
                 config=args.config, chromium=args.chromium)


def cmd_verify(args: argparse.Namespace) -> int:
    from .evidence import EvidenceLog
    path = Path(args.log) if args.log else Path(args.reports_dir) / "evidence.jsonl"
    if not path.exists():
        print(f"error: no evidence log at {path}", file=sys.stderr)
        return EXIT_ERROR
    ok, messages = EvidenceLog(path).verify(check_files=not args.chain_only)
    for m in messages:
        print(("OK: " if ok else "PROBLEM: ") + m)
    return EXIT_OK if ok else EXIT_THRESHOLD


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="accesspilot",
        description="Automated accessibility scans for online shops (EAA / RGAA / WCAG 2.1 AA): "
                    "prioritised fix plan per page template, draft accessibility statement, "
                    "and a tamper-evident history of scans.")
    ap.add_argument("--version", action="version", version=f"accesspilot {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="COMMAND")

    def common_out(p: argparse.ArgumentParser) -> None:
        p.add_argument("--ai", action="store_true",
                       help="rewrite fix instructions for the exact code found, with an LLM "
                            "(see ACCESSPILOT_LLM_* env vars); guarded, optional")
        p.add_argument("--no-statement", action="store_true",
                       help="do not write the draft accessibility statement")
        p.add_argument("--json", action="store_true", help="print a JSON summary on stdout")
        p.add_argument("-q", "--quiet", action="store_true", help="no progress output")

    p = sub.add_parser("scan", help="scan a site and write the report, fix plan and statement")
    p.add_argument("url", help="site address, e.g. https://www.example.fr")
    p.add_argument("--page", action="append", metavar="URL",
                   help="also test this page (repeatable), e.g. /panier or a product URL")
    p.add_argument("--max-pages", type=int)
    p.add_argument("--max-depth", type=int)
    p.add_argument("--per-template", type=int, help="pages tested per template (default 3)")
    p.add_argument("--time-budget", type=int, metavar="SECONDS")
    p.add_argument("--ignore-robots", action="store_true",
                   help="ignore robots.txt (only for a site you own or are authorised to test)")
    p.add_argument("--locale", choices=["fr", "en"], help="language of axe-core messages")
    p.add_argument("--chromium", metavar="PATH", help="Chromium binary (default: Playwright's)")
    p.add_argument("--config", metavar="FILE", help="TOML settings (default ./accesspilot.toml)")
    p.add_argument("--reports-dir", default="accesspilot-reports",
                   help="root for reports and the evidence log (default ./accesspilot-reports)")
    p.add_argument("--out", metavar="DIR", help="write this scan's files here instead")
    p.add_argument("--baseline", metavar="SCAN_JSON",
                   help="compare with this scan (default: the previous scan of the same site)")
    p.add_argument("--no-baseline", action="store_true", help="do not compare with a previous scan")
    p.add_argument("--fail-on", choices=["none", *reversed(IMPACTS)], default="none",
                   help="exit 1 if any defect at or above this impact is found (for CI)")
    p.add_argument("--fail-on-new", action="store_true",
                   help="exit 1 if the scan has defects the baseline did not (for CI)")
    p.add_argument("--log", metavar="FILE", help="evidence log (default REPORTS_DIR/evidence.jsonl)")
    p.add_argument("--no-log", action="store_true", help="do not record this scan in the evidence log")
    common_out(p)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("report", help="re-render reports from an existing scan.json (no browser)")
    p.add_argument("scan", help="path to scan.json")
    p.add_argument("--baseline", metavar="SCAN_JSON")
    p.add_argument("--out", metavar="DIR", help="default: the scan's directory")
    common_out(p)
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("diff", help="compare two scans of the same site")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--fail-on-new", action="store_true", help="exit 1 if new defects appeared")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("exemption",
                       help="check whether the EAA microenterprise exemption likely applies")
    p.add_argument("target", help="SIREN, SIRET, or the shop's address (its SIREN is read from "
                                  "the legal pages)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_exemption)

    p = sub.add_parser("ui", help="open a local web interface to run scans and browse reports")
    p.add_argument("--reports-dir", default="accesspilot-reports",
                   help="where scans are saved and read (default ./accesspilot-reports)")
    p.add_argument("--port", type=int, default=8765,
                   help="port on 127.0.0.1 (default 8765; another one is picked if it is taken)")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser")
    p.add_argument("--config", metavar="FILE", help="TOML settings (default ./accesspilot.toml)")
    p.add_argument("--chromium", metavar="PATH", help="Chromium binary (default: Playwright's)")
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser("verify", help="check the evidence log has not been altered")
    p.add_argument("--reports-dir", default="accesspilot-reports")
    p.add_argument("--log", metavar="FILE")
    p.add_argument("--chain-only", action="store_true", help="skip checking the scan files")
    p.set_defaults(func=cmd_verify)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_ERROR
    except Exception as e:  # noqa: BLE001 - CLI boundary: one clean line, not a traceback
        from .scan.crawler import ScanError
        if os.environ.get("ACCESSPILOT_DEBUG"):
            raise
        kind = "" if isinstance(e, (ScanError, ValueError, FileNotFoundError)) else f"{type(e).__name__}: "
        print(f"error: {kind}{e}", file=sys.stderr)
        return EXIT_ERROR

