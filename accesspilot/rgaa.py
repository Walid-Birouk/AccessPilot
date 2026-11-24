"""Accessibility knowledge used by the reports: RGAA orientation, fix guidance,
and the limits of automated testing.

Everything here is static and reviewed by hand. The axe rule -> RGAA theme
mapping is approximate orientation only and is labelled as such wherever it
appears: exact RGAA criteria are an auditor's call.
"""
from __future__ import annotations

import re

# axe-core rule id -> (RGAA theme number, theme name).
AXE_TO_RGAA_THEME: dict[str, tuple[int, str]] = {
    "image-alt": (1, "Images"), "input-image-alt": (1, "Images"), "area-alt": (1, "Images"),
    "role-img-alt": (1, "Images"), "svg-img-alt": (1, "Images"), "object-alt": (1, "Images"),
    "image-redundant-alt": (1, "Images"),
    "frame-title": (2, "Cadres"), "frame-title-unique": (2, "Cadres"),
    "color-contrast": (3, "Couleurs"), "link-in-text-block": (3, "Couleurs"),
    "video-caption": (4, "Multimédia"), "audio-caption": (4, "Multimédia"),
    "no-autoplay-audio": (4, "Multimédia"),
    "td-headers-attr": (5, "Tableaux"), "th-has-data-cells": (5, "Tableaux"),
    "table-fake-caption": (5, "Tableaux"), "td-has-header": (5, "Tableaux"),
    "link-name": (6, "Liens"), "identical-links-same-purpose": (6, "Liens"),
    "aria-allowed-attr": (7, "Scripts"), "aria-required-attr": (7, "Scripts"),
    "aria-required-children": (7, "Scripts"), "aria-required-parent": (7, "Scripts"),
    "aria-roles": (7, "Scripts"), "aria-valid-attr": (7, "Scripts"),
    "aria-valid-attr-value": (7, "Scripts"), "aria-hidden-focus": (7, "Scripts"),
    "aria-command-name": (7, "Scripts"), "aria-toggle-field-name": (7, "Scripts"),
    "aria-dialog-name": (7, "Scripts"), "nested-interactive": (7, "Scripts"),
    "aria-progressbar-name": (7, "Scripts"), "aria-tooltip-name": (7, "Scripts"),
    "html-has-lang": (8, "Éléments obligatoires"), "html-lang-valid": (8, "Éléments obligatoires"),
    "valid-lang": (8, "Éléments obligatoires"), "document-title": (8, "Éléments obligatoires"),
    "duplicate-id-aria": (8, "Éléments obligatoires"), "marquee": (13, "Consultation"),
    "blink": (13, "Consultation"), "meta-refresh": (13, "Consultation"),
    "heading-order": (9, "Structuration de l'information"),
    "empty-heading": (9, "Structuration de l'information"),
    "page-has-heading-one": (9, "Structuration de l'information"),
    "list": (9, "Structuration de l'information"), "listitem": (9, "Structuration de l'information"),
    "definition-list": (9, "Structuration de l'information"),
    "dlitem": (9, "Structuration de l'information"),
    "meta-viewport": (10, "Présentation de l'information"),
    "scrollable-region-focusable": (10, "Présentation de l'information"),
    "label": (11, "Formulaires"), "select-name": (11, "Formulaires"),
    "form-field-multiple-labels": (11, "Formulaires"), "autocomplete-valid": (11, "Formulaires"),
    "button-name": (11, "Formulaires"), "input-button-name": (11, "Formulaires"),
    "label-title-only": (11, "Formulaires"),
    "bypass": (12, "Navigation"), "landmark-one-main": (12, "Navigation"),
    "region": (12, "Navigation"), "skip-link": (12, "Navigation"), "tabindex": (12, "Navigation"),
}

