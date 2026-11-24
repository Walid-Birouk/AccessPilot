"""Maison Céleste: a fictional online shop used as the demo's scan target.

It looks like a small fashion shop and carries the accessibility defects that
real shop themes commonly ship with: images without text alternatives, icon
buttons without a name, form fields identified only by a placeholder, low
contrast, invalid ARIA. Two versions exist:

- ``before``: the shop as it was first scanned.
- ``after``: the same shop once the theme's most serious defects were fixed,
  plus one new defect (a promotional banner) so the comparison shows both
  fixed and new findings, as real follow-up scans do.

Pages are rendered from Python so both versions share one source and the
differences are explicit (each ``fx(...)`` call names the defect it toggles).
"""
from __future__ import annotations

import html
from dataclasses import dataclass

VERSIONS = ("before", "after")

PRODUCTS = [
    # slug, name, price, colour, collection, description
    ("robe-lin-sable", "Robe en lin sable", "89,00", "#d8c3a5", "robes",
     "Robe midi en lin lavé, coupe droite, boutons en corozo."),
    ("robe-portefeuille-terracotta", "Robe portefeuille terracotta", "95,00", "#c46a4a", "robes",
     "Robe portefeuille en viscose fluide, ceinture à nouer."),
    ("pull-col-rond-marine", "Pull col rond marine", "69,00", "#2f3e5c", "mailles",
     "Pull en laine mérinos extra-fine, maille jersey."),
    ("cardigan-mohair-ecru", "Cardigan mohair écru", "110,00", "#efe6d6", "mailles",
     "Cardigan oversize en mohair et laine, boutons nacrés."),
    ("veste-lin-olive", "Veste en lin olive", "129,00", "#7a7f4f", "vestes",
     "Veste déstructurée en lin, deux poches plaquées."),
    ("jean-droit-brut", "Jean droit brut", "79,00", "#34405a", "denim",
     "Jean coupe droite taille haute, denim brut 12 oz."),
]
COLLECTIONS = {"robes": "Robes", "mailles": "Mailles", "vestes": "Vestes", "denim": "Denim"}


@dataclass(frozen=True)
class Shop:
    version: str = "before"
    base: str = ""          # URL prefix when the shop is served under a path (public preview)

    def fixed(self, defect: str) -> bool:
        """True when ``defect`` has been fixed in this version."""
        return self.version == "after" and defect in FIXED_IN_AFTER

    def new(self, defect: str) -> bool:
        """True when ``defect`` was introduced in this version."""
        return self.version == "after" and defect in NEW_IN_AFTER

    def u(self, path: str) -> str:
        return f"{self.base}{path}"


# What the "after" version fixed: the theme's critical and serious defects on the
# purchase path, plus the shared header. Everything else is still there.
FIXED_IN_AFTER = {
    "logo-alt", "cart-button-name", "product-image-alt", "size-select-label",
    "remove-button-name", "checkout-labels", "checkout-autocomplete", "aria-typo",
    "card-image-alt", "footer-contrast",
}
NEW_IN_AFTER = {"promo-banner-contrast"}


def esc(s: str) -> str:
    return html.escape(s, quote=True)


# ------------------------------------------------------------------ assets

def product_svg(slug: str) -> str:
    """A simple garment illustration for a product, as an SVG document."""
    p = next(p for p in PRODUCTS if p[0] == slug)
    colour = p[3]
    coll = p[4]
    shapes = {
        "robes": "M150 70 L130 95 L110 100 L95 300 L205 300 L190 100 L170 95 Z",
        "mailles": "M110 85 L70 120 L82 190 L105 180 L105 290 L195 290 L195 180 L218 190 L230 120 L190 85 L170 95 Q150 110 130 95 Z",
        "vestes": "M112 80 L70 115 L85 290 L140 290 L150 140 L160 290 L215 290 L230 115 L188 80 L150 135 Z",
        "denim": "M108 80 L192 80 L200 300 L160 300 L150 150 L140 300 L100 300 Z",
    }
    path = shapes[coll]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 360" width="600" height="720">
