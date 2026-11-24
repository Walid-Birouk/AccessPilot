from conftest import finding, make_scan

from accesspilot.config import DEFAULT_TEMPLATES
from accesspilot.plan import LAYOUT, build_plan
from accesspilot.scan.templates import classify, group_by_template, url_shape


def test_classify_shop_urls():
    t = DEFAULT_TEMPLATES
    assert classify("https://s.fr/", t) == "home"
    assert classify("https://s.fr/fr/", t) == "home"
    assert classify("https://s.fr/products/robe-rouge", t) == "product"
    assert classify("https://s.fr/collections/robes", t) == "category"
    assert classify("https://s.fr/cart", t) == "cart"
    assert classify("https://s.fr/panier?x=1", t) == "cart"
    assert classify("https://s.fr/checkouts/abc", t) == "checkout"
    assert classify("https://s.fr/blog/2024/ma-recette-123", t) == "/blog/{x}/{x}"


def test_url_shape_collapses_slugs():
    assert url_shape("https://s.fr/blog/123-titre") == url_shape("https://s.fr/blog/456-autre")


def test_group_by_template_orders_by_severity():
    fs = [finding(1, template="home", impact="minor"),
          finding(2, template="cart", impact="critical"), finding(3, template="cart", impact="critical")]
    groups = group_by_template(fs)
    assert [g.template for g in groups] == ["cart", "home"]
    assert groups[0].finding_count == 2 and groups[0].rules["image-alt"].count == 2


def test_plan_merges_same_rule_per_template_and_cites_real_ids():
    fs = [finding(i, template="product") for i in range(1, 4)]
    scan = make_scan(fs)
    plan = build_plan(scan)
    assert len(plan) == 1 and plan[0].count == 3
    assert set(plan[0].evidence_ids) <= scan.evidence_ids()
    assert plan[0].wcag == ["1.1.1"]


def test_plan_moves_shared_elements_to_layout():
    logo = dict(rule="link-name", impact="serious", selector="header > a", html="<a href='/'><img></a>")
    fs = [finding(1, template="home", **logo), finding(2, template="product", **logo),
          finding(3, template="product", rule="label", impact="critical")]
    plan = build_plan(make_scan(fs))
    assert {(fx.template, fx.rule, fx.count) for fx in plan} == {(LAYOUT, "link-name", 2),
                                                                 ("product", "label", 1)}


def test_plan_order_impact_then_purchase_path():
    fs = [finding(1, template="home", impact="critical"),
          finding(2, template="checkout", impact="critical", rule="label"),
          finding(3, template="checkout", impact="minor", rule="region")]
    plan = build_plan(make_scan(fs))
    assert [(f.template, f.impact) for f in plan] == [("checkout", "critical"), ("home", "critical"),
                                                      ("checkout", "minor")]
    assert [f.priority for f in plan] == [1, 2, 3]
