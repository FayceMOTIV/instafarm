"""
Configuration universelle des 20 niches InstaFarm.
Chaque niche a ses sources certifiees specifiques + codes NAF + config scraping + config IA.

Source unique de verite pour toute la configuration sectorielle du pipeline.
"""

NICHES: dict[str, dict] = {
    # ════════════════════════════════════════
    # 1. RESTAURANT
    # ════════════════════════════════════════
    "restaurant": {
        "label": "Restaurant",
        "naf_codes": ["56.10A", "56.10B", "56.10C", "56.30Z"],
        "sources": [
            {
                "name": "wolt",
                "type": "apify",
                "actor": "odaudlegur/wolt-scraper",
                "priority": 1,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "ubereats",
                "type": "apify",
                "actor": "borderline/ubereats-scraper",
                "priority": 2,
                "returns_instagram": False,
                "free": True,
            },
            {
                "name": "tripadvisor",
                "type": "apify",
                "actor": "maxcopell/tripadvisor",
                "priority": 3,
                "returns_instagram": False,
                "free": True,
            },
            {
                "name": "thefork",
                "type": "custom_scraper",
                "url_template": "https://www.thefork.fr/recherche?cityId={city_id}&cuisine=",
                "priority": 4,
                "returns_instagram": False,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 5,
                "returns_instagram": False,
                "free": True,
            },
        ],
        "ai_keywords": [
            "restaurant", "cuisine", "chef", "plat du jour", "menu",
            "gastronomie", "brasserie", "bistrot",
        ],
        "ai_disqualifiers": [
            "food blogger", "influenceur", "food photography",
            "critique culinaire", "touriste",
        ],
        "instagram_min_followers": 200,
        "instagram_max_followers": 50_000,
    },

    # ════════════════════════════════════════
    # 2. DENTISTE
    # ════════════════════════════════════════
    "dentiste": {
        "label": "Dentiste / Cabinet dentaire",
        "naf_codes": ["86.23Z"],
        "sources": [
            {
                "name": "doctolib",
                "type": "apify",
                "actor": "anchor/doctolib",
                "priority": 1,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
                "input": {
                    "startUrl": "https://www.doctolib.fr/chirurgien-dentiste/{city}",
                },
            },
            {
                "name": "ameli_annuaire",
                "type": "custom_scraper",
                "url_template": "https://annuaire.sante.fr/web/site-pro/recherche?commune={city}&profil=chirurgien-dentiste",
                "priority": 2,
                "returns_instagram": False,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 3,
                "free": True,
            },
        ],
        "ai_keywords": [
            "dentiste", "cabinet dentaire", "implant", "orthodontie",
            "blanchiment", "chirurgien-dentiste", "sourire",
        ],
        "ai_disqualifiers": [
            "patient", "peur du dentiste", "douleur dentaire", "temoignage",
        ],
        "instagram_min_followers": 100,
        "instagram_max_followers": 20_000,
    },

    # ════════════════════════════════════════
    # 3. COIFFEUR
    # ════════════════════════════════════════
    "coiffeur": {
        "label": "Salon de coiffure",
        "naf_codes": ["96.02A"],
        "sources": [
            {
                "name": "planity",
                "type": "custom_scraper",
                "url_template": "https://www.planity.com/coiffeur-{city}",
                "priority": 1,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
            },
            {
                "name": "treatwell",
                "type": "custom_scraper",
                "url_template": "https://www.treatwell.fr/coiffeur/{city}/",
                "priority": 2,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "pages_jaunes",
                "type": "apify",
                "actor": "drobnikj/pages-jaunes-scraper",
                "priority": 3,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 4,
                "free": True,
            },
        ],
        "ai_keywords": [
            "coiffeur", "salon", "coupe", "coloration", "balayage",
            "brushing", "keratine", "extensions",
        ],
        "ai_disqualifiers": [
            "client", "avant/apres personnel", "influenceur beaute",
        ],
        "instagram_min_followers": 200,
        "instagram_max_followers": 30_000,
    },

    # ════════════════════════════════════════
    # 4. BEAUTE / ONGLERIE / ESTHETIQUE
    # ════════════════════════════════════════
    "beaute": {
        "label": "Institut beaute / Onglerie / Esthetique",
        "naf_codes": ["96.02B"],
        "sources": [
            {
                "name": "treatwell",
                "type": "custom_scraper",
                "url_template": "https://www.treatwell.fr/manucure/{city}/",
                "priority": 1,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "planity",
                "type": "custom_scraper",
                "url_template": "https://www.planity.com/institut-beaute-{city}",
                "priority": 2,
                "free": True,
            },
            {
                "name": "fresha",
                "type": "custom_scraper",
                "url_template": "https://www.fresha.com/fr/beauty-spas/france--{city}",
                "priority": 3,
                "returns_instagram": False,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 4,
                "free": True,
            },
        ],
        "ai_keywords": [
            "onglerie", "nail art", "estheticienne", "maquillage",
            "soin visage", "epilation", "spa", "institut",
        ],
        "ai_disqualifiers": [
            "cliente", "tutoriel", "influenceuse beaute",
        ],
        "instagram_min_followers": 300,
        "instagram_max_followers": 50_000,
    },

    # ════════════════════════════════════════
    # 5. GARAGE / MECANIQUE AUTO
    # ════════════════════════════════════════
    "garage": {
        "label": "Garage / Mecanique automobile",
        "naf_codes": ["45.20A", "45.20B"],
        "sources": [
            {
                "name": "google_maps",
                "type": "outscraper",
                "query_template": "garage mecanique {city}",
                "priority": 1,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "pages_jaunes",
                "type": "apify",
                "actor": "drobnikj/pages-jaunes-scraper",
                "query": "garage+auto",
                "priority": 2,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 3,
                "free": True,
            },
        ],
        "ai_keywords": [
            "garage", "mecanique", "reparation auto", "vidange",
            "carrosserie", "diagnostic", "entretien vehicule",
        ],
        "ai_disqualifiers": [
            "passionne auto", "collection", "youngtimer", "particulier",
        ],
        "instagram_min_followers": 100,
        "instagram_max_followers": 15_000,
    },

    # ════════════════════════════════════════
    # 6. BTP / ARTISANS
    # ════════════════════════════════════════
    "btp": {
        "label": "BTP / Artisans / Construction",
        "naf_codes": [
            "43.11Z", "43.12A", "43.21A", "43.22A", "43.31Z",
            "43.32A", "43.33Z", "43.34Z", "43.39Z", "43.91A", "43.99B",
        ],
        "sources": [
            {
                "name": "houzz",
                "type": "apify",
                "actor": "jungle_synthesizer/houzz-scraper",
                "url_template": "https://www.houzz.fr/professionnels/{category}/{city}",
                "priority": 1,
                "returns_instagram": True,
                "free": True,
                "categories": [
                    "architects", "general-contractors", "interior-designers",
                    "electricians", "plumbers",
                ],
            },
            {
                "name": "qualibat",
                "type": "custom_scraper",
                "url_template": "https://www.qualibat.com/trouver-une-entreprise/?q={activity}&location={city}",
                "priority": 2,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
            },
            {
                "name": "rge_data_gouv",
                "type": "api_gouv",
                "priority": 3,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
                "note": "Telecharger CSV une fois, filtrer par departement",
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 4,
                "free": True,
            },
        ],
        "ai_keywords": [
            "entreprise BTP", "artisan", "construction", "renovation",
            "chantier", "maconnerie", "menuiserie", "plomberie", "electricite",
        ],
        "ai_disqualifiers": [
            "particulier", "DIY", "tuto maison", "bricoleur",
        ],
        "instagram_min_followers": 100,
        "instagram_max_followers": 20_000,
    },

    # ════════════════════════════════════════
    # 7. IMMOBILIER
    # ════════════════════════════════════════
    "immobilier": {
        "label": "Agence immobiliere",
        "naf_codes": ["68.31Z"],
        "sources": [
            {
                "name": "seloger_agences",
                "type": "custom_scraper",
                "url_template": "https://www.seloger.com/agences-immobilieres/{city}/",
                "priority": 1,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
            },
            {
                "name": "fnaim",
                "type": "custom_scraper",
                "url_template": "https://www.fnaim.fr/trouver-agence.htm?lieurecherche={city}",
                "priority": 2,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
            },
            {
                "name": "pages_jaunes",
                "type": "apify",
                "actor": "drobnikj/pages-jaunes-scraper",
                "query": "agence+immobiliere",
                "priority": 3,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 4,
                "free": True,
            },
        ],
        "ai_keywords": [
            "agence immobiliere", "vente appartement", "location",
            "estimation", "transaction", "bien immobilier", "chasseur immobilier",
        ],
        "ai_disqualifiers": [
            "particulier vend", "locataire", "investisseur personnel",
        ],
        "instagram_min_followers": 200,
        "instagram_max_followers": 30_000,
    },

    # ════════════════════════════════════════
    # 8. AVOCAT
    # ════════════════════════════════════════
    "avocat": {
        "label": "Cabinet d'avocat",
        "naf_codes": ["69.10Z"],
        "sources": [
            {
                "name": "conseil_national_barreaux",
                "type": "api_officielle",
                "url": "https://api.api-justice.fr/v1/avocats",
                "params": {"commune": "{city}", "specialite": "{specialty}"},
                "priority": 1,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
            },
            {
                "name": "avocat_fr",
                "type": "custom_scraper",
                "url_template": "https://www.avocat.fr/annuaire/{city}/",
                "priority": 2,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 3,
                "free": True,
            },
        ],
        "ai_keywords": [
            "cabinet avocat", "maitre", "droit", "juridique",
            "conseil juridique", "procedure", "defense",
        ],
        "ai_disqualifiers": [
            "etudiant droit", "juriste salarie", "justice personnelle",
        ],
        "instagram_min_followers": 100,
        "instagram_max_followers": 10_000,
    },

    # ════════════════════════════════════════
    # 9. SPORT / FITNESS / YOGA
    # ════════════════════════════════════════
    "sport": {
        "label": "Salle de sport / Yoga / Fitness",
        "naf_codes": ["93.12Z", "93.13Z", "93.19Z", "85.51Z"],
        "sources": [
            {
                "name": "google_maps",
                "type": "outscraper",
                "query_template": "salle de sport yoga fitness {city}",
                "priority": 1,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "decathlon_pro",
                "type": "custom_scraper",
                "url_template": "https://www.decathlon.fr/clubs/{city}",
                "priority": 2,
                "returns_instagram": False,
                "free": True,
            },
            {
                "name": "pages_jaunes",
                "type": "apify",
                "actor": "drobnikj/pages-jaunes-scraper",
                "query": "salle+sport+fitness",
                "priority": 3,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 4,
                "free": True,
            },
        ],
        "ai_keywords": [
            "salle de sport", "gym", "yoga", "pilates", "fitness",
            "musculation", "CrossFit", "coach sportif", "bien-etre",
        ],
        "ai_disqualifiers": [
            "sportif amateur", "motivation perso", "challenge", "particulier",
        ],
        "instagram_min_followers": 300,
        "instagram_max_followers": 50_000,
    },

    # ════════════════════════════════════════
    # 10. VETERINAIRE
    # ════════════════════════════════════════
    "veterinaire": {
        "label": "Cabinet veterinaire",
        "naf_codes": ["75.00Z"],
        "sources": [
            {
                "name": "ordre_veterinaires",
                "type": "custom_scraper",
                "url_template": "https://www.veterinaire.fr/services-en-ligne/trouver-un-veterinaire.html?ville={city}",
                "priority": 1,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
            },
            {
                "name": "vetup",
                "type": "custom_scraper",
                "url_template": "https://www.vetup.fr/{city}/",
                "priority": 2,
                "free": True,
            },
            {
                "name": "pages_jaunes",
                "type": "apify",
                "actor": "drobnikj/pages-jaunes-scraper",
                "query": "veterinaire+clinique+animaux",
                "priority": 3,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 4,
                "free": True,
            },
        ],
        "ai_keywords": [
            "veterinaire", "clinique veterinaire", "soins animaux",
            "urgences veterinaires", "cabinet animal", "chirurgie animale",
        ],
        "ai_disqualifiers": [
            "proprietaire animal", "amoureux des animaux", "refuge", "particulier",
        ],
        "instagram_min_followers": 100,
        "instagram_max_followers": 15_000,
    },

    # ════════════════════════════════════════
    # 11. FORMATION / ECOLE PRIVEE
    # ════════════════════════════════════════
    "formation": {
        "label": "Organisme de formation / Ecole",
        "naf_codes": ["85.41Z", "85.42Z", "85.59A", "85.59B"],
        "sources": [
            {
                "name": "qualiopi_data_gouv",
                "type": "dataset_csv",
                "priority": 1,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
                "note": "27 000 organismes certifies Qualiopi, filtrer par region",
            },
            {
                "name": "mon_compte_formation",
                "type": "api_gouv",
                "url": "https://api.moncompteformation.gouv.fr/",
                "priority": 2,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 3,
                "free": True,
            },
        ],
        "ai_keywords": [
            "centre de formation", "ecole", "cours", "certification",
            "diplome", "formation professionnelle", "apprentissage",
        ],
        "ai_disqualifiers": [
            "etudiant", "apprenant", "temoignage formation",
        ],
        "instagram_min_followers": 200,
        "instagram_max_followers": 30_000,
    },

    # ════════════════════════════════════════
    # 12. PHARMACIE
    # ════════════════════════════════════════
    "pharmacie": {
        "label": "Pharmacie",
        "naf_codes": ["47.73Z"],
        "sources": [
            {
                "name": "ordre_pharmaciens",
                "type": "custom_scraper",
                "url_template": "https://www.ordre.pharmacien.fr/les-pharmaciens/annuaire/",
                "priority": 1,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
            },
            {
                "name": "google_maps",
                "type": "outscraper",
                "query_template": "pharmacie {city}",
                "priority": 2,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 3,
                "free": True,
            },
        ],
        "ai_keywords": [
            "pharmacie", "pharmacien", "medicaments", "ordonnance",
            "para-pharmacie", "conseil sante", "preparation",
        ],
        "ai_disqualifiers": [
            "patient", "avis medicament", "automedication",
        ],
        "instagram_min_followers": 100,
        "instagram_max_followers": 10_000,
    },

    # ════════════════════════════════════════
    # 13. AUTO-ECOLE
    # ════════════════════════════════════════
    "auto_ecole": {
        "label": "Auto-ecole",
        "naf_codes": ["85.53Z"],
        "sources": [
            {
                "name": "en_voiture_simone",
                "type": "custom_scraper",
                "url_template": "https://www.envoituresimone.com/auto-ecoles/{city}",
                "priority": 1,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
            },
            {
                "name": "le_permis_libre",
                "type": "custom_scraper",
                "url_template": "https://www.lepermislibre.fr/auto-ecoles/{city}",
                "priority": 2,
                "free": True,
            },
            {
                "name": "pages_jaunes",
                "type": "apify",
                "actor": "drobnikj/pages-jaunes-scraper",
                "query": "auto-ecole+permis",
                "priority": 3,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 4,
                "free": True,
            },
        ],
        "ai_keywords": [
            "auto-ecole", "permis de conduire", "code de la route",
            "moniteur", "lecon de conduite", "passage permis",
        ],
        "ai_disqualifiers": [
            "eleve conducteur", "temoignage permis", "vlog permis",
        ],
        "instagram_min_followers": 100,
        "instagram_max_followers": 10_000,
    },

    # ════════════════════════════════════════
    # 14. HOTEL / HEBERGEMENT
    # ════════════════════════════════════════
    "hotel": {
        "label": "Hotel / Hebergement",
        "naf_codes": ["55.10Z", "55.20Z"],
        "sources": [
            {
                "name": "booking",
                "type": "apify",
                "actor": "voyager/booking-scraper",
                "priority": 1,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
            },
            {
                "name": "atout_france",
                "type": "api_officielle",
                "url": "https://data.datatourisme.fr/",
                "priority": 2,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
            },
            {
                "name": "tripadvisor",
                "type": "apify",
                "actor": "maxcopell/tripadvisor",
                "priority": 3,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 4,
                "free": True,
            },
        ],
        "ai_keywords": [
            "hotel", "hebergement", "chambre d'hotes", "residence",
            "petit-dejeuner inclus", "boutique hotel", "sejour",
        ],
        "ai_disqualifiers": [
            "voyageur", "avis client", "influenceur voyage",
        ],
        "instagram_min_followers": 300,
        "instagram_max_followers": 50_000,
    },

    # ════════════════════════════════════════
    # 15. DECORATION / DESIGN INTERIEUR
    # ════════════════════════════════════════
    "decoration": {
        "label": "Decorateur / Designer d'interieur",
        "naf_codes": ["74.10Z"],
        "sources": [
            {
                "name": "houzz",
                "type": "apify",
                "actor": "jungle_synthesizer/houzz-scraper",
                "url_template": "https://www.houzz.fr/professionnels/decorateur-interieur/{city}",
                "priority": 1,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "maisons_et_decors",
                "type": "custom_scraper",
                "url_template": "https://www.maisons-et-decors.fr/annuaire-decorateurs/{city}/",
                "priority": 2,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 3,
                "free": True,
            },
        ],
        "ai_keywords": [
            "decorateur", "designer interieur", "architecture interieure",
            "agencement", "renovation interieure", "home staging", "moodboard",
        ],
        "ai_disqualifiers": [
            "particulier deco", "inspiration deco", "before/after DIY",
        ],
        "instagram_min_followers": 500,
        "instagram_max_followers": 100_000,
    },

    # ════════════════════════════════════════
    # 16. TRAITEUR / EVENEMENTIEL
    # ════════════════════════════════════════
    "traiteur": {
        "label": "Traiteur / Evenementiel",
        "naf_codes": ["56.21Z", "82.30Z"],
        "sources": [
            {
                "name": "mariages_net",
                "type": "custom_scraper",
                "url_template": "https://www.mariages.net/traiteur-mariage/{city}/",
                "priority": 1,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "zankyou",
                "type": "custom_scraper",
                "url_template": "https://www.zankyou.fr/f/traiteurs-{city}",
                "priority": 2,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "wolt",
                "type": "apify",
                "actor": "odaudlegur/wolt-scraper",
                "priority": 3,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 4,
                "free": True,
            },
        ],
        "ai_keywords": [
            "traiteur", "buffet", "evenementiel", "cocktail",
            "mariage", "reception", "banquet", "chef a domicile",
        ],
        "ai_disqualifiers": [
            "mariee", "invite mariage", "temoignage",
        ],
        "instagram_min_followers": 300,
        "instagram_max_followers": 30_000,
    },

    # ════════════════════════════════════════
    # 17. BIEN-ETRE / SPA / MASSAGE
    # ════════════════════════════════════════
    "bienetre": {
        "label": "Spa / Massage / Bien-etre",
        "naf_codes": ["96.04Z"],
        "sources": [
            {
                "name": "treatwell",
                "type": "custom_scraper",
                "url_template": "https://www.treatwell.fr/spa-massage/{city}/",
                "priority": 1,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "fresha",
                "type": "custom_scraper",
                "url_template": "https://www.fresha.com/fr/beauty-spas/france--{city}?q=spa",
                "priority": 2,
                "free": True,
            },
            {
                "name": "pages_jaunes",
                "type": "apify",
                "actor": "drobnikj/pages-jaunes-scraper",
                "query": "spa+massage+institut",
                "priority": 3,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 4,
                "free": True,
            },
        ],
        "ai_keywords": [
            "spa", "massage", "bien-etre", "relaxation", "hammam",
            "sauna", "soins corps", "kinesitherapie",
        ],
        "ai_disqualifiers": [
            "client spa", "influence wellness", "avis particulier",
        ],
        "instagram_min_followers": 200,
        "instagram_max_followers": 30_000,
    },

    # ════════════════════════════════════════
    # 18. PHOTOGRAPHE / VIDEASTE
    # ════════════════════════════════════════
    "photographe": {
        "label": "Photographe / Videaste professionnel",
        "naf_codes": ["74.20Z"],
        "sources": [
            {
                "name": "mariages_net",
                "type": "custom_scraper",
                "url_template": "https://www.mariages.net/photographe-mariage/{city}/",
                "priority": 1,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "malt",
                "type": "custom_scraper",
                "url_template": "https://www.malt.fr/s?q=photographe&l={city}",
                "priority": 2,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
            },
            {
                "name": "pages_jaunes",
                "type": "apify",
                "actor": "drobnikj/pages-jaunes-scraper",
                "query": "photographe+professionnel",
                "priority": 3,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 4,
                "free": True,
            },
        ],
        "ai_keywords": [
            "photographe", "photographie", "studio photo", "reportage",
            "portrait", "mariage photo", "videaste", "production video",
        ],
        "ai_disqualifiers": [
            "photo amateur", "smartphone photo", "influenceur", "passionne photo",
        ],
        "instagram_min_followers": 500,
        "instagram_max_followers": 100_000,
    },

    # ════════════════════════════════════════
    # 19. PLOMBIER / ELECTRICIEN
    # ════════════════════════════════════════
    "depannage": {
        "label": "Plombier / Electricien / Depannage",
        "naf_codes": ["43.21A", "43.22A", "43.22B"],
        "sources": [
            {
                "name": "rge_data_gouv",
                "type": "dataset_csv",
                "url": "https://data.ademe.fr/datasets/liste-des-entreprises-rge-2",
                "priority": 1,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
                "note": "Telecharger CSV complet, filtrer par activite + departement",
            },
            {
                "name": "houzz",
                "type": "apify",
                "actor": "jungle_synthesizer/houzz-scraper",
                "url_template": "https://www.houzz.fr/professionnels/plombiers/{city}",
                "priority": 2,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "habitissimo",
                "type": "custom_scraper",
                "url_template": "https://www.habitissimo.fr/pros/plombier/{city}",
                "priority": 3,
                "returns_instagram": False,
                "returns_website": True,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 4,
                "free": True,
            },
        ],
        "ai_keywords": [
            "plombier", "electricien", "depannage", "installation sanitaire",
            "chauffagiste", "climatisation", "RGE", "artisan certifie",
        ],
        "ai_disqualifiers": [
            "bricoleur", "DIY plomberie", "particulier",
        ],
        "instagram_min_followers": 100,
        "instagram_max_followers": 10_000,
    },

    # ════════════════════════════════════════
    # 20. BOULANGERIE / PATISSERIE
    # ════════════════════════════════════════
    "boulangerie": {
        "label": "Boulangerie / Patisserie",
        "naf_codes": ["10.71C", "10.71D"],
        "sources": [
            {
                "name": "wolt",
                "type": "apify",
                "actor": "odaudlegur/wolt-scraper",
                "priority": 1,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "tripadvisor",
                "type": "apify",
                "actor": "maxcopell/tripadvisor",
                "priority": 2,
                "free": True,
            },
            {
                "name": "google_maps",
                "type": "outscraper",
                "query_template": "boulangerie patisserie {city}",
                "priority": 3,
                "returns_instagram": True,
                "free": True,
            },
            {
                "name": "sirene",
                "type": "api_gouv",
                "priority": 4,
                "free": True,
            },
        ],
        "ai_keywords": [
            "boulangerie", "patisserie", "pain artisanal", "viennoiserie",
            "croissant", "cake design", "fournil", "boulanger",
        ],
        "ai_disqualifiers": [
            "amateur patisserie", "gateau maison", "food blogger boulangerie",
        ],
        "instagram_min_followers": 200,
        "instagram_max_followers": 50_000,
    },
}