<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#f6f1ea"/><stop offset="1" stop-color="#ebe3d7"/></linearGradient></defs>
<rect width="300" height="360" fill="url(#bg)"/>
<ellipse cx="150" cy="318" rx="80" ry="8" fill="#000" opacity=".06"/>
<path d="{path}" fill="{colour}" stroke="#00000022" stroke-width="2" stroke-linejoin="round"/>
</svg>"""


LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 260 40" width="260" height="40">
<circle cx="18" cy="20" r="12" fill="none" stroke="#1d1d1b" stroke-width="2"/>
<circle cx="24" cy="15" r="3" fill="#c46a4a"/>
<text x="40" y="27" font-family="Georgia, serif" font-size="20" letter-spacing="3" fill="#1d1d1b">MAISON CÉLESTE</text>
</svg>"""

HERO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 520" width="1200" height="520">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#e9ddcb"/><stop offset="1" stop-color="#c9a98a"/></linearGradient></defs>
<rect width="1200" height="520" fill="url(#g)"/>
<circle cx="930" cy="200" r="150" fill="#f4ece1" opacity=".55"/>
<path d="M860 120 L820 160 L800 165 L780 470 L1000 470 L980 165 L960 160 L920 120 Z" fill="#c46a4a" opacity=".9"/>
<path d="M700 180 L660 215 L675 470 L760 470 L760 215 Z" fill="#7a7f4f" opacity=".8"/>
</svg>"""

ICON_BAG = ('<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">'
            '<path d="M6 7h12l1 13H5L6 7Zm3 0a3 3 0 0 1 6 0" fill="none" stroke="currentColor" '
            'stroke-width="1.6"/></svg>')
ICON_X = ('<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false">'
          '<path d="M6 6l12 12M18 6 6 18" stroke="currentColor" stroke-width="1.8"/></svg>')
ICON_SOCIAL = ('<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">'
               '<rect x="4" y="4" width="16" height="16" rx="5" fill="none" stroke="currentColor" '
               'stroke-width="1.6"/><circle cx="12" cy="12" r="3.5" fill="none" stroke="currentColor" '
               'stroke-width="1.6"/></svg>')

CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:"Helvetica Neue",Arial,sans-serif;color:#1d1d1b;background:#fbf8f4;line-height:1.5}
a{color:inherit}
img{max-width:100%;display:block}
.promo{background:#f2d7c9;color:#e8a88e;text-align:center;font-size:13px;padding:6px}
.top{display:flex;align-items:center;gap:24px;padding:18px 40px;border-bottom:1px solid #eadfd2;background:#fff}
.top nav{display:flex;gap:22px;font-size:14px;letter-spacing:.08em;text-transform:uppercase}
.top nav a{text-decoration:none}
.top .tools{margin-left:auto;display:flex;align-items:center;gap:12px}
.top input{border:1px solid #d9cdbd;border-radius:999px;padding:7px 14px;font:inherit;font-size:14px;background:#fbf8f4}
.iconbtn{background:none;border:0;padding:6px;cursor:pointer;color:#1d1d1b}
.hero{position:relative}
.hero > img{width:100%;height:auto}
.hero .txt{position:absolute;left:60px;top:120px;max-width:420px}
.hero h1{font-family:Georgia,serif;font-weight:400;font-size:46px;line-height:1.1;margin:0 0 14px}
.hero p{margin:0 0 22px}
.btn{display:inline-block;background:#1d1d1b;color:#fff;text-decoration:none;padding:12px 26px;border:0;font:inherit;font-size:14px;letter-spacing:.1em;text-transform:uppercase;cursor:pointer}
.btn.light{background:#d9b8a0;color:#fff}
.wrap{max-width:1180px;margin:0 auto;padding:40px}
h2{font-family:Georgia,serif;font-weight:400;font-size:28px;margin:0 0 20px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:28px}
.card a{text-decoration:none}
.card h3{font-weight:400;font-size:15px;margin:10px 0 2px}
.price{color:#a39c94;font-size:14px}
.filters{display:flex;gap:18px;margin:0 0 22px;font-size:14px}
.pdp{display:grid;grid-template-columns:1.1fr 1fr;gap:56px}
.pdp h1{font-family:Georgia,serif;font-weight:400;font-size:34px;margin:0 0 6px}
.swatches{display:flex;gap:8px;margin:14px 0}
.swatches a{width:26px;height:26px;border-radius:50%;display:block;border:1px solid #0002}
.field{margin:14px 0}
.field select,.field input{font:inherit;padding:9px 12px;border:1px solid #d9cdbd;background:#fff;min-width:120px}
table{width:100%;border-collapse:collapse}
td,th{padding:14px 8px;border-bottom:1px solid #eadfd2;text-align:left}
.co{display:grid;grid-template-columns:1.3fr 1fr;gap:48px}
.co input{display:block;width:100%;margin:0 0 12px;font:inherit;padding:11px 12px;border:1px solid #d9cdbd;background:#fff}
.summary{background:#fff;padding:24px;border:1px solid #eadfd2}
.pay{background:#e7d9cc;color:#fff}
footer{background:#1d1d1b;color:#bdb6ad;margin-top:60px}
footer .wrap{display:grid;grid-template-columns:2fr 1fr 1fr;gap:32px}
footer .fine{color:#55524e;font-size:12px}
footer input{font:inherit;padding:9px 12px;border:0;min-width:220px}
.social{display:flex;gap:10px}
"""


