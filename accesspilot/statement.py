"""Draft accessibility statement (déclaration d'accessibilité), RGAA model format.

Deterministic: filled from the scan, with [À COMPLÉTER] placeholders for what only
the site owner knows. With no conformance audit, the only honest status is
« non conforme »; the statement says so and explains why. It is a draft: the
owner completes it, has it reviewed, and publishes it.
"""
from __future__ import annotations

from collections import Counter

from .model import Scan
from .plan import build_plan
from .rgaa import AXE_TO_RGAA_THEME, NOT_TESTED_BY_AUTOMATION

TODO = "[À COMPLÉTER]"


def render_statement(scan: Scan) -> str:
    date = scan.started[:10]
    pages = scan.tested_pages
    by_theme: Counter[str] = Counter()
    for fx in build_plan(scan):
        t = AXE_TO_RGAA_THEME.get(fx.rule)
        by_theme[f"{t[0]:02d}. {t[1]}" if t else "Autres"] += fx.count

    out: list[str] = []
    a = out.append
    a("<!-- PROJET généré par AccessPilot. À compléter, relire et faire valider avant publication. -->")
    a("")
    a("# Déclaration d'accessibilité")
    a("")
    a(f"{TODO} nom de l'entreprise s'engage à rendre son site internet accessible, "
      f"conformément aux obligations d'accessibilité qui lui sont applicables {TODO} base "
      "légale, à faire valider.")
    a("")
    a(f"Cette déclaration d'accessibilité s'applique au site {scan.start_url}.")
    a("")
    a("## État de conformité")
    a("")
    a(f"Le site {scan.site} est **non conforme** avec le RGAA 4.1.2. Aucun audit de conformité "
      "n'a encore été réalisé : seul un test automatique partiel a été effectué, qui ne permet "
      "pas d'établir un niveau de conformité.")
    a("")
    a("## Contenus non accessibles")
    a("")
    a("### Non-conformités")
    a("")
    if scan.findings:
        a(f"Le test automatique du {date} a relevé des défauts dans les domaines suivants "
          "(nombre d'éléments concernés) :")
        a("")
        for theme, n in sorted(by_theme.items()):
            a(f"- {theme} : {n}")
    else:
        a(f"Le test automatique du {date} n'a relevé aucun défaut détectable automatiquement. "
          "Cela ne signifie pas que le site est accessible : voir les limites ci-dessous.")
    a("")
    a("### Dérogations pour charge disproportionnée")
    a("")
    a(f"{TODO} ou supprimer cette section.")
    a("")
    a("### Contenus non soumis à l'obligation d'accessibilité")
    a("")
    a(f"{TODO} par exemple : cartes interactives, contenus de tiers non financés ni développés "
      "par l'entreprise, ou supprimer cette section.")
    a("")
    a("## Établissement de cette déclaration")
    a("")
    a(f"Cette déclaration a été établie le {TODO}.")
    a("")
    a("### Technologies utilisées pour la réalisation du site")
    a("")
    a(f"- HTML, CSS, JavaScript {TODO}")
    a("")
    a("### Environnement de test")
    a("")
    a(f"- Test automatique : axe-core {scan.tool_versions.get('axe_core', '?')}, "
      f"navigateur Chromium {scan.tool_versions.get('chromium', '?')}, via AccessPilot "
      f"{scan.tool_versions.get('accesspilot', '?')}, le {date}")
    a("- Aucun test avec technologie d'assistance n'a encore été réalisé.")
    a("")
    a("### Pages du site ayant fait l'objet de la vérification")
    a("")
    for p in pages:
        a(f"- {p.template} : {p.url}")
    a("")
    a("### Limites du test automatique")
    a("")
    a("Les points suivants ne peuvent pas être vérifiés automatiquement et n'ont pas été testés :")
    a("")
    for item in NOT_TESTED_BY_AUTOMATION:
        a(f"- {item}")
    a("")
    a("## Amélioration et contact")
    a("")
    a("Si vous n'arrivez pas à accéder à un contenu ou à un service, vous pouvez contacter le "
      "responsable du site pour être orienté vers une alternative accessible ou obtenir le "
      "contenu sous une autre forme.")
    a("")
    a(f"- E-mail : {TODO}")
    a(f"- Adresse : {TODO}")
    a(f"- Formulaire de contact : {TODO}")
    a("")
    a(f"Nous essayons de répondre dans un délai de {TODO} jours ouvrés.")
    a("")
    a("## Voies de recours")
    a("")
    a("Si vous constatez un défaut d'accessibilité vous empêchant d'accéder à un contenu ou à "
      "une fonctionnalité du site, que vous nous le signalez et que vous ne parvenez pas à "
      "obtenir une réponse de notre part, vous êtes en droit de faire parvenir vos doléances ou "
      "une demande de saisine au Défenseur des droits.")
    a("")
    a("Plusieurs moyens sont à votre disposition :")
    a("")
    a("- Écrire un message au Défenseur des droits (formulaire en ligne : "
      "https://formulaire.defenseurdesdroits.fr/)")
    a("- Contacter le délégué du Défenseur des droits dans votre région "
      "(https://www.defenseurdesdroits.fr/saisir/delegues)")
    a("- Envoyer un courrier par la poste (gratuit, ne pas mettre de timbre) : "
      "Défenseur des droits, Libre réponse 71120, 75342 Paris CEDEX 07")
    a("")
    return "\n".join(out)
