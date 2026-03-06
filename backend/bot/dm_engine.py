"""Le cerveau des envois DM : queue, relances, 2-step, interest detection."""

import json
import random
from datetime import datetime, timedelta

from sqlalchemy import and_, select, update

from backend.bot.account_pool import AccountPool
from backend.bot.ig_client import IGClient, human_delay, is_active_hours
from backend.database import async_session
from backend.models import AbVariant, IgAccount, Message, Niche, Prospect, SystemLog
from backend.services.groq_service import GroqService

# Mots-cles pour detection d'interet
POSITIVE_KEYWORDS = [
    "interesse", "intéressé", "intéressée", "oui", "dites m'en plus", "dites-moi plus",
    "en savoir plus", "comment ca marche", "comment ça marche", "c'est quoi",
    "combien", "prix", "tarif", "demo", "démo", "demonstration", "rdv",
    "rendez-vous", "appelez-moi", "appelez moi", "appel", "disponible",
    "pourquoi pas", "ok", "d'accord", "je veux bien", "volontiers",
    "envoyer", "envoyez", "plus d'info", "plus d'infos", "curieux",
]

NEGATIVE_KEYWORDS = [
    "non merci", "pas interesse", "pas intéressé", "pas intéressée",
    "arretez", "arrêtez", "stop", "spam", "ne me contactez plus",
    "ne m'ecrivez plus", "ne m'écrivez plus", "desabonner", "désabonner",
    "pas besoin", "laissez-moi", "laissez moi", "foutez-moi la paix",
    "signaler", "bloquer", "bloque", "non", "jamais",
]


async def _log(tenant_id: int, level: str, message: str, details: dict | None = None):
    async with async_session() as session:
        session.add(SystemLog(
            tenant_id=tenant_id,
            level=level,
            module="dm_engine",
            message=message,
            details=json.dumps(details or {}, ensure_ascii=False),
        ))
        await session.commit()