# ------------------------------------------------------------------ layout

def layout(shop: Shop, title: str, body: str) -> str:
    s = shop
    logo_alt = ' alt="Maison Céleste"' if s.fixed("logo-alt") else ""
    if s.fixed("cart-button-name"):
        cart = f'<a class="iconbtn" href="{s.u("/cart")}" aria-label="Panier (2 articles)">{ICON_BAG}</a>'
    else:
        cart = f'<a class="iconbtn" href="{s.u("/cart")}">{ICON_BAG}</a>'
    promo = ('<div class="promo">Livraison offerte dès 80 € · Retours gratuits sous 30 jours</div>'
             if s.new("promo-banner-contrast") else "")
    nav = " ".join(f'<a href="{s.u("/collections/" + k)}">{esc(v)}</a>' for k, v in COLLECTIONS.items())
    fine_style = ' style="color:#a8a29b"' if s.fixed("footer-contrast") else ""
    return f"""<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · Maison Céleste</title>
<link rel="stylesheet" href="{s.u('/assets/shop.css')}">
<meta name="robots" content="noindex">
</head>
<body>
{promo}
<header class="top">
  <a href="{s.u('/')}"><img src="{s.u('/assets/logo.svg')}" width="260" height="40"{logo_alt}></a>
  <nav>{nav}</nav>
  <div class="tools">
    <form action="{s.u('/search')}" method="get" role="search"><input type="search" name="q" placeholder="Rechercher"></form>
    <a class="iconbtn" href="{s.u('/account/login')}">Compte</a>
    {cart}
  </div>
</header>
<main>
{body}
</main>
<footer>
  <div class="wrap">
    <div>
      <p>Inscrivez-vous à la lettre d'information</p>
      <form action="{s.u('/contact')}" method="get"><input type="email" name="email" placeholder="Votre adresse e-mail">
      <button class="btn" type="submit">OK</button></form>
      <p class="fine"{fine_style}>© 2026 Maison Céleste SAS · Boutique de démonstration fictive</p>
    </div>
    <div><p><a href="{s.u('/contact')}">Contact</a></p><p><a href="{s.u('/cart')}">Panier</a></p></div>
    <div class="social"><a href="{s.u('/')}">{ICON_SOCIAL}</a><a href="{s.u('/')}">{ICON_SOCIAL}</a></div>
  </div>
</footer>
</body>
</html>"""


def img(shop: Shop, slug: str, alt: str, fixed_key: str, cls: str = "") -> str:
    a = f' alt="{esc(alt)}"' if shop.fixed(fixed_key) else ""
    c = f' class="{cls}"' if cls else ""
    return f'<img src="{shop.u("/assets/p/" + slug + ".svg")}" width="600" height="720"{a}{c}>'


def card(shop: Shop, p: tuple) -> str:
    slug, name, price, *_ = p
    return (f'<div class="card"><a href="{shop.u("/products/" + slug)}">'
            f'{img(shop, slug, name, "card-image-alt")}<h3>{esc(name)}</h3></a>'
            f'<span class="price">{price} €</span></div>')


# ------------------------------------------------------------------ pages

