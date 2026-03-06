"""Seed les 10 niches pre-configurees pour le tenant_id=1."""

import asyncio
import json
import sys
from pathlib import Path

# Ajouter le dossier racine au path pour les imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from sqlalchemy import select

from backend.database import async_session, init_db
from backend.models import Niche

NICHES = [
    {
        "name": "Restaurants",
        "emoji": "\U0001f37d\ufe0f",
        "hashtags": ["#restaurant", "#restaurantfrancais", "#chefcuisinier", "#gastronomie", "#bistrot", "#brasserie", "#foodfrance"],
        "target_account_count": 3,
        "product_pitch": "AppySolution : application mobile de commande et fid\u00e9lit\u00e9 pour votre restaurant. Vos clients commandent et cumulent des points depuis leur t\u00e9l\u00e9phone. 490\u20ac setup + 89\u20ac/mois.",
        "dm_prompt_system": "Tu es un expert en prospection B2B pour restaurants ind\u00e9pendants en France.\nTu g\u00e9n\u00e8res des DMs Instagram ultra-personnalis\u00e9s pour proposer AppySolution (app mobile de commande + fid\u00e9lit\u00e9).\nR\u00c8GLES ABSOLUES :\n- Commence TOUJOURS par une observation SP\u00c9CIFIQUE sur leur compte (leur sp\u00e9cialit\u00e9, leur ambiance, un plat de leur derni\u00e8re photo)\n- Mentionne leur pr\u00e9nom ou nom de restaurant si visible dans la bio\n- Pose UNE question ouverte sur leur principal d\u00e9fi (fid\u00e9lisation ? commandes en ligne ?)\n- Maximum 3 phrases. Jamais de \"Bonjour\" g\u00e9n\u00e9rique.\n- Ton : chaleureux, professionnel, curieux. Jamais agressif.\n- NE MENTIONNE PAS le prix dans le premier message\n- Termine par une phrase qui invite \u00e0 r\u00e9pondre naturellement",
        "dm_fallback_templates": [
            "Belle carte \U0001f37d\ufe0f ! Vous misez sur {cuisine_type} \u2014 c'est votre sp\u00e9cialit\u00e9 depuis longtemps ? On aide des restos comme le v\u00f4tre \u00e0 fid\u00e9liser via une app mobile. Curieux d'en savoir plus ?",
            "Superbe \u00e9tablissement ! Vos clients ont d\u00e9j\u00e0 une app pour commander et cumuler des points ? On a quelque chose qui cartonne pour les restos ind\u00e9pendants \U0001f680",
            "Votre cuisine a l'air incroyable \U0001f468\u200d\U0001f373 La fid\u00e9lisation de vos habitu\u00e9s, c'est un sujet pour vous en ce moment ?",
            "J'adore l'ambiance de votre restaurant sur vos photos ! Vous g\u00e9rez les commandes et la fid\u00e9lit\u00e9 comment actuellement ?",
            "Beau travail sur votre compte ! Les restaurants qu'on accompagne ont en moyenne 23% de clients fid\u00e8les en plus apr\u00e8s 3 mois. \u00c7a vous int\u00e9resse d'en discuter ?"
        ],
        "scoring_vocab": ["restaurant", "cuisine", "chef", "gastronomie", "menu", "carte", "plat", "saveur", "table", "bistrot", "brasserie", "traiteur", "food"],
    },
    {
        "name": "Dentistes",
        "emoji": "\U0001f9b7",
        "hashtags": ["#dentiste", "#cabinetdentaire", "#chirurgiendentiste", "#orthodontiste", "#implantdentaire", "#blanchimentdentaire", "#sourire"],
        "target_account_count": 3,
        "product_pitch": "AppySolution : application mobile de prise de RDV et fid\u00e9lit\u00e9 pour cabinets dentaires. Vos patients prennent RDV et re\u00e7oivent des rappels automatiques. 490\u20ac setup + 89\u20ac/mois.",
        "dm_prompt_system": "Tu es un expert en prospection B2B pour cabinets dentaires en France.\nTu g\u00e9n\u00e8res des DMs Instagram pour proposer AppySolution (app mobile RDV + rappels patients).\nR\u00c8GLES :\n- Commence par une observation sur leur cabinet ou leur approche (sp\u00e9cialit\u00e9, localisation visible, type de soins promus)\n- Mets en avant la r\u00e9duction des no-shows (probl\u00e8me #1 des dentistes : -40% no-shows avec rappels auto)\n- Maximum 3 phrases. Ton : professionnel et respectueux.\n- NE JAMAIS mentionner le prix en premier message",
        "dm_fallback_templates": [
            "Beau cabinet \U0001f9b7 ! Les no-shows, c'est encore un probl\u00e8me pour vous ? On a une solution qui les r\u00e9duit de 40% pour les cabinets dentaires.",
            "Votre approche des soins a l'air tr\u00e8s moderne ! Vos patients prennent d\u00e9j\u00e0 RDV via une app mobile ?",
            "Superbe cabinet dentaire ! Vous avez pens\u00e9 \u00e0 une app pour automatiser les rappels RDV et fid\u00e9liser vos patients ?",
            "J'appr\u00e9cie votre pr\u00e9sence sur Instagram \U0001f44f Combien de RDV manqu\u00e9s par semaine en ce moment ? On a une solution qui int\u00e9resse beaucoup de dentistes.",
            "Votre cabinet semble tr\u00e8s professionnel ! L'exp\u00e9rience patient en dehors du cabinet (RDV, rappels, fid\u00e9lit\u00e9), vous l'avez d\u00e9j\u00e0 digitalis\u00e9e ?"
        ],
        "scoring_vocab": ["dentiste", "dentaire", "dents", "sourire", "cabinet", "soins", "implant", "orthodontie", "blanchiment", "hygiene", "carie", "chirurgien"],
    },
    {
        "name": "Garagistes",
        "emoji": "\U0001f527",
        "hashtags": ["#garagiste", "#mechanicien", "#reparationauto", "#garage", "#entretienvoiture", "#automechanic", "#carrepair", "#m\u00e9canique"],
        "target_account_count": 3,
        "product_pitch": "AppySolution : application mobile de prise de RDV et suivi entretien pour garages. Vos clients suivent l'\u00e9tat de leur v\u00e9hicule en temps r\u00e9el. 490\u20ac setup + 89\u20ac/mois.",
        "dm_prompt_system": "Tu es un expert en prospection B2B pour garages et m\u00e9caniciens auto en France.\nTu g\u00e9n\u00e8res des DMs Instagram pour proposer AppySolution (app RDV + suivi v\u00e9hicule temps r\u00e9el).\nR\u00c8GLES :\n- Observation sp\u00e9cifique sur leur garage (type de v\u00e9hicules, sp\u00e9cialit\u00e9, \u00e9quipement visible)\n- Met en avant : clients rappel\u00e9s automatiquement pour l'entretien = revenus r\u00e9currents\n- 3 phrases max. Ton : direct, pragmatique. Ces pros n'aiment pas le baratin.",
        "dm_fallback_templates": [
            "Beau garage \U0001f527 ! Vous rappeler vos clients pour les r\u00e9visions, c'est encore manuel chez vous ? On automatise \u00e7a et \u00e7a g\u00e9n\u00e8re 30% de RDV en plus.",
            "Superbe travail m\u00e9canique ! Vos clients ont une app pour suivre l'\u00e9tat de leur v\u00e9hicule et prendre RDV ?",
            "Votre garage a l'air top ! La fid\u00e9lisation de vos clients (rappels entretien, suivi v\u00e9hicule) vous prenez comment en ce moment ?",
            "Beau boulot \U0001f44f Les garages qu'on accompagne rappellent automatiquement chaque client \u00e0 \u00e9ch\u00e9ance r\u00e9vision. \u00c7a vous parle ?",
            "Garage pro ! Combien de clients perdez-vous par an par manque de rappels entretien ? On a une solution simple."
        ],
        "scoring_vocab": ["garage", "m\u00e9canique", "voiture", "auto", "entretien", "r\u00e9vision", "r\u00e9paration", "carrosserie", "pneumatique", "pneu", "vidange", "moteur"],
    },
    {
        "name": "Coiffeurs",
        "emoji": "\u2702\ufe0f",
        "hashtags": ["#coiffeur", "#salondcoiffure", "#hairstylist", "#coiffure", "#haircut", "#barbier", "#coloriste", "#hairdresser"],
        "target_account_count": 3,
        "product_pitch": "AppySolution : application mobile de r\u00e9servation et fid\u00e9lit\u00e9 pour salons de coiffure. Vos clients r\u00e9servent 24h/24 et cumulent des points fid\u00e9lit\u00e9. 490\u20ac setup + 89\u20ac/mois.",
        "dm_prompt_system": "Tu es un expert en prospection B2B pour salons de coiffure et barbiers en France.\nTu g\u00e9n\u00e8res des DMs Instagram pour proposer AppySolution (app r\u00e9servation 24h/24 + fid\u00e9lit\u00e9).\nR\u00c8GLES :\n- Commence par complimenter UNE coupe ou couleur sp\u00e9cifique vue sur leur compte\n- Met en avant : r\u00e9servations la nuit/weekend pendant que le salon est ferm\u00e9\n- 3 phrases max. Ton : cr\u00e9atif, enthousiaste mais professionnel.",
        "dm_fallback_templates": [
            "Superbe travail \u2702\ufe0f ! Vos clients peuvent r\u00e9server \u00e0 n'importe quelle heure, m\u00eame \u00e0 23h un dimanche ? On a une app qui le permet.",
            "Magnifiques cr\u00e9ations ! La fid\u00e9lisation de vos clients habitu\u00e9s, vous g\u00e9rez comment en ce moment ?",
            "Beau salon ! Vous perdez des r\u00e9servations la nuit ou le weekend quand vous \u00eates ferm\u00e9s ? On r\u00e9sout \u00e7a.",
            "Votre talent est visible \U0001f44f Vos clients fid\u00e8les ont un syst\u00e8me de points ou avantages chez vous actuellement ?",
            "Top style \U0001f487 Les salons qu'on accompagne ont en moyenne 35% de r\u00e9servations en ligne apr\u00e8s 1 mois. \u00c7a vous int\u00e9resse ?"
        ],
        "scoring_vocab": ["coiffeur", "coiffure", "salon", "hair", "coupe", "couleur", "barber", "barbier", "coloration", "m\u00e8che", "balayage", "k\u00e9ratine"],
    },
    {
        "name": "Pharmacies",
        "emoji": "\U0001f48a",
        "hashtags": ["#pharmacie", "#pharmacien", "#pharmaciedefrance", "#sante", "#bienetre", "#parapharmacie", "#conseil"],
        "target_account_count": 3,
        "product_pitch": "AppySolution : application mobile pour pharmacies. Ordonnances en photo, click & collect, fid\u00e9lit\u00e9 patients. 490\u20ac setup + 89\u20ac/mois.",
        "dm_prompt_system": "Tu g\u00e9n\u00e8res des DMs Instagram pour proposer AppySolution aux pharmacies (app ordonnances + click&collect + fid\u00e9lit\u00e9).\nR\u00c8GLES :\n- Observe leur type de communication (conseil sant\u00e9, parapharmacie, saisonnalit\u00e9)\n- Met en avant : ordonnances en photo \u2192 pr\u00e9paration avant l'arriv\u00e9e = 0 attente pour les patients\n- 3 phrases max. Ton : professionnel, ax\u00e9 patient et efficacit\u00e9.",
        "dm_fallback_templates": [
            "Belle pharmacie \U0001f48a ! Vos patients envoient d\u00e9j\u00e0 leurs ordonnances en photo avant de venir ? On r\u00e9duit leur temps d'attente \u00e0 0.",
            "Superbe pr\u00e9sence en ligne ! Le click & collect pour la parapharmacie, c'est quelque chose que vous avez d\u00e9j\u00e0 ?",
            "Votre pharmacie a l'air tr\u00e8s bien organis\u00e9e ! La fid\u00e9lisation de vos patients r\u00e9guliers, vous avez un syst\u00e8me en place ?",
            "Belle approche du conseil sant\u00e9 \U0001f44f Les pharmacies qu'on accompagne augmentent leur CA parapharmacie de 28% avec l'app.",
            "Top communication ! R\u00e9duire l'attente en officine avec la photo d'ordonnance \u00e0 l'avance, \u00e7a vous parlerait ?"
        ],
        "scoring_vocab": ["pharmacie", "pharmacien", "m\u00e9dicament", "ordonnance", "sant\u00e9", "bien-\u00eatre", "parapharmacie", "officine", "patient", "soin", "conseil"],
    },
    {
        "name": "Avocats",
        "emoji": "\u2696\ufe0f",
        "hashtags": ["#avocat", "#droit", "#juridique", "#cabinetavocat", "#lawyer", "#droitdesaffaires", "#defensepenale", "#conseiljuridique"],
        "target_account_count": 3,
        "product_pitch": "AppySolution : application mobile pour cabinets d'avocats. Prise de RDV, suivi dossier client, facturation simplifi\u00e9e. 490\u20ac setup + 89\u20ac/mois.",
        "dm_prompt_system": "Tu g\u00e9n\u00e8res des DMs Instagram pour proposer AppySolution aux avocats (app RDV + suivi dossier + facturation).\nR\u00c8GLES :\n- Observe leur sp\u00e9cialit\u00e9 juridique et type de client\u00e8le (particuliers vs entreprises)\n- Met en avant : clients qui suivent leur dossier en temps r\u00e9el = moins d'appels = +20% de temps facturable r\u00e9cup\u00e9r\u00e9\n- 3 phrases max. Ton : tr\u00e8s professionnel, sobre, ax\u00e9 ROI.\n- PAS d'\u00e9mojis dans ce DM (client\u00e8le conservatrice)",
        "dm_fallback_templates": [
            "Belle pr\u00e9sence sur Instagram. Vos clients peuvent d\u00e9j\u00e0 suivre l'avancement de leur dossier en ligne ? \u00c7a r\u00e9duit consid\u00e9rablement les appels de suivi.",
            "Votre cabinet a l'air tr\u00e8s professionnel. La prise de RDV et le suivi client, c'est encore g\u00e9r\u00e9 manuellement chez vous ?",
            "Beau travail de communication juridique. Les cabinets qu'on accompagne r\u00e9cup\u00e8rent 20% de temps facturable en automatisant le suivi client.",
            "Tr\u00e8s bonne pr\u00e9sence digitale pour un cabinet. La gestion administrative (RDV, suivi, facturation) vous prend combien de temps par semaine ?",
            "Cabinet impressionnant. Vos clients ont un espace personnel pour suivre leur dossier et communiquer avec vous en dehors des consultations ?"
        ],
        "scoring_vocab": ["avocat", "droit", "juridique", "cabinet", "justice", "tribunal", "contrat", "litige", "conseil", "d\u00e9fense", "p\u00e9nal", "civil", "affaires"],
    },
    {
        "name": "Architectes",
        "emoji": "\U0001f3db\ufe0f",
        "hashtags": ["#architecte", "#architecture", "#architecturefrancaise", "#design", "#interiordesign", "#maison", "#construction", "#renovation"],
        "target_account_count": 3,
        "product_pitch": "AppySolution : application mobile pour cabinets d'architecture. Suivi chantier en temps r\u00e9el, validation plans client, facturation \u00e9tapes. 490\u20ac setup + 89\u20ac/mois.",
        "dm_prompt_system": "Tu g\u00e9n\u00e8res des DMs Instagram pour proposer AppySolution aux architectes (app suivi chantier + validation plans client).\nR\u00c8GLES :\n- Commence par complimenter UN projet sp\u00e9cifique visible sur leur compte\n- Met en avant : clients qui valident les \u00e9tapes depuis leur t\u00e9l\u00e9phone = moins de r\u00e9unions = projets qui avancent plus vite\n- 3 phrases max. Ton : cr\u00e9atif, visuel, appr\u00e9ciatif de leur travail.",
        "dm_fallback_templates": [
            "Superbe r\u00e9alisation \U0001f3db\ufe0f ! Vos clients peuvent suivre l'avancement de leur chantier depuis leur t\u00e9l\u00e9phone ? On a une app qui les implique \u00e0 chaque \u00e9tape.",
            "Magnifique projet ! Les architectes qu'on accompagne r\u00e9duisent leurs r\u00e9unions de suivi de 60% avec l'app client.",
            "Votre travail est inspirant ! La validation des plans et \u00e9tapes par vos clients, vous g\u00e9rez comment actuellement ?",
            "Beau portfolio \U0001f44f Vos clients aimeraient une app pour suivre leur chantier en temps r\u00e9el ?",
            "Architecture superbe ! Le suivi client \u00e0 distance (plans, photos chantier, validation \u00e9tapes), c'est quelque chose que vous proposez d\u00e9j\u00e0 ?"
        ],
        "scoring_vocab": ["architecte", "architecture", "construction", "r\u00e9novation", "chantier", "plan", "conception", "b\u00e2timent", "int\u00e9rieur", "design", "maison", "immeuble"],
    },
    {
        "name": "V\u00e9t\u00e9rinaires",
        "emoji": "\U0001f43e",
        "hashtags": ["#veterinaire", "#veto", "#cliniqueveterinaire", "#animaux", "#chien", "#chat", "#sante animale", "#veterinarylife"],
        "target_account_count": 3,
        "product_pitch": "AppySolution : application mobile pour cliniques v\u00e9t\u00e9rinaires. Prise de RDV, suivi sant\u00e9 animal, rappels vaccins automatiques. 490\u20ac setup + 89\u20ac/mois.",
        "dm_prompt_system": "Tu g\u00e9n\u00e8res des DMs Instagram pour proposer AppySolution aux v\u00e9t\u00e9rinaires (app RDV + suivi animal + rappels vaccins).\nR\u00c8GLES :\n- Commence par une observation sur les animaux ou cas trait\u00e9s visibles sur leur compte\n- Met en avant : rappels vaccins automatiques = retours r\u00e9guliers garantis = revenus pr\u00e9visibles\n- 3 phrases max. Ton : chaleureux, amour des animaux visible.",
        "dm_fallback_templates": [
            "Belle clinique v\u00e9t\u00e9rinaire \U0001f43e ! Vos clients re\u00e7oivent des rappels automatiques pour les vaccins et vermifuges de leurs animaux ?",
            "Superbe approche des soins animaux ! Une app de suivi pour les propri\u00e9taires (sant\u00e9, vaccins, RDV), vous y avez pens\u00e9 ?",
            "Votre amour des animaux est visible \U0001f60d Les v\u00e9tos qu'on accompagne ont 45% de retours vaccins en plus gr\u00e2ce aux rappels automatiques.",
            "Belle clinique ! Les propri\u00e9taires de vos patients peuvent suivre l'historique sant\u00e9 de leur animal depuis leur t\u00e9l\u00e9phone ?",
            "Top pr\u00e9sence sur Instagram \U0001f436\U0001f431 Vos rappels de vaccination sont encore envoy\u00e9s manuellement ?"
        ],
        "scoring_vocab": ["v\u00e9t\u00e9rinaire", "v\u00e9to", "animal", "chien", "chat", "clinique", "soin", "sant\u00e9", "vaccination", "pet", "refuge", "animaux", "consult"],
    },
    {
        "name": "Opticiens",
        "emoji": "\U0001f453",
        "hashtags": ["#opticien", "#optique", "#lunettes", "#vuecorrection", "#ophtalmologie", "#monture", "#verres", "#contactlens"],
        "target_account_count": 3,
        "product_pitch": "AppySolution : application mobile pour opticiens. Essayage virtuel, rappels renouvellement ordonnance, fid\u00e9lit\u00e9. 490\u20ac setup + 89\u20ac/mois.",
        "dm_prompt_system": "Tu g\u00e9n\u00e8res des DMs Instagram pour proposer AppySolution aux opticiens (app essayage virtuel + rappels ordonnance + fid\u00e9lit\u00e9).\nR\u00c8GLES :\n- Observe leur style de montures ou leur approche mode/sant\u00e9\n- Met en avant : rappel automatique renouvellement 2 ans = clients qui reviennent sans action de ta part\n- 3 phrases max. Ton : mode + sant\u00e9, cr\u00e9atif.",
        "dm_fallback_templates": [
            "Superbes montures \U0001f453 ! Vos clients re\u00e7oivent un rappel automatique quand leur ordonnance arrive \u00e0 renouvellement ?",
            "Beau magasin d'optique ! Ils peuvent essayer virtuellement vos montures depuis leur t\u00e9l\u00e9phone ?",
            "Top s\u00e9lection de lunettes ! Les opticiens qu'on accompagne ont 40% de fid\u00e9lisation en plus avec les rappels ordonnance automatiques.",
            "Votre vitrine est top \U0001f60e La fid\u00e9lisation de vos clients entre deux paires de lunettes, vous g\u00e9rez comment ?",
            "Belle collection ! Un rappel automatique \u00e0 vos clients 1 mois avant le renouvellement de leur ordonnance, \u00e7a vous int\u00e9resse ?"
        ],
        "scoring_vocab": ["opticien", "optique", "lunettes", "monture", "verre", "vue", "correction", "myopie", "contact", "lentilles", "solaire", "optom\u00e9triste"],
    },
    {
        "name": "Notaires",
        "emoji": "\U0001f4dc",
        "hashtags": ["#notaire", "#notariat", "#immobilier", "#actenotarie", "#succession", "#achat immobilier", "#droit immobilier"],
        "target_account_count": 3,
        "product_pitch": "AppySolution : application mobile pour \u00e9tudes notariales. Suivi dossier client en temps r\u00e9el, upload documents s\u00e9curis\u00e9, signature \u00e9lectronique. 490\u20ac setup + 89\u20ac/mois.",
        "dm_prompt_system": "Tu g\u00e9n\u00e8res des DMs Instagram pour proposer AppySolution aux notaires (app suivi dossier + documents s\u00e9curis\u00e9s + signature \u00e9lectronique).\nR\u00c8GLES :\n- Observe leur type de communication (immobilier, succession, famille)\n- Met en avant : clients qui uploadent leurs documents depuis leur t\u00e9l\u00e9phone = dossiers complets plus vite\n- 3 phrases max. Ton : tr\u00e8s professionnel, sobre, z\u00e9ro \u00e9moji.\n- Formulation soign\u00e9e, niveau BCBG, vouvoiement.",
        "dm_fallback_templates": [
            "Belle pr\u00e9sence digitale pour une \u00e9tude notariale. Vos clients peuvent d\u00e9j\u00e0 d\u00e9poser leurs documents en ligne et suivre leur dossier de vente ? Cela acc\u00e9l\u00e8re consid\u00e9rablement les d\u00e9lais.",
            "Excellente communication. La gestion documentaire client \u00e0 distance, c'est encore par email chez vous actuellement ?",
            "\u00c9tude tr\u00e8s professionnelle. Les notaires que nous accompagnons r\u00e9duisent de 30% le d\u00e9lai moyen de traitement gr\u00e2ce \u00e0 l'upload client s\u00e9curis\u00e9.",
            "Tr\u00e8s bonne visibilit\u00e9 sur Instagram. La signature \u00e9lectronique pour vos actes sous seing priv\u00e9, vous la proposez d\u00e9j\u00e0 \u00e0 vos clients ?",
            "\u00c9tude s\u00e9rieuse et bien install\u00e9e. Vos clients ont un espace s\u00e9curis\u00e9 pour acc\u00e9der \u00e0 leurs actes et documents en dehors des consultations ?"
        ],
        "scoring_vocab": ["notaire", "notariat", "acte", "immobilier", "succession", "vente", "acquisition", "bail", "testament", "donation", "hypoth\u00e8que", "compromis"],
    },
]


async def seed_niches(tenant_id: int = 1):
    """Insere les 10 niches pour un tenant donne."""
    await init_db()

    async with async_session() as session:
        # Verifier si deja seede
        result = await session.execute(
            select(Niche).where(Niche.tenant_id == tenant_id)
        )
        existing = result.scalars().all()
        if existing:
            print(f"[SKIP] {len(existing)} niches existent deja pour tenant_id={tenant_id}")
            return

        for niche_data in NICHES:
            niche = Niche(
                tenant_id=tenant_id,
                name=niche_data["name"],
                emoji=niche_data["emoji"],
                hashtags=json.dumps(niche_data["hashtags"], ensure_ascii=False),
                target_account_count=niche_data["target_account_count"],
                product_pitch=niche_data["product_pitch"],
                dm_prompt_system=niche_data["dm_prompt_system"],
                dm_fallback_templates=json.dumps(niche_data["dm_fallback_templates"], ensure_ascii=False),
                scoring_vocab=json.dumps(niche_data["scoring_vocab"], ensure_ascii=False),
            )
            session.add(niche)

        await session.commit()
        print(f"[OK] 10 niches seedees pour tenant_id={tenant_id}")


if __name__ == "__main__":
    asyncio.run(seed_niches())
