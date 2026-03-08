"""
WarmupActions — Actions de warmup Playwright pour comptes Instagram.

Simule un comportement humain naturel :
- Like random posts sur Explore
- Follow des comptes populaires
- Watch stories
- Scroll le feed

Utilise Playwright (web) car instagrapi est bloque pour les nouveaux comptes.
"""

import asyncio
import logging
import random
from datetime import datetime

from sqlalchemy import select

from backend.database import async_session
from backend.models import IgAccount, Proxy
from backend.accounts.pool_manager import get_quotas_for_account

logger = logging.getLogger("instafarm.warmup")

# User agent Chrome desktop
CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
)

# Comptes populaires FR pour follow warmup (non-prives, gros comptes)
POPULAR_ACCOUNTS = [
    "paris", "lyon", "marseille", "bordeaux",
    "lefooding", "thefork_fr", "tripadvisorfr",
    "bonappetitmag", "foodnetwork", "cuisineactuelle",
]

# Delai humain entre actions (secondes)
MIN_DELAY = 3
MAX_DELAY = 8


async def _human_delay(min_s: float = MIN_DELAY, max_s: float = MAX_DELAY):
    """Pause aleatoire pour simuler un humain."""
    delay = random.uniform(min_s, max_s)
    await asyncio.sleep(delay)