def page_home(shop: Shop) -> str:
    cards = "".join(card(shop, p) for p in PRODUCTS[:3])
    body = f"""
<section class="hero">
  <img src="{shop.u('/assets/hero.svg')}" width="1200" height="520">
  <div class="txt"><h1>La collection de printemps</h1>
  <p>Lin, mohair et denim brut, pensés pour durer.</p>
  <a class="btn light" href="{shop.u('/collections/robes')}">Découvrir</a></div>
</section>
<div class="wrap"><h2>Nouveautés</h2><div class="grid">{cards}</div></div>"""
    return layout(shop, "Accueil", body)


def page_collection(shop: Shop, key: str) -> str:
    items = [p for p in PRODUCTS if p[4] == key] or PRODUCTS[:2]
    items = items + [p for p in PRODUCTS if p not in items][: max(0, 3 - len(items))]
    cards = "".join(card(shop, p) for p in items)
    body = f"""<div class="wrap"><h1>{esc(COLLECTIONS.get(key, key))}</h1>
<div class="filters"><input type="checkbox" name="taille-s"> S <input type="checkbox" name="taille-m"> M
<input type="checkbox" name="stock"> En stock</div>
<div class="grid">{cards}</div></div>"""
    return layout(shop, COLLECTIONS.get(key, key), body)


def page_product(shop: Shop, slug: str) -> str:
    p = next((p for p in PRODUCTS if p[0] == slug), None)
    if p is None:
        return ""
    _, name, price, colour, coll, desc = p
    if shop.fixed("size-select-label"):
        size = ('<label for="taille">Taille</label><br>'
                '<select id="taille" name="taille"><option>36</option><option>38</option>'
                '<option>40</option><option>42</option></select>')
    else:
        size = ('<select name="taille"><option>Taille</option><option>36</option><option>38</option>'
                '<option>40</option><option>42</option></select>')
    aria = ('aria-describedby="livraison"' if shop.fixed("aria-typo")
            else 'aria-describeby="livraison"')
    others = [q for q in PRODUCTS if q[4] == coll and q[0] != slug] or PRODUCTS[:1]
    body = f"""<div class="wrap"><div class="pdp">
<div>{img(shop, slug, name + ", vue de face", "product-image-alt")}</div>
<div>
  <h1>{esc(name)}</h1>
  <p class="price">{price} €</p>
  <p>{esc(desc)}</p>
  <div class="swatches"><a href="#" style="background:{colour}"></a><a href="#" style="background:#1d1d1b"></a></div>
  <form action="{shop.u('/cart')}" method="get">
    <div class="field">{size}</div>
    <div class="field"><input type="number" name="quantite" value="1" min="1"></div>
    <button class="btn" type="submit" {aria}>Ajouter au panier</button>
  </form>
  <p id="livraison">Expédié sous 48 h. Retours gratuits sous 30 jours.</p>
</div></div>
<h2 style="margin-top:48px">Vous aimerez aussi</h2>
<div class="grid">{"".join(card(shop, q) for q in others[:3])}</div></div>"""
    return layout(shop, name, body)


def page_cart(shop: Shop) -> str:
    rows = []
    for p in PRODUCTS[:2]:
        slug, name, price, *_ = p
        if shop.fixed("remove-button-name"):
            rm = f'<button class="iconbtn" type="button" aria-label="Retirer {esc(name)}">{ICON_X}</button>'
        else:
            rm = f'<button class="iconbtn" type="button">{ICON_X}</button>'
        rows.append(f"""<tr><td style="width:90px">{img(shop, slug, name, "product-image-alt")}</td>
<td><a href="{shop.u('/products/' + slug)}">{esc(name)}</a></td>
<td><input type="number" name="q-{slug}" value="1" min="1" style="width:64px"></td>
<td>{price} €</td><td>{rm}</td></tr>""")
    body = f"""<div class="wrap"><h1>Votre panier</h1>
<table>{''.join(rows)}</table>
<p style="text-align:right;margin-top:24px"><strong>Total : 184,00 €</strong></p>
<p style="text-align:right"><a class="btn" href="{shop.u('/checkout')}">Passer commande</a></p></div>"""
    return layout(shop, "Panier", body)