# Concrete fix guidance per rule, written for whoever edits the theme.
FIX_HINTS: dict[str, tuple[str, str]] = {
    "image-alt": ("Donner une alternative textuelle aux images",
                  "Ajouter un attribut alt décrivant l'information portée par l'image (nom et "
                  "variante du produit, par exemple). Image décorative : alt=\"\". Sur Shopify, "
                  "renseigner le texte alternatif des médias produit et utiliser image.alt dans le thème."),
    "color-contrast": ("Renforcer le contraste des textes",
                       "Le texte doit atteindre un ratio de 4,5:1 avec son fond (3:1 au-delà de "
                       "24 px, ou 18,66 px en gras). Corriger la couleur dans les variables du "
                       "thème plutôt qu'élément par élément."),
    "link-name": ("Donner un intitulé aux liens",
                  "Chaque lien doit avoir un texte accessible : texte visible, alt de l'image "
                  "contenue, ou aria-label sur les liens-icônes (panier, réseaux sociaux, logo)."),
    "button-name": ("Donner un intitulé aux boutons",
                    "Les boutons-icônes (fermer, menu, quantité +/−, recherche) doivent avoir un "
                    "texte accessible : texte masqué visuellement ou aria-label."),
    "label": ("Associer une étiquette à chaque champ de formulaire",
              "Chaque champ doit avoir un <label for> lié à son id (ou aria-label s'il n'y a "
              "vraiment pas de place). Un placeholder ne remplace pas une étiquette."),
    "select-name": ("Étiqueter les listes déroulantes",
                    "Les listes (tri, taille, quantité, pays) doivent avoir une étiquette "
                    "associée, visible de préférence."),
    "html-has-lang": ("Déclarer la langue de la page",
                      "Ajouter lang=\"fr\" sur l'élément <html> dans le gabarit principal."),
    "html-lang-valid": ("Corriger la langue déclarée",
                        "L'attribut lang de <html> doit être un code valide, par exemple « fr »."),
    "document-title": ("Donner un titre à chaque page",
                       "Chaque page doit avoir un <title> pertinent et unique."),
    "frame-title": ("Donner un titre aux cadres",
                    "Chaque <iframe> (vidéo, carte, widget d'avis, chat) doit avoir un attribut "
                    "title décrivant son contenu."),
    "aria-hidden-focus": ("Retirer le focus des éléments masqués",
                          "Un élément aria-hidden=\"true\" ne doit contenir aucun élément "
                          "focalisable : ajouter tabindex=\"-1\" ou inert aux éléments du "
                          "contenu masqué (menus fermés, carrousels)."),
    "aria-allowed-attr": ("Corriger les attributs ARIA non autorisés",
                          "Retirer les attributs ARIA qui ne sont pas permis sur le rôle de "
                          "l'élément."),
    "aria-required-attr": ("Compléter les attributs ARIA obligatoires",
                           "Ajouter les attributs requis par le rôle (par exemple aria-checked "
                           "sur un rôle checkbox)."),
    "aria-valid-attr-value": ("Corriger les valeurs ARIA invalides",
                              "Les attributs ARIA doivent référencer des id existants et avoir "
                              "des valeurs permises."),
    "aria-command-name": ("Donner un intitulé aux commandes ARIA",
                          "Les éléments role=\"button\", \"link\" ou \"menuitem\" doivent avoir "
                          "un texte accessible."),
    "aria-roles": ("Corriger les rôles ARIA", "Utiliser uniquement des rôles ARIA valides."),
    "nested-interactive": ("Ne pas imbriquer des éléments interactifs",
                           "Un lien ou bouton ne doit pas contenir un autre élément interactif "
                           "(par exemple une carte produit cliquable contenant un bouton)."),
    "list": ("Corriger la structure des listes",
             "Un <ul> ou <ol> ne doit contenir directement que des <li>."),
    "listitem": ("Placer les éléments de liste dans une liste",
                 "Chaque <li> doit être enfant direct d'un <ul> ou <ol>."),
    "heading-order": ("Respecter la hiérarchie des titres",
                      "Les niveaux de titre ne doivent pas sauter de niveau (h2 puis h4)."),
    "empty-heading": ("Supprimer ou remplir les titres vides",
                      "Un élément de titre doit contenir du texte."),
    "page-has-heading-one": ("Ajouter un titre principal",
                             "Chaque page doit avoir un titre de niveau 1 (nom du produit, de "
                             "la catégorie...)."),
    "meta-viewport": ("Autoriser le zoom",
                      "Retirer user-scalable=no et maximum-scale<2 de la balise meta viewport."),
    "duplicate-id-aria": ("Rendre uniques les id référencés",
                          "Les id utilisés par aria-labelledby, aria-describedby ou label for "
                          "doivent être uniques sur la page."),
    "landmark-one-main": ("Ajouter une zone principale",
                          "Envelopper le contenu principal dans un élément <main> unique."),
    "region": ("Placer le contenu dans des régions",
               "Tout le contenu doit se trouver dans un repère (header, nav, main, footer)."),
    "bypass": ("Ajouter un lien d'évitement",
               "Ajouter en début de page un lien « Aller au contenu » vers <main>."),
    "autocomplete-valid": ("Corriger les attributs autocomplete",
                           "Utiliser les valeurs autocomplete normalisées (email, given-name, "
                           "postal-code...) sur les champs d'informations personnelles."),
    "input-button-name": ("Donner un intitulé aux boutons de formulaire",
                          "Les <input type=\"submit|button\"> doivent avoir un attribut value."),
    "scrollable-region-focusable": ("Rendre les zones défilantes accessibles au clavier",
                                    "Ajouter tabindex=\"0\" et un nom accessible aux zones à "
                                    "défilement."),
    "link-in-text-block": ("Distinguer les liens dans le texte",
                           "Les liens dans un paragraphe doivent se distinguer autrement que "
                           "par la couleur (soulignement)."),
    "role-img-alt": ("Donner une alternative aux images ARIA",
                     "Un élément role=\"img\" doit avoir un aria-label ou aria-labelledby."),
    "svg-img-alt": ("Donner une alternative aux SVG",
                    "Un <svg role=\"img\"> doit avoir un <title> ou un aria-label."),
    "tabindex": ("Ne pas utiliser de tabindex positif",
                 "Remplacer les tabindex supérieurs à 0 par 0 et suivre l'ordre du DOM."),
    "target-size": ("Agrandir les zones cliquables",
                    "Les cibles tactiles doivent mesurer au moins 24 × 24 px."),
}