class DMEngine:
    """Le cerveau des envois DM."""

    def __init__(self):
        self.groq = GroqService()
        self.pool = AccountPool()
        self.ig_client = IGClient()
        self.ab_manager = ABTestManager()

    async def process_niche_dm_queue(self, niche: Niche, tenant_id: int):
        """Traite la queue DM d'une niche."""
        if not is_active_hours():
            return

        async with async_session() as session:
            result = await session.execute(
                select(Prospect)
                .where(
                    Prospect.tenant_id == tenant_id,
                    Prospect.niche_id == niche.id,
                    Prospect.status == "follow_back",
                )
                .order_by(Prospect.score.desc())
            )
            prospects = result.scalars().all()

        for prospect in prospects:
            # Verifier si DM pas deja envoye
            async with async_session() as session:
                existing = await session.execute(
                    select(Message)
                    .where(
                        Message.prospect_id == prospect.id,
                        Message.direction == "outbound",
                        Message.is_relance == False,  # noqa: E712
                    )
                )
                if existing.scalar_one_or_none():
                    continue

            # Selectionner compte avec quota DM disponible
            account = await self.pool.get_account_for_action(
                niche_id=niche.id, action="dm", tenant_id=tenant_id,
            )
            if not account:
                await _log(tenant_id, "WARNING", f"Aucun compte disponible pour DM dans niche {niche.name}")
                break  # Plus de quota pour cette niche

            # Selectionner variant A/B
            variant = await self.ab_manager.get_active_variant(niche.id, tenant_id)

            # Generer DM (step 1 = curiosite)
            dm_text = await self._build_dm_message(prospect, niche, account, step=1)

            # Envoyer via ig_client
            result = await self.ig_client.send_dm(account, prospect.username, dm_text)

            # Sauvegarder message en DB
            async with async_session() as session:
                msg = Message(
                    tenant_id=tenant_id,
                    prospect_id=prospect.id,
                    ig_account_id=account.id,
                    direction="outbound",
                    content=dm_text,
                    status="sent" if result["success"] else "failed",
                    ig_message_id=result.get("message_id", ""),
                    ab_variant=variant.variant_letter if variant else None,
                    generated_by="groq" if result["success"] else "fallback",
                    error_message=result.get("error", ""),
                    sent_at=datetime.utcnow() if result["success"] else None,
                )
                session.add(msg)
                await session.commit()

            if result["success"]:
                # Update prospect status
                async with async_session() as session:
                    await session.execute(
                        update(Prospect)
                        .where(Prospect.id == prospect.id)
                        .values(status="dm_sent", first_dm_at=datetime.utcnow(), last_dm_at=datetime.utcnow())
                    )
                    await session.commit()

                # Record A/B send
                if variant:
                    await self.ab_manager.record_send(variant.id)

                await _log(tenant_id, "INFO", f"DM envoye a @{prospect.username} via @{account.username}")
            else:
                await _log(tenant_id, "ERROR", f"DM echoue pour @{prospect.username}: {result.get('error')}")

    async def process_follow_queue(self, niche: Niche, tenant_id: int):
        """Follow les prospects status='scored' tries par score DESC."""
        if not is_active_hours():
            return

        async with async_session() as session:
            result = await session.execute(
                select(Prospect)
                .where(
                    Prospect.tenant_id == tenant_id,
                    Prospect.niche_id == niche.id,
                    Prospect.status == "scored",
                )
                .order_by(Prospect.score.desc())
                .limit(20)
            )
            prospects = result.scalars().all()

        for prospect in prospects:
            account = await self.pool.get_account_for_action(
                niche_id=niche.id, action="follow", tenant_id=tenant_id,
            )
            if not account:
                break

            success = await self.ig_client.follow(account, prospect.username)
            if success:
                async with async_session() as session:
                    await session.execute(
                        update(Prospect)
                        .where(Prospect.id == prospect.id)
                        .values(status="followed", followed_at=datetime.utcnow())
                    )
                    await session.commit()

    async def check_follow_backs(self, tenant_id: int):
        """Verifie les follow-backs pour les prospects suivis depuis > 24h."""
        cutoff = datetime.utcnow() - timedelta(hours=24)

        async with async_session() as session:
            result = await session.execute(
                select(Prospect)
                .where(
                    Prospect.tenant_id == tenant_id,
                    Prospect.status == "followed",
                    Prospect.followed_at < cutoff,
                )
            )
            prospects = result.scalars().all()

        for prospect in prospects:
            # En production, on verifierait via ig_client si le prospect a follow-back
            # Pour l'instant on simule — sera connecte au vrai check en Session 5
            pass

    async def process_relances(self, tenant_id: int):
        """
        Relances automatiques :
        - D+7 : premiere relance si pas de reponse
        - D+14 : deuxieme relance
        - D+21 : troisieme et derniere
        Apres D+21 sans reponse → status = 'lost'
        """
        if not is_active_hours():
            return

        now = datetime.utcnow()

        # Prospects DM envoye sans reponse
        async with async_session() as session:
            result = await session.execute(
                select(Prospect)
                .where(
                    Prospect.tenant_id == tenant_id,
                    Prospect.status == "dm_sent",
                    Prospect.first_dm_at.isnot(None),
                )
            )
            prospects = result.scalars().all()

        for prospect in prospects:
            if not prospect.first_dm_at:
                continue

            days_since_dm = (now - prospect.first_dm_at).days

            # Compter les relances deja envoyees
            async with async_session() as session:
                count_result = await session.execute(
                    select(Message)
                    .where(
                        Message.prospect_id == prospect.id,
                        Message.is_relance == True,  # noqa: E712
                    )
                )
                existing_relances = len(count_result.scalars().all())

            # Determiner si une relance est due
            relance_number = 0
            if days_since_dm >= 7 and existing_relances < 1:
                relance_number = 1
            elif days_since_dm >= 14 and existing_relances < 2:
                relance_number = 2
            elif days_since_dm >= 21 and existing_relances < 3:
                relance_number = 3

            if relance_number == 0:
                # Verifier si on est au-dela de D+21 avec 3 relances deja envoyees
                if days_since_dm > 28 and existing_relances >= 3:
                    async with async_session() as session:
                        await session.execute(
                            update(Prospect)
                            .where(Prospect.id == prospect.id)
                            .values(status="lost")
                        )
                        await session.commit()
                    await _log(tenant_id, "INFO", f"@{prospect.username} → lost (3 relances sans reponse)")
                continue

            # Recuperer niche pour generer la relance
            async with async_session() as session:
                niche = await session.get(Niche, prospect.niche_id)
                if not niche:
                    continue

            # Generer et envoyer la relance
            account = await self.pool.get_account_for_action(
                niche_id=prospect.niche_id, action="dm", tenant_id=tenant_id,
            )
            if not account:
                continue

            relance_text = await self.groq.generate_relance(prospect, niche, relance_number)
            result = await self.ig_client.send_dm(account, prospect.username, relance_text)

            if result["success"]:
                async with async_session() as session:
                    msg = Message(
                        tenant_id=tenant_id,
                        prospect_id=prospect.id,
                        ig_account_id=account.id,
                        direction="outbound",
                        content=relance_text,
                        status="sent",
                        is_relance=True,
                        relance_number=relance_number,
                        generated_by="groq",
                        sent_at=datetime.utcnow(),
                    )
                    session.add(msg)
                    await session.execute(
                        update(Prospect)
                        .where(Prospect.id == prospect.id)
                        .values(last_dm_at=datetime.utcnow())
                    )
                    await session.commit()

                await _log(tenant_id, "INFO", f"Relance {relance_number} envoyee a @{prospect.username}")

    async def handle_incoming_reply(self, prospect_id: int, message_text: str, ig_account_id: int | None = None):
        """Traite une reponse entrante."""
        async with async_session() as session:
            prospect = await session.get(Prospect, prospect_id)
            if not prospect:
                return

            # Sauvegarder le message inbound
            msg = Message(
                tenant_id=prospect.tenant_id,
                prospect_id=prospect_id,
                ig_account_id=ig_account_id or 0,
                direction="inbound",
                content=message_text,
                status="delivered",
            )
            session.add(msg)

            # Detecter l'interet
            interest = await self.detect_interest(message_text)

            if interest == "positive":
                prospect.status = "interested"
                prospect.last_reply_at = datetime.utcnow()
                await _log(
                    prospect.tenant_id, "INFO",
                    f"REPONSE POSITIVE de @{prospect.username}: {message_text[:100]}",
                    {"interest": "positive"},
                )
            elif interest == "negative":
                prospect.status = "lost"
                prospect.last_reply_at = datetime.utcnow()
                await _log(
                    prospect.tenant_id, "INFO",
                    f"Reponse negative de @{prospect.username}: {message_text[:100]}",
                    {"interest": "negative"},
                )
            else:
                prospect.status = "replied"
                prospect.last_reply_at = datetime.utcnow()

            await session.commit()

    async def detect_interest(self, message_text: str) -> str:
        """
        Classifie la reponse :
        - "positive" : interet, question, demande de demo
        - "negative" : non merci, pas interesse, arretez
        - "neutral" : reponse ambigue
        """
        text_lower = message_text.lower().strip()

        # Check negative first (plus important a detecter)
        for kw in NEGATIVE_KEYWORDS:
            if kw in text_lower:
                return "negative"

        # Check positive
        for kw in POSITIVE_KEYWORDS:
            if kw in text_lower:
                return "positive"

        # Questions = generalement positif
        if "?" in text_lower and len(text_lower) > 10:
            return "positive"

        return "neutral"

    async def _build_dm_message(
        self,
        prospect: Prospect,
        niche: Niche,
        account: IgAccount,
        step: int = 1,
    ) -> str:
        """
        Step 1 : curiosite sans pitch produit
        Step 2 : presentation produit (si reponse positive au step 1)
        """
        if step == 1:
            return await self.groq.generate_dm(prospect, niche, account)

        # Step 2 : pitch after positive response
        try:
            from backend.services.groq_service import call_groq
            system_prompt = (
                f"Tu es un expert en prospection B2B pour {niche.name}.\n"
                f"Le prospect a repondu positivement a ton premier message.\n"
                f"Maintenant, presente brievement le produit et propose un RDV.\n"
                f"Produit : {niche.product_pitch}\n"
                f"Maximum 3 phrases. Ton : enthousiaste mais professionnel."
            )
            user_prompt = (
                f"Prospect : @{prospect.username}\n"
                f"Genere le message de presentation produit (step 2) :"
            )
            return await call_groq(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=200,
                temperature=0.8,
            )
        except Exception:
            return (
                f"Super ! On a justement une solution pour ca — AppySolution. "
                f"En 2 mots : {niche.product_pitch.split('.')[0]}. "
                f"Ca vous dirait qu'on en discute 15min ?"
            )


