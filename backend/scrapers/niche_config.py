"""
Mapping secteurs → codes NAF + config scraping par niche.
Source unique de verite pour la configuration sectorielle.
"""

SECTORS: dict[str, dict] = {
    "restaurant": {
        "naf_codes": ["56.10A", "56.10B", "56.10C", "56.30Z"],
        "wolt_enabled": True,
        "keywords_default": ["restaurant", "cuisine", "chef", "plat", "gastronomie"],
        "disqualifiers": [
            "food blogger", "influenceur", "critique", "recette maison",
            "foodie", "blog", "avis", "test resto",
        ],
        "min_followers": 200,
        "max_followers": 50_000,
    },
    "boulangerie": {
        "naf_codes": ["10.71C", "10.71D"],
        "wolt_enabled": True,
        "keywords_default": ["boulangerie", "patisserie", "pain", "viennoiserie"],
        "disqualifiers": ["recette", "amateur", "fait maison"],
        "min_followers": 100,
        "max_followers": 30_000,
    },
    "cafe": {
        "naf_codes": ["56.30Z"],
        "wolt_enabled": True,
        "keywords_default": ["cafe", "coffee", "barista", "torrefacteur"],
        "disqualifiers": ["coffee lover", "amateur cafe"],
        "min_followers": 100,
        "max_followers": 30_000,
    },
    "dentiste": {
        "naf_codes": ["86.23Z"],
        "wolt_enabled": False,
        "keywords_default": ["dentiste", "cabinet dentaire", "implant", "orthodontie"],
        "disqualifiers": ["patient", "peur du dentiste", "temoignage"],
        "min_followers": 100,
        "max_followers": 20_000,
    },
    "garage": {
        "naf_codes": ["45.20A", "45.20B"],
        "wolt_enabled": False,
        "keywords_default": ["garage", "mecanique", "reparation auto", "carrosserie"],
        "disqualifiers": ["tuning perso", "passion auto", "amateur"],
        "min_followers": 50,
        "max_followers": 20_000,
    },
    "coiffeur": {
        "naf_codes": ["96.02A", "96.02B"],
        "wolt_enabled": False,
        "keywords_default": ["coiffeur", "salon", "coupe", "coloration", "barbier"],
        "disqualifiers": ["tuto coiffure", "DIY", "a domicile perso"],
        "min_followers": 100,
        "max_followers": 40_000,
    },
    "pharmacie": {
        "naf_codes": ["47.73Z"],
        "wolt_enabled": False,
        "keywords_default": ["pharmacie", "officine", "pharmacien"],
        "disqualifiers": ["parapharmacie en ligne", "dropshipping"],
        "min_followers": 50,
        "max_followers": 15_000,
    },
    "avocat": {
        "naf_codes": ["69.10Z"],
        "wolt_enabled": False,
        "keywords_default": ["avocat", "cabinet", "droit", "juridique", "barreau"],
        "disqualifiers": ["etudiant en droit", "blog juridique"],
        "min_followers": 50,
        "max_followers": 20_000,
    },
    "architecte": {
        "naf_codes": ["71.11Z"],
        "wolt_enabled": False,
        "keywords_default": ["architecte", "architecture", "design interieur", "agence"],
        "disqualifiers": ["etudiant archi", "inspiration deco"],
        "min_followers": 100,
        "max_followers": 30_000,
    },
    "veterinaire": {
        "naf_codes": ["75.00Z"],
        "wolt_enabled": False,
        "keywords_default": ["veterinaire", "clinique veterinaire", "cabinet veto"],
        "disqualifiers": ["eleveur amateur", "mon chien", "mon chat"],
        "min_followers": 50,
        "max_followers": 20_000,
    },
    "opticien": {
        "naf_codes": ["47.78A"],
        "wolt_enabled": False,
        "keywords_default": ["opticien", "lunettes", "optique", "lentilles"],
        "disqualifiers": ["lunettes fashion", "influenceur mode"],
        "min_followers": 50,
        "max_followers": 15_000,
    },
    "notaire": {
        "naf_codes": ["69.10Z"],
        "wolt_enabled": False,
        "keywords_default": ["notaire", "etude notariale", "office notarial"],
        "disqualifiers": ["immobilier particulier"],
        "min_followers": 30,
        "max_followers": 10_000,
    },
}


def get_sector_config(sector_name: str) -> dict:
    """
    Retourne la config d'un secteur.
    Si secteur inconnu, retourne une config custom generique.
    """
    normalized = sector_name.lower().strip()
    if normalized in SECTORS:
        return SECTORS[normalized]

    return {
        "naf_codes": [],
        "wolt_enabled": False,
        "keywords_default": [normalized],
        "disqualifiers": [],
        "min_followers": 100,
        "max_followers": 30_000,
    }


def get_naf_codes(sector_name: str, custom_naf: list[str] | None = None) -> list[str]:
    """
    Retourne les codes NAF pour un secteur.
    Fusionne avec des codes NAF custom si fournis.
    """
    config = get_sector_config(sector_name)
    codes = list(config.get("naf_codes", []))
    if custom_naf:
        for code in custom_naf:
            if code not in codes:
                codes.append(code)
    return codes