def page_checkout(shop: Shop) -> str:
    fields = [("email", "Adresse e-mail", "email", "email"),
              ("prenom", "Prénom", "text", "given-name"),
              ("nom", "Nom", "text", "family-name"),
              ("adresse", "Adresse", "text", "street-address"),
              ("cp", "Code postal", "text", "postal-code"),
              ("ville", "Ville", "text", "address-level2"),
              ("tel", "Téléphone", "tel", "tel")]
    out = []
    for name, label, typ, ac in fields:
        auto = ac if shop.fixed("checkout-autocomplete") else {"given-name": "prenom",
                                                              "family-name": "nom-famille"}.get(ac, ac)
        if shop.fixed("checkout-labels"):
            out.append(f'<label for="{name}">{label}</label>'
                       f'<input id="{name}" name="{name}" type="{typ}" autocomplete="{auto}">')
        else:
            # The label is shown, but not tied to the field: a screen reader announces "edit text".
            out.append(f'<span>{label}</span><input name="{name}" type="{typ}" autocomplete="{auto}">')
    body = f"""<div class="wrap"><div class="co">
<form action="{shop.u('/checkout')}" method="get"><h1>Livraison</h1>
{''.join(out)}
<button class="btn pay" type="submit">Continuer vers le paiement</button></form>
<aside class="summary"><h2>Récapitulatif</h2>
<p>Robe en lin sable · 89,00 €</p><p>Robe portefeuille terracotta · 95,00 €</p>
<p><strong>Total : 184,00 €</strong></p></aside>
</div></div>"""
    return layout(shop, "Commande", body)


def page_contact(shop: Shop) -> str:
    body = f"""<div class="wrap" style="max-width:640px"><h1>Nous contacter</h1>
<form action="{shop.u('/contact')}" method="get" class="co" style="display:block">
<input name="nom" placeholder="Votre nom"><input name="email" type="email" placeholder="Votre e-mail">
<textarea name="message" rows="6" style="width:100%;font:inherit;padding:11px" placeholder="Votre message"></textarea>
<p><button class="btn" type="submit">Envoyer</button></p></form></div>"""
    return layout(shop, "Contact", body)


def page_login(shop: Shop) -> str:
    body = f"""<div class="wrap" style="max-width:480px"><h1>Connexion</h1>
<form action="{shop.u('/account/login')}" method="get" class="co" style="display:block">
<label for="login-email">E-mail</label><input id="login-email" name="email" type="email" autocomplete="email">
<label for="login-pw">Mot de passe</label><input id="login-pw" name="pw" type="password" autocomplete="current-password">
<p><button class="btn" type="submit">Se connecter</button></p></form></div>"""
    return layout(shop, "Connexion", body)


def page_search(shop: Shop) -> str:
    cards = "".join(card(shop, p) for p in PRODUCTS[3:6])
    body = f'<div class="wrap"><h1>Résultats de recherche</h1><div class="grid">{cards}</div></div>'
    return layout(shop, "Recherche", body)


ROBOTS = "User-agent: *\nDisallow: /account/\n"


def render(shop: Shop, path: str) -> tuple[int, str, bytes]:
    """(status, content type, body) for a path of the shop (without its base prefix)."""
    path = path.split("?")[0].split("#")[0]
    if path != "/":
        path = path.rstrip("/")
    html_type = "text/html; charset=utf-8"
    if path == "/robots.txt":
        return 200, "text/plain; charset=utf-8", ROBOTS.encode()
    if path == "/assets/shop.css":
        return 200, "text/css; charset=utf-8", CSS.encode()
    if path == "/assets/logo.svg":
        return 200, "image/svg+xml", LOGO_SVG.encode()
    if path == "/assets/hero.svg":
        return 200, "image/svg+xml", HERO_SVG.encode()
    if path.startswith("/assets/p/") and path.endswith(".svg"):
        slug = path[len("/assets/p/"):-4]
        if any(p[0] == slug for p in PRODUCTS):
            return 200, "image/svg+xml", product_svg(slug).encode()
    pages = {"/": page_home, "/cart": page_cart, "/checkout": page_checkout,
             "/contact": page_contact, "/account/login": page_login, "/search": page_search}
    if path in pages:
        return 200, html_type, pages[path](shop).encode()
    if path.startswith("/collections/") and path[len("/collections/"):] in COLLECTIONS:
        return 200, html_type, page_collection(shop, path[len("/collections/"):]).encode()
    if path.startswith("/products/"):
        body = page_product(shop, path[len("/products/"):])
        if body:
            return 200, html_type, body.encode()
    body = layout(shop, "Page introuvable", '<div class="wrap"><h1>Page introuvable</h1></div>')
    return 404, html_type, body.encode()
