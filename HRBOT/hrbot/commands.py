from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .scheduler import SchedulerService, JST
from .storage import ScheduleRecord


log = logging.getLogger(__name__)


def parse_datetime(text: str) -> Optional[datetime]:
    text = text.strip()
    now = datetime.now(JST)

    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})$", text)
    if m:
        y, M, d, h, m_ = map(int, m.groups())
        return JST.localize(datetime(y, M, d, h, m_))

    m = re.match(r"^(\d{1,2})\/(\d{1,2})\s+(\d{2}):(\d{2})$", text)
    if m:
        M, d, h, m_ = map(int, m.groups())
        return JST.localize(datetime(now.year, M, d, h, m_))

    m = re.match(r"^今日\s+(\d{2}):(\d{2})$", text)
    if m:
        h, m_ = map(int, m.groups())
        return JST.localize(datetime(now.year, now.month, now.day, h, m_))

    m = re.match(r"^明日\s+(\d{2}):(\d{2})$", text)
    if m:
        h, m_ = map(int, m.groups())
        dt = JST.localize(datetime(now.year, now.month, now.day, h, m_)) + timedelta(days=1)
        return dt

    return None


def require_admin(interaction: discord.Interaction) -> bool:
    perms = interaction.user.guild_permissions if isinstance(interaction.user, discord.Member) else None
    return bool(perms and perms.administrator)


class ScheduleGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name='schedule', description='スケジュール関連コマンド')
        self.bot = bot

    @app_commands.command(name='help', description='使い方を表示')
    async def help(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            '\n'.join([
                '/schedule add <日時> <チャンネル> <メッセージ>',
                '/schedule list',
                '/schedule delete <ID>',
                '/schedule edit <ID>',
            ]), ephemeral=True)

    @app_commands.command(name='list', description='スケジュールの一覧を表示')
    async def list(self, interaction: discord.Interaction):
        if not require_admin(interaction):
            await interaction.response.send_message('このコマンドは管理者のみ実行できます。', ephemeral=True)
            return
        records = self.bot.storage.list()
        if not records:
            await interaction.response.send_message('スケジュールはありません。', ephemeral=True)
            return
        lines = [f"ID: {r.id} | <#{r.channel_id}> | {r.type} | {r.when or r.cron} | {r.content[:40]}" for r in records]
        await interaction.response.send_message('\n'.join(lines), ephemeral=True)

    @app_commands.command(name='delete', description='指定IDのスケジュールを削除')
    @app_commands.describe(id='スケジュールID')
    async def delete(self, interaction: discord.Interaction, id: str):
        if not require_admin(interaction):
            await interaction.response.send_message('このコマンドは管理者のみ実行できます。', ephemeral=True)
            return
        ok = self.bot.storage.delete(id)
        self.bot.scheduler.remove(id)
        await interaction.response.send_message('削除しました。' if ok else '該当IDが見つかりません。', ephemeral=True)

    @app_commands.command(name='add', description='指定日時に投稿を予約')
    @app_commands.describe(when='YYYY-MM-DD HH:MM | 今日 HH:MM | 明日 HH:MM | MM/DD HH:MM',
                           channel='投稿先チャンネル', message='投稿するメッセージ')
    async def add(self, interaction: discord.Interaction, when: str, channel: discord.TextChannel, message: str):
        if not require_admin(interaction):
            await interaction.response.send_message('このコマンドは管理者のみ実行できます。', ephemeral=True)
            return

        dt = parse_datetime(when)
        if dt is None:
            await interaction.response.send_message('日時の形式が無効です。', ephemeral=True)
            return
        if not (1 <= len(message) <= 1800):
            await interaction.response.send_message('メッセージ長が不正です。', ephemeral=True)
            return

        schedule_id = uuid.uuid4().hex[:8]

        async def post_message(ch_id: int, content: str):
            ch = self.bot.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                # 簡易レート制限: 同一チャンネルで5秒未満の連投を防止
                last = getattr(self.bot, 'last_post_time_by_channel', {}).get(ch_id)
                now = discord.utils.utcnow()
                allow = True if last is None else (now - last).total_seconds() >= 5
                if not allow:
                    return
                try:
                    await ch.send(content)
                    getattr(self.bot, 'last_post_time_by_channel', {}).update({ch_id: now})
                except discord.Forbidden:
                    log.warning('権限不足で投稿できません: channel=%s', ch_id)
                except Exception:
                    log.exception('投稿中にエラーが発生しました')

        self.bot.scheduler.add_once(
            schedule_id,
            dt,
            lambda ch_id=channel.id, content=message: asyncio.create_task(post_message(ch_id, content))
        )

        self.bot.storage.upsert(ScheduleRecord(
            id=schedule_id,
            channel_id=channel.id,
            content=message,
            type='once',
            when=dt.isoformat(),
        ))

        await interaction.response.send_message(f'予約しました: ID={schedule_id} {dt.strftime("%Y-%m-%d %H:%M")}', ephemeral=True)

    @app_commands.command(name='edit', description='指定IDのスケジュールを編集')
    @app_commands.describe(id='スケジュールID')
    async def edit(self, interaction: discord.Interaction, id: str):
        if not require_admin(interaction):
            await interaction.response.send_message('このコマンドは管理者のみ実行できます。', ephemeral=True)
            return
        record = self.bot.storage.get(id)
        if not record:
            await interaction.response.send_message('該当IDが見つかりません。', ephemeral=True)
            return

        bot = self.bot

        class EditModal(discord.ui.Modal, title='スケジュール編集'):
            content = discord.ui.TextInput(label='メッセージ', style=discord.TextStyle.paragraph, default=record.content, max_length=1800)
            when = discord.ui.TextInput(label='日時 (空欄なら変更なし)', required=False, default=record.when or '')

            async def on_submit(self, interaction2: discord.Interaction):
                new_content = str(self.content)
                new_when = str(self.when).strip() if self.when is not None else ''

                if not (1 <= len(new_content) <= 1800):
                    await interaction2.response.send_message('メッセージ長が不正です。', ephemeral=True)
                    return

                if new_when:
                    parsed = parse_datetime(new_when)
                    if not parsed:
                        await interaction2.response.send_message('日時の形式が無効です。', ephemeral=True)
                        return
                    bot.scheduler.remove(record.id)

                    async def post_message(ch_id: int, content: str):
                        ch = bot.get_channel(ch_id)
                        if isinstance(ch, discord.TextChannel):
                            try:
                                await ch.send(content)
                            except discord.Forbidden:
                                log.warning('権限不足で投稿できません: channel=%s', ch_id)
                            except Exception:
                                log.exception('投稿中にエラーが発生しました')

                    bot.scheduler.add_once(record.id, parsed, lambda ch_id=record.channel_id, content=new_content: asyncio.create_task(post_message(ch_id, content)))
                    record.when = parsed.isoformat()
                    record.type = 'once'

                record.content = new_content
                bot.storage.upsert(record)
                await interaction2.response.send_message('更新しました。', ephemeral=True)

        await interaction.response.send_modal(EditModal())


class RepeatGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name='repeat', description='定期投稿を設定')
        self.bot = bot

    @app_commands.command(name='daily', description='毎日定時投稿を設定')
    @app_commands.describe(time='HH:MM', channel='投稿先チャンネル', message='投稿するメッセージ')
    async def daily(self, interaction: discord.Interaction, time: str, channel: discord.TextChannel, message: str):
        if not require_admin(interaction):
            await interaction.response.send_message('このコマンドは管理者のみ実行できます。', ephemeral=True)
            return
        m = re.match(r"^(\d{2}):(\d{2})$", time)
        if not m:
            await interaction.response.send_message('時刻の形式が無効です。', ephemeral=True)
            return
        hh, mm = map(int, m.groups())
        cron = f"{mm} {hh} * * *"
        await self._create_cron(interaction, cron, channel, message)

    @app_commands.command(name='weekly', description='毎週定時投稿を設定')
    @app_commands.describe(weekday='曜日 (月/火/水/木/金/土/日)', time='HH:MM', channel='投稿先チャンネル', message='投稿するメッセージ')
    async def weekly(self, interaction: discord.Interaction, weekday: str, time: str, channel: discord.TextChannel, message: str):
        if not require_admin(interaction):
            await interaction.response.send_message('このコマンドは管理者のみ実行できます。', ephemeral=True)
            return
        weekdays = {
            '月': 'mon', '火': 'tue', '水': 'wed', '木': 'thu', '金': 'fri', '土': 'sat', '日': 'sun',
        }
        if weekday not in weekdays:
            await interaction.response.send_message('曜日の指定が無効です。', ephemeral=True)
            return
        m = re.match(r"^(\d{2}):(\d{2})$", time)
        if not m:
            await interaction.response.send_message('時刻の形式が無効です。', ephemeral=True)
            return
        hh, mm = map(int, m.groups())
        dow = weekdays[weekday]
        cron = f"{mm} {hh} * * {dow}"
        await self._create_cron(interaction, cron, channel, message)

    async def _create_cron(self, interaction: discord.Interaction, cron: str, channel: discord.TextChannel, message: str):
        if not (1 <= len(message) <= 1800):
            await interaction.response.send_message('メッセージ長が不正です。', ephemeral=True)
            return

        schedule_id = uuid.uuid4().hex[:8]

        async def post_message(ch_id: int, content: str):
            ch = self.bot.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(content)
                except discord.Forbidden:
                    log.warning('権限不足で投稿できません: channel=%s', ch_id)
                except Exception:
                    log.exception('投稿中にエラーが発生しました')

        self.bot.scheduler.add_cron(
            schedule_id,
            cron,
            lambda ch_id=channel.id, content=message: asyncio.create_task(post_message(ch_id, content))
        )

        self.bot.storage.upsert(ScheduleRecord(
            id=schedule_id,
            channel_id=channel.id,
            content=message,
            type='cron',
            cron=cron,
        ))

        await interaction.response.send_message(f'定期投稿を設定しました: ID={schedule_id} cron="{cron}"', ephemeral=True)


def register_app_commands(bot: commands.Bot) -> None:
    bot.tree.add_command(ScheduleGroup(bot))
    bot.tree.add_command(RepeatGroup(bot))


