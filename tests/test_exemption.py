import pytest

from accesspilot.exemption import (
    LIKELY_EXEMPT,
    NOT_EXEMPT,
    UNKNOWN,
    decide,
    extract_sirens,
    legal_pages,
    luhn_ok,
    normalise_siren,
    parse_page,
)


def company(**k):
    base = {"siren": "652014051", "nom_complet": "X", "etat_administratif": "A",
            "statut_diffusion": "O", "tranche_effectif_salarie": "01",
            "categorie_entreprise": "PME", "finances": {}}
    base.update(k)
    return base


def test_luhn_and_normalise():
    assert luhn_ok("652014051") and not luhn_ok("652014052")
    assert luhn_ok("356000000")  # La Poste exception
    assert normalise_siren("652 014 051") == "652014051"
    assert normalise_siren("65201405100012") == "652014051"  # SIRET
    assert normalise_siren("123") is None


def test_extract_prefers_page_order_and_drops_third_parties():
    t = ("Registre du commerce : 903 046 555 R.C.S. Nanterre. TVA FR 02903046555. "
         "Hébergeur OVH RCS Lille 424 761 419.")
    assert extract_sirens(t) == ["903046555"]
    assert extract_sirens("SIRET 652 014 051 00012") == ["652014051"]
    assert extract_sirens("téléphone 06 52 01 40 51") == []


def test_legal_pages_ranking_and_text_extraction():
    html = ('<script>var x="SIREN 111"</script><a href="/policies/privacy-policy">Confidentialité</a>'
            '<a href="/cgv">CGV</a><a href="/pages/mentions-legales">Mentions légales</a>'
            '<a href="https://other.fr/mentions-legales">x</a><p>Bonjour</p>')
    text, links = parse_page(html)
    assert "SIREN" not in text and "Bonjour" in text
    assert legal_pages("https://shop.fr/", links) == [
        "https://shop.fr/pages/mentions-legales", "https://shop.fr/cgv",
        "https://shop.fr/policies/privacy-policy"]


@pytest.mark.parametrize("kw,status", [
    ({"finances": {"2024": {"ca": 400_000}}}, LIKELY_EXEMPT),
    ({"finances": {"2024": {"ca": 3_000_000}}}, UNKNOWN),           # balance sheet may still qualify
    ({}, UNKNOWN),                                                   # turnover not published
    ({"tranche_effectif_salarie": "12"}, NOT_EXEMPT),                # 20-49 employees
    ({"categorie_entreprise": "GE"}, NOT_EXEMPT),                    # group-level category wins
    ({"tranche_effectif_salarie": "NN"}, UNKNOWN),
    ({"etat_administratif": "C"}, UNKNOWN),
    ({"statut_diffusion": "P"}, UNKNOWN),
])
def test_decide_matrix(kw, status):
    assert decide(company(**kw), "652014051").status == status


def test_decide_without_data():
    assert decide(None, None).status == UNKNOWN
    assert decide(None, "652014051").status == UNKNOWN