# ════════════════════════════════════════════════════
# SOURCES UNIVERSELLES (toutes niches)
# ════════════════════════════════════════════════════
UNIVERSAL_SOURCES: dict[str, dict] = {
    "google_maps_outscraper": {
        "description": "Outscraper Google Maps — retourne Instagram direct",
        "free_quota": 25,
        "returns_instagram": True,
        "applies_to": "ALL",
    },
    "pages_jaunes_apify": {
        "description": "Pages Jaunes France — 4M+ pros",
        "actor": "drobnikj/pages-jaunes-scraper",
        "free": True,
        "applies_to": "ALL",
    },
    "sirene_api": {
        "description": "API Annuaire Entreprises — sans cle, illimitee",
        "url": "https://recherche-entreprises.api.gouv.fr/search",
        "free": True,
        "applies_to": "ALL",
    },
    "osm_overpass": {
        "description": "OpenStreetMap — requetes par type d'etablissement",
        "url": "https://overpass-api.de/api/interpreter",
        "free": True,
        "applies_to": "ALL",
    },
}


# ════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ════════════════════════════════════════════════════


def get_niche_sources(niche_key: str) -> list[dict]:
    """Retourne les sources triees par priorite pour une niche."""
    niche = NICHES.get(niche_key)
    if not niche:
        raise ValueError(
            f"Niche '{niche_key}' non trouvee. "
            f"Niches disponibles: {list(NICHES.keys())}"
        )
    return sorted(niche["sources"], key=lambda x: x["priority"])