class WarmupActions:
    """Actions de warmup via Playwright web."""

    async def _get_account_with_proxy(
        self, account_id: int
    ) -> tuple[IgAccount | None, Proxy | None]:
        """Charge un compte et son proxy depuis la DB."""
        async with async_session() as session:
            result = await session.execute(
                select(IgAccount).where(IgAccount.id == account_id)
            )
            account = result.scalars().first()
            if not account:
                return None, None

            proxy = None
            if account.proxy_id:
                result = await session.execute(
                    select(Proxy).where(Proxy.id == account.proxy_id)
                )
                proxy = result.scalars().first()

            return account, proxy

    async def _launch_browser(self, proxy: Proxy | None):
        """Lance un browser Playwright avec proxy optionnel."""
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()

        launch_opts = {
            "headless": True,
            "args": ["--disable-blink-features=AutomationControlled"],
        }

        if proxy:
            launch_opts["proxy"] = {
                "server": f"http://{proxy.host}:{proxy.port}",
                "username": proxy.username or "",
                "password": proxy.password or "",
            }

        browser = await pw.chromium.launch(**launch_opts)
        context = await browser.new_context(
            user_agent=CHROME_UA,
            viewport={"width": 1280, "height": 800},
            locale="fr-FR",
        )
        page = await context.new_page()
        return pw, browser, context, page

    async def _login(self, page, username: str, password: str) -> bool:
        """Login Instagram via web."""
        try:
            await page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle")
            await _human_delay(2, 4)

            # Cookie consent
            try:
                consent = page.get_by_role("button", name="Autoriser tous les cookies")
                if await consent.is_visible(timeout=3000):
                    await consent.scroll_into_view_if_needed()
                    await consent.click()
                    await _human_delay(1, 2)
            except Exception:
                pass

            # Fill credentials
            username_input = page.locator('input[name="username"]')
            password_input = page.locator('input[name="password"]')

            await username_input.fill(username)
            await _human_delay(0.5, 1.5)
            await password_input.fill(password)
            await _human_delay(0.5, 1.5)

            # Submit
            await page.locator('button[type="submit"]').click()
            await page.wait_for_load_state("networkidle", timeout=15000)

            # Handle terms/consent pages
            for _ in range(3):
                url = page.url
                if "/consent/" in url or "terms" in url:
                    try:
                        suivant = page.get_by_role("button", name="Suivant")
                        if await suivant.is_visible(timeout=2000):
                            await suivant.click()
                            await _human_delay(1, 2)
                            continue
                    except Exception:
                        pass
                    try:
                        accepter = page.get_by_role("button", name="Accepter")
                        if await accepter.is_visible(timeout=2000):
                            await accepter.click()
                            await _human_delay(1, 2)
                            continue
                    except Exception:
                        pass
                break

            # Navigate to home if needed
            if "instagram.com" in page.url and "/accounts/" not in page.url:
                if "/api/" in page.url or page.url.endswith("/"):
                    await page.goto("https://www.instagram.com/", wait_until="networkidle")

            # Dismiss "Plus tard" dialogs
            for _ in range(2):
                try:
                    plus_tard = page.get_by_role("button", name="Plus tard")
                    if await plus_tard.is_visible(timeout=2000):
                        await plus_tard.click()
                        await _human_delay(0.5, 1)
                except Exception:
                    break

            # Verify login success
            is_home = "instagram.com" in page.url and "/accounts/login" not in page.url
            if is_home:
                logger.info(f"[Warmup] Login OK: @{username}")
                return True
            else:
                logger.warning(f"[Warmup] Login echoue: @{username} (url={page.url})")
                return False

        except Exception as e:
            logger.error(f"[Warmup] Login erreur @{username}: {e}")
            return False

    # ------------------------------------------------------------------
    # LIKE RANDOM POSTS (Explore page)
    # ------------------------------------------------------------------
    async def like_random_posts(
        self, account_id: int, count: int = 3, dry_run: bool = False
    ) -> dict:
        """
        Like des posts aleatoires sur la page Explore.

        Args:
            account_id: ID du compte
            count: nombre de likes a faire
            dry_run: si True, simule sans executer

        Returns:
            dict avec resultats
        """
        if dry_run:
            logger.info(f"[Warmup] DRY RUN: like_random_posts(account={account_id}, count={count})")
            return {"action": "like", "dry_run": True, "planned_count": count}

        account, proxy = await self._get_account_with_proxy(account_id)
        if not account:
            return {"error": "Compte non trouve"}

        quotas = get_quotas_for_account(account.warmup_day, account.status)
        max_likes = quotas["likes"] - account.likes_today
        count = min(count, max_likes)
        if count <= 0:
            return {"action": "like", "skipped": True, "reason": "Quota likes atteint"}

        pw, browser, context, page = await self._launch_browser(proxy)
        liked = 0

        try:
            if not await self._login(page, account.username, account.password):
                return {"error": "Login echoue"}

            # Aller sur Explore
            await page.goto("https://www.instagram.com/explore/", wait_until="networkidle")
            await _human_delay(2, 4)

            # Cliquer sur des posts et liker
            posts = await page.locator("article a").all()
            random.shuffle(posts)

            for post in posts[:count]:
                try:
                    await post.click()
                    await _human_delay(1, 3)

                    # Chercher le bouton like (coeur SVG)
                    like_btn = page.locator('svg[aria-label="J\'aime"]').first
                    if await like_btn.is_visible(timeout=3000):
                        await like_btn.click()
                        liked += 1
                        logger.debug(f"[Warmup] @{account.username} liked post ({liked}/{count})")
                        await _human_delay(2, 5)

                    # Fermer le post
                    try:
                        close = page.locator('svg[aria-label="Fermer"]').first
                        if await close.is_visible(timeout=2000):
                            await close.click()
                            await _human_delay(1, 2)
                    except Exception:
                        await page.go_back()
                        await _human_delay(1, 2)

                except Exception as e:
                    logger.debug(f"[Warmup] Like erreur: {e}")
                    continue

            # Update DB
            async with async_session() as session:
                result = await session.execute(
                    select(IgAccount).where(IgAccount.id == account_id)
                )
                acc = result.scalars().first()
                if acc:
                    acc.likes_today += liked
                    acc.last_action = datetime.utcnow()
                    await session.commit()

        finally:
            await browser.close()
            await pw.stop()

        logger.info(f"[Warmup] @{account.username} liked {liked}/{count} posts")
        return {"action": "like", "liked": liked, "target": count}

    # ------------------------------------------------------------------
    # FOLLOW ACCOUNT
    # ------------------------------------------------------------------
    async def follow_account(
        self, account_id: int, target_username: str | None = None, dry_run: bool = False
    ) -> dict:
        """
        Follow un compte (random populaire ou specifique).

        Args:
            account_id: ID du compte
            target_username: username a follow (random si None)
            dry_run: si True, simule sans executer
        """
        if not target_username:
            target_username = random.choice(POPULAR_ACCOUNTS)

        if dry_run:
            logger.info(
                f"[Warmup] DRY RUN: follow_account(account={account_id}, "
                f"target=@{target_username})"
            )
            return {"action": "follow", "dry_run": True, "target": target_username}

        account, proxy = await self._get_account_with_proxy(account_id)
        if not account:
            return {"error": "Compte non trouve"}

        quotas = get_quotas_for_account(account.warmup_day, account.status)
        if account.follows_today >= quotas["follows"]:
            return {"action": "follow", "skipped": True, "reason": "Quota follows atteint"}

        pw, browser, context, page = await self._launch_browser(proxy)
        followed = False

        try:
            if not await self._login(page, account.username, account.password):
                return {"error": "Login echoue"}

            # Aller sur le profil cible
            await page.goto(
                f"https://www.instagram.com/{target_username}/",
                wait_until="networkidle",
            )
            await _human_delay(2, 4)

            # Cliquer sur "Suivre" / "S'abonner"
            follow_btn = page.get_by_role("button", name="Suivre").first
            try:
                if await follow_btn.is_visible(timeout=3000):
                    await follow_btn.click()
                    followed = True
                    await _human_delay(1, 3)
            except Exception:
                # Essayer "S'abonner"
                try:
                    follow_btn2 = page.get_by_role("button", name="S'abonner").first
                    if await follow_btn2.is_visible(timeout=2000):
                        await follow_btn2.click()
                        followed = True
                except Exception:
                    pass

            if followed:
                async with async_session() as session:
                    result = await session.execute(
                        select(IgAccount).where(IgAccount.id == account_id)
                    )
                    acc = result.scalars().first()
                    if acc:
                        acc.follows_today += 1
                        acc.total_follows += 1
                        acc.last_action = datetime.utcnow()
                        await session.commit()

        finally:
            await browser.close()
            await pw.stop()

        logger.info(
            f"[Warmup] @{account.username} {'followed' if followed else 'failed to follow'} "
            f"@{target_username}"
        )
        return {"action": "follow", "followed": followed, "target": target_username}

    # ------------------------------------------------------------------
    # WATCH STORIES
    # ------------------------------------------------------------------
    async def watch_stories(
        self, account_id: int, count: int = 3, dry_run: bool = False
    ) -> dict:
        """
        Regarde des stories sur le feed.

        Args:
            account_id: ID du compte
            count: nombre de stories a regarder
            dry_run: si True, simule
        """
        if dry_run:
            logger.info(f"[Warmup] DRY RUN: watch_stories(account={account_id}, count={count})")
            return {"action": "stories", "dry_run": True, "planned_count": count}

        account, proxy = await self._get_account_with_proxy(account_id)
        if not account:
            return {"error": "Compte non trouve"}

        pw, browser, context, page = await self._launch_browser(proxy)
        watched = 0

        try:
            if not await self._login(page, account.username, account.password):
                return {"error": "Login echoue"}

            # Sur le feed, les stories sont en haut
            await _human_delay(2, 4)

            # Cliquer sur la premiere story
            story_rings = await page.locator("canvas").all()
            if story_rings:
                try:
                    await story_rings[0].click()
                    await _human_delay(3, 6)
                    watched += 1

                    # Naviguer entre stories (clic droit de l'ecran)
                    for _ in range(min(count - 1, 5)):
                        await page.click("body", position={"x": 900, "y": 400})
                        await _human_delay(2, 5)
                        watched += 1

                    # Fermer
                    try:
                        close = page.locator('svg[aria-label="Fermer"]').first
                        if await close.is_visible(timeout=2000):
                            await close.click()
                    except Exception:
                        await page.keyboard.press("Escape")
                except Exception as e:
                    logger.debug(f"[Warmup] Story erreur: {e}")

            # Update last_action
            async with async_session() as session:
                result = await session.execute(
                    select(IgAccount).where(IgAccount.id == account_id)
                )
                acc = result.scalars().first()
                if acc:
                    acc.last_action = datetime.utcnow()
                    await session.commit()

        finally:
            await browser.close()
            await pw.stop()

        logger.info(f"[Warmup] @{account.username} watched {watched} stories")
        return {"action": "stories", "watched": watched, "target": count}

    # ------------------------------------------------------------------
    # SCROLL FEED
    # ------------------------------------------------------------------
    async def scroll_feed(
        self, account_id: int, duration_sec: int = 30, dry_run: bool = False
    ) -> dict:
        """
        Scroll le feed pendant une duree donnee (simule consultation).

        Args:
            account_id: ID du compte
            duration_sec: duree en secondes
            dry_run: si True, simule
        """
        if dry_run:
            logger.info(
                f"[Warmup] DRY RUN: scroll_feed(account={account_id}, "
                f"duration={duration_sec}s)"
            )
            return {"action": "scroll", "dry_run": True, "planned_duration": duration_sec}

        account, proxy = await self._get_account_with_proxy(account_id)
        if not account:
            return {"error": "Compte non trouve"}

        pw, browser, context, page = await self._launch_browser(proxy)
        scroll_count = 0

        try:
            if not await self._login(page, account.username, account.password):
                return {"error": "Login echoue"}

            # Scroll le feed
            start = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start) < duration_sec:
                scroll_amount = random.randint(300, 800)
                await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
                scroll_count += 1
                await _human_delay(2, 5)

            # Update last_action
            async with async_session() as session:
                result = await session.execute(
                    select(IgAccount).where(IgAccount.id == account_id)
                )
                acc = result.scalars().first()
                if acc:
                    acc.last_action = datetime.utcnow()
                    await session.commit()

        finally:
            await browser.close()
            await pw.stop()

        logger.info(
            f"[Warmup] @{account.username} scrolled feed "
            f"({scroll_count} scrolls, {duration_sec}s)"
        )
        return {"action": "scroll", "scrolls": scroll_count, "duration_sec": duration_sec}

    # ------------------------------------------------------------------
    # RUN DAILY WARMUP (orchestrateur)
    # ------------------------------------------------------------------
    async def run_daily_warmup(
        self, account_id: int, dry_run: bool = False
    ) -> dict:
        """
        Execute le warmup quotidien complet pour un compte.
        Adapte les actions selon le warmup_day.

        Args:
            account_id: ID du compte
            dry_run: si True, simule tout

        Returns:
            dict avec resultats de chaque action
        """
        account, proxy = await self._get_account_with_proxy(account_id)
        if not account:
            return {"error": "Compte non trouve"}

        day = account.warmup_day
        results = {
            "account_id": account_id,
            "username": account.username,
            "warmup_day": day,
            "dry_run": dry_run,
            "actions": [],
        }

        logger.info(
            f"[Warmup] Daily warmup @{account.username} "
            f"(day={day}, dry_run={dry_run})"
        )

        # Scroll feed (tous les jours)
        scroll_duration = min(20 + day * 2, 60)  # 20s J0 → 60s J18+
        r = await self.scroll_feed(account_id, duration_sec=scroll_duration, dry_run=dry_run)
        results["actions"].append(r)

        # Watch stories (a partir de J2)
        if day >= 2:
            story_count = min(2 + day // 3, 8)
            r = await self.watch_stories(account_id, count=story_count, dry_run=dry_run)
            results["actions"].append(r)

        # Like posts (a partir de J3)
        if day >= 3:
            quotas = get_quotas_for_account(day, account.status)
            like_count = min(random.randint(2, 5), quotas["likes"])
            r = await self.like_random_posts(account_id, count=like_count, dry_run=dry_run)
            results["actions"].append(r)

        # Follow (a partir de J5)
        if day >= 5:
            quotas = get_quotas_for_account(day, account.status)
            if quotas["follows"] > 0:
                r = await self.follow_account(account_id, dry_run=dry_run)
                results["actions"].append(r)

        logger.info(
            f"[Warmup] Daily warmup @{account.username} termine: "
            f"{len(results['actions'])} actions"
        )
        return results
