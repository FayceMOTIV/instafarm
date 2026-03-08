"""Configuration centralisee des niches TikTok."""

TIKTOK_NICHE_CONFIG = {
    "restauration": {
        "account_env_key": "TIKTOK_COOKIES_RESTAURATION",
        "cta_keywords": ["MENU", "CARTE", "TARIF", "GUIDE", "OUI", "INFO", "VEUX", "JE VEUX", "INTÉRESSE", "ENVOI", "ENVOIE"],
        "dm_link_placeholder": "[lien guide restaurant]",
        "cta_color": "#E74C3C",
        "publish_hour": 9,
        "publish_minute": 30,
    },
    "coiffure": {
        "account_env_key": "TIKTOK_COOKIES_COIFFURE",
        "cta_keywords": ["PRIX", "PROMO", "GUIDE", "INFO", "OUI", "DISPO", "TARIF", "AGENDA", "RDV"],
        "dm_link_placeholder": "[lien guide coiffure]",
        "cta_color": "#9B59B6",
        "publish_hour": 10,
        "publish_minute": 0,
    },
    "btp_artisan": {
        "account_env_key": "TIKTOK_COOKIES_BTP",
        "cta_keywords": ["DEVIS", "GUIDE", "PRIX", "INFO", "OUI", "DISPO", "CHANTIER"],
        "dm_link_placeholder": "[lien guide artisan]",
        "cta_color": "#E67E22",
        "publish_hour": 7,
        "publish_minute": 30,
    },
    "dentiste": {
        "account_env_key": "TIKTOK_COOKIES_SANTE",
        "cta_keywords": ["RDV", "INFO", "GUIDE", "CONTACT", "OUI", "INTÉRESSE", "COMMENT"],
        "dm_link_placeholder": "[lien guide cabinet]",
        "cta_color": "#27AE60",
        "publish_hour": 8,
        "publish_minute": 0,
    },
    "auto_garage": {
        "account_env_key": "TIKTOK_COOKIES_AUTO",
        "cta_keywords": ["DEVIS", "PROMO", "GUIDE", "INFO", "OUI", "FIDELITE", "FIDEL"],
        "dm_link_placeholder": "[lien guide garage]",
        "cta_color": "#2C3E50",
        "publish_hour": 8,
        "publish_minute": 30,
    },
    "sport_fitness": {
        "account_env_key": "TIKTOK_COOKIES_SPORT",
        "cta_keywords": ["PROGRAMME", "BILAN", "GUIDE", "INFO", "OUI", "COACHING", "CLIENTS"],
        "dm_link_placeholder": "[lien guide coaching]",
        "cta_color": "#1ABC9C",
        "publish_hour": 6,
        "publish_minute": 30,
    },
    "immobilier": {
        "account_env_key": "TIKTOK_COOKIES_IMMO",
        "cta_keywords": ["GUIDE", "ASTUCE", "INFO", "MANDAT", "OUI", "FORMATION"],
        "dm_link_placeholder": "[lien guide immo]",
        "cta_color": "#3498DB",
        "publish_hour": 9,
        "publish_minute": 0,
    },
    "photographe": {
        "account_env_key": "TIKTOK_COOKIES_PHOTO",
        "cta_keywords": ["TARIF", "PACK", "INFO", "GUIDE", "OUI", "DISPO", "PRIX"],
        "dm_link_placeholder": "[lien guide photo]",
        "cta_color": "#E91E63",
        "publish_hour": 10,
        "publish_minute": 30,
    },
}

HOOKS = {
    "restauration": [
        "Ce restaurant fait 50k/mois sans pub — voici son secret",
        "3 erreurs qui font partir vos clients sans commander de dessert",
        "Ce que les restaurants qui cartonnent font que toi tu ne fais pas",
        "Comment ce kebab a Marseille a triple ses commandes en 30 jours",
        "Le truc que j'aurais voulu savoir quand j'ai ouvert mon restaurant",
        "Pourquoi ton restaurant est vide le mardi (et comment y remedier)",
    ],
    "coiffure": [
        "Comment ce salon a rempli son agenda 3 semaines a l'avance",
        "L'erreur que font 90% des coiffeurs qui perdent des clients",
        "Ce salon de coiffure fait 15k/mois sans publicite Google",
        "Pourquoi tes clients ne reviennent pas apres le premier rendez-vous",
        "Cette astuce a rempli 2 semaines d'agenda en 48h",
    ],
    "btp_artisan": [
        "Ce plombier refuse des chantiers tellement il en a — voici son secret",
        "3 phrases pour closer un client qui demande 3 devis concurrents",
        "Comment ce macon decroche 20 chantiers par mois sans prospecter",
        "Pourquoi tu passes du temps sur des devis qui ne convertissent jamais",
        "L'artisan qui gagne 8k/mois en travaillant 4 jours par semaine",
    ],
    "dentiste": [
        "40 nouveaux patients par mois sans publicite Google — comment ?",
        "Pourquoi les patients ne reviennent pas apres le premier rendez-vous",
        "Ce cabinet dentaire genere 15k de plus par mois avec cette astuce",
        "L'erreur fatale que font 80% des cabinets dentaires en ligne",
    ],
    "auto_garage": [
        "Ce garagiste a 200 clients fideles et ne fait jamais de pub",
        "Pourquoi vos clients vont a Norauto au lieu de chez vous",
        "Comment ce garage a double ses entrees atelier en 2 mois",
    ],
    "sport_fitness": [
        "Comment j'ai eu 40 clients coaching en ligne en 2 mois depuis zero",
        "Pourquoi tes clients s'arretent apres 3 seances (et comment stopper ca)",
        "Ce coach fait 8k par mois en travaillant 20 heures par semaine",
    ],
    "immobilier": [
        "5 mandats en 1 semaine sans appel sortant — voici comment",
        "L'erreur que font 80% des agents immobiliers sur les reseaux",
        "Ce mandataire fait 15k par mois depuis chez lui grace a TikTok",
    ],
    "photographe": [
        "De 1500 a 6000 euros par mois en 3 mois — voici ce que j'ai change",
        "Pourquoi tes clients ne te recommandent pas a leurs amis",
        "Le wording qui triple les prises de contact — teste et valide",
    ],
}