class ABTestManager:
    """Gere les variants A/B par niche."""

    async def get_active_variant(self, niche_id: int, tenant_id: int) -> AbVariant | None:
        """
        Selectionne le variant a utiliser :
        - Si winner detecte : 100% winner
        - Sinon : distribution 80/20 (80% au meilleur, 20% aux autres)
        """
        async with async_session() as session:
            # Chercher un winner
            result = await session.execute(
                select(AbVariant)
                .where(
                    AbVariant.tenant_id == tenant_id,
                    AbVariant.niche_id == niche_id,
                    AbVariant.is_winner == True,  # noqa: E712
                    AbVariant.status == "winner",
                )
            )
            winner = result.scalar_one_or_none()
            if winner:
                return winner

            # Pas de winner : distribution 80/20
            result = await session.execute(
                select(AbVariant)
                .where(
                    AbVariant.tenant_id == tenant_id,
                    AbVariant.niche_id == niche_id,
                    AbVariant.status == "testing",
                )
                .order_by(AbVariant.response_rate.desc())
            )
            variants = result.scalars().all()
            if not variants:
                return None

            # 80% chance de prendre le meilleur, 20% un autre
            if random.random() < 0.8:
                return variants[0]
            return random.choice(variants[1:]) if len(variants) > 1 else variants[0]

    async def record_send(self, variant_id: int):
        """Incremente sends du variant."""
        async with async_session() as session:
            variant = await session.get(AbVariant, variant_id)
            if variant:
                variant.sends += 1
                await session.commit()

    async def record_response(self, variant_id: int):
        """Incremente responses + recalcule response_rate."""
        async with async_session() as session:
            variant = await session.get(AbVariant, variant_id)
            if variant:
                variant.responses += 1
                variant.response_rate = variant.responses / max(variant.sends, 1)
                await session.commit()

    async def check_for_winner(self, niche_id: int, tenant_id: int) -> AbVariant | None:
        """
        Apres 100 envois minimum par variant :
        Si un variant a response_rate > 2x la moyenne → c'est le winner.
        """
        async with async_session() as session:
            result = await session.execute(
                select(AbVariant)
                .where(
                    AbVariant.tenant_id == tenant_id,
                    AbVariant.niche_id == niche_id,
                    AbVariant.status == "testing",
                )
            )
            variants = result.scalars().all()

        # Tous doivent avoir au moins 100 envois
        if not all(v.sends >= 100 for v in variants):
            return None

        avg_rate = sum(v.response_rate for v in variants) / max(len(variants), 1)
        if avg_rate == 0:
            return None

        for variant in variants:
            if variant.response_rate > avg_rate * 2:
                # Winner detecte
                async with async_session() as session:
                    await session.execute(
                        update(AbVariant)
                        .where(AbVariant.id == variant.id)
                        .values(is_winner=True, status="winner")
                    )
                    # Pauser les autres
                    await session.execute(
                        update(AbVariant)
                        .where(
                            AbVariant.niche_id == niche_id,
                            AbVariant.tenant_id == tenant_id,
                            AbVariant.id != variant.id,
                        )
                        .values(status="paused")
                    )
                    await session.commit()
                return variant

        return None

    async def initialize_variants_for_niche(self, niche: Niche):
        """Cree 5 variants (A-E) depuis les dm_fallback_templates de la niche."""
        try:
            templates = json.loads(niche.dm_fallback_templates)
        except (json.JSONDecodeError, TypeError):
            templates = []

        letters = ["A", "B", "C", "D", "E"]
        async with async_session() as session:
            # Verifier si deja initialise
            result = await session.execute(
                select(AbVariant)
                .where(
                    AbVariant.tenant_id == niche.tenant_id,
                    AbVariant.niche_id == niche.id,
                )
            )
            if result.scalars().first():
                return

            for i, letter in enumerate(letters):
                template = templates[i] if i < len(templates) else f"Template {letter} par defaut"
                variant = AbVariant(
                    tenant_id=niche.tenant_id,
                    niche_id=niche.id,
                    variant_letter=letter,
                    template=template,
                    status="testing",
                )
                session.add(variant)
            await session.commit()