def get_naf_codes(niche_key: str, custom_naf: list[str] | None = None) -> list[str]:
    """Retourne les codes NAF pour filtrage SIRENE. Fusionne avec custom_naf."""
    niche = NICHES.get(niche_key)
    if not niche:
        return list(custom_naf) if custom_naf else []

    codes = list(niche["naf_codes"])
    if custom_naf:
        for code in custom_naf:
            if code not in codes:
                codes.append(code)
    return codes


def get_ai_config(niche_key: str) -> dict:
    """Retourne la config pour la verification IA."""
    niche = NICHES.get(niche_key)
    if not niche:
        return {
            "keywords": [niche_key],
            "disqualifiers": [],
            "min_followers": 100,
            "max_followers": 30_000,
        }
    return {
        "keywords": niche["ai_keywords"],
        "disqualifiers": niche["ai_disqualifiers"],
        "min_followers": niche["instagram_min_followers"],
        "max_followers": niche["instagram_max_followers"],
    }


def get_sector_config(sector_name: str) -> dict:
    """
    Retrocompatibilite avec niche_config.py.
    Retourne une config au format attendu par pipeline.py et sirene_scraper.py.
    """
    normalized = sector_name.lower().strip()
    niche = NICHES.get(normalized)
    if not niche:
        return {
            "naf_codes": [],
            "wolt_enabled": False,
            "keywords_default": [normalized],
            "disqualifiers": [],
            "min_followers": 100,
            "max_followers": 30_000,
        }

    # Determiner si wolt est dans les sources
    wolt_enabled = any(s["name"] == "wolt" for s in niche["sources"])

    return {
        "naf_codes": niche["naf_codes"],
        "wolt_enabled": wolt_enabled,
        "keywords_default": niche["ai_keywords"],
        "disqualifiers": niche["ai_disqualifiers"],
        "min_followers": niche["instagram_min_followers"],
        "max_followers": niche["instagram_max_followers"],
    }


def list_all_niches() -> dict[str, str]:
    """Liste toutes les niches disponibles {key: label}."""
    return {key: niche["label"] for key, niche in NICHES.items()}


def get_gold_source(niche_key: str) -> dict | None:
    """Retourne la source priorite 1 (gold) d'une niche."""
    sources = get_niche_sources(niche_key)
    return sources[0] if sources else None
