import logging
from datetime import datetime

import discord
from discord.ext import commands

from .scheduler import SchedulerService
from .storage import StorageService
from .commands import register_app_commands
from .scheduler import JST


log = logging.getLogger(__name__)


def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = False
    bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

    # attach services
    bot.scheduler = SchedulerService()
    bot.storage = StorageService()
    bot.last_post_time_by_channel = {}

    @bot.event
    async def on_ready():
        try:
            await bot.tree.sync()
        except Exception as e:
            log.exception("Slash commands sync failed: %s", e)
        log.info('Bot logged in as %s (id=%s)', bot.user, getattr(bot.user, 'id', '?'))

        # restore scheduled jobs after restart
        now = datetime.now(JST)
        for rec in bot.storage.list():
            try:
                if rec.type == 'once' and rec.when:
                    try:
                        dt = datetime.fromisoformat(rec.when)
                    except Exception:
                        continue
                    if dt.tzinfo is None:
                        # treat as JST
                        dt = JST.localize(dt)
                    if dt > now:
                        async def _post_once(ch_id: int, content: str):
                            ch = bot.get_channel(ch_id)
                            if isinstance(ch, discord.TextChannel):
                                try:
                                    await ch.send(content)
                                except Exception:
                                    log.exception('復旧投稿でエラー')
                        bot.scheduler.add_once(
                            rec.id,
                            dt,
                            lambda ch_id=rec.channel_id, content=rec.content: bot.loop.create_task(_post_once(ch_id, content)),
                        )
                elif rec.type == 'cron' and rec.cron:
                    async def _post_cron(ch_id: int, content: str):
                        ch = bot.get_channel(ch_id)
                        if isinstance(ch, discord.TextChannel):
                            try:
                                await ch.send(content)
                            except Exception:
                                log.exception('復旧定期投稿でエラー')
                    bot.scheduler.add_cron(
                        rec.id,
                        rec.cron,
                        lambda ch_id=rec.channel_id, content=rec.content: bot.loop.create_task(_post_cron(ch_id, content)),
                    )
            except Exception:
                log.exception('Failed to restore schedule: id=%s', rec.id)

    # register slash commands
    register_app_commands(bot)

    return bot