# What automated testing does NOT cover. Printed in every report and statement:
# silence about untested areas would be an overclaim.
NOT_TESTED_BY_AUTOMATION: list[str] = [
    "Pertinence des alternatives textuelles (une alternative présente mais fausse passe le test)",
    "Pertinence des intitulés de liens, de boutons et de titres",
    "Sous-titres, audiodescription et transcriptions des contenus multimédia",
    "Navigation complète au clavier et ordre de tabulation, y compris dans le tunnel de commande",
    "Gestion du focus dans les composants interactifs (menus, carrousels, fenêtres modales)",
    "Messages d'erreur et aide à la saisie des formulaires après soumission",
    "Parcours nécessitant une interaction (ajout au panier, paiement, création de compte)",
    "Contenu des cadres intégrés (iframes) : widgets de paiement, d'avis, de chat, vidéos",
    "Cohérence de la navigation et de la structure entre les pages",
    "Lisibilité et compréhension du contenu",
    "Affichage avec un zoom à 200 %, en orientation portrait/paysage et avec espacement du texte modifié",
    "Restitution réelle par les lecteurs d'écran (NVDA, JAWS, VoiceOver, TalkBack)",
]

DISCLAIMER_FR = (
    "Ce rapport est produit par un outil automatisé. Les tests automatiques ne détectent "
    "qu'une partie des défauts d'accessibilité : "
    "ce rapport est une liste de défauts détectés et de corrections priorisées, pas un audit "
    "de conformité. Seul un audit réalisé par une personne qualifiée permet d'établir un "
    "taux de conformité RGAA."
)

IMPACT_FR = {"critical": "bloquant", "serious": "grave", "moderate": "modéré", "minor": "mineur"}


def rgaa_theme(rule: str) -> str:
    t = AXE_TO_RGAA_THEME.get(rule)
    return f"RGAA thème {t[0]} ({t[1]}), correspondance approximative" if t else "RGAA : à qualifier"


_SC = re.compile(r"^wcag(\d)(\d)(\d{1,2})$")


def wcag_criteria(tags: list[str]) -> list[str]:
    """axe tags -> WCAG success criteria: ['wcag111', 'wcag2a'] -> ['1.1.1']."""
    out = []
    for t in tags:
        m = _SC.match(t)
        if m:
            out.append(".".join(m.groups()))
    return out


def fix_hint(rule: str, axe_help: str) -> tuple[str, str]:
    """(title, instructions) for a rule; falls back to axe's own help text."""
    if rule in FIX_HINTS:
        return FIX_HINTS[rule]
    return axe_help, f"Voir la documentation de la règle « {rule} » (lien ci-dessous)."
