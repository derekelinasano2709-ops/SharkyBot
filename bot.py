# ============================================================
# SHARKY MEGALODON
# Version: 1.0
# Discord.py 2.x | Python 3.13+
# ============================================================

import os
import re
import io
import json
import time
import random
import sqlite3
import asyncio
import discord

from datetime import datetime, timedelta, timezone
from discord import app_commands
from discord.ext import commands

# ============================================================
# CONFIGURATION
# ============================================================

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

if not TOKEN:
    raise RuntimeError(
        "Missing DISCORD_TOKEN environment variable. "
        "Configure your Discord bot token in your hosting panel."
    )

DB_PATH = "sharky.db"

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

START_TIME = time.time()

COLOR_MAIN = discord.Color.from_rgb(25, 105, 210)
COLOR_SUCCESS = discord.Color.from_rgb(46, 204, 113)
COLOR_WARNING = discord.Color.from_rgb(241, 196, 15)
COLOR_ERROR = discord.Color.from_rgb(231, 76, 60)
COLOR_DARK = discord.Color.from_rgb(35, 39, 42)

# ============================================================
# DATABASE
# ============================================================

def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_database():
    with db_connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY,
                language TEXT DEFAULT 'en',
                log_channel INTEGER,
                raid_mode INTEGER DEFAULT 0,
                anti_link INTEGER DEFAULT 0,
                anti_spam INTEGER DEFAULT 0,
                automod INTEGER DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS filters (
                guild_id INTEGER NOT NULL,
                phrase TEXT NOT NULL,
                PRIMARY KEY (guild_id, phrase)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS modlogs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                target_id INTEGER,
                action TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS role_buttons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                label TEXT NOT NULL
            )
        """)


def ensure_guild(guild_id: int):
    with db_connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)",
            (guild_id,)
        )


def get_config(guild_id: int):
    ensure_guild(guild_id)

    with db_connect() as conn:
        row = conn.execute(
            "SELECT * FROM guild_config WHERE guild_id = ?",
            (guild_id,)
        ).fetchone()

    return dict(row)


def set_config(guild_id: int, key: str, value):
    allowed = {
        "language",
        "log_channel",
        "raid_mode",
        "anti_link",
        "anti_spam",
        "automod"
    }

    if key not in allowed:
        raise ValueError("Invalid configuration key")

    ensure_guild(guild_id)

    with db_connect() as conn:
        conn.execute(
            f"UPDATE guild_config SET {key} = ? WHERE guild_id = ?",
            (value, guild_id)
        )


def save_modlog(guild_id, moderator_id, target_id, action, reason):
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO modlogs
            (guild_id, moderator_id, target_id, action, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            guild_id,
            moderator_id,
            target_id,
            action,
            reason,
            datetime.now(timezone.utc).isoformat()
        ))


def add_warning(guild_id, user_id, moderator_id, reason):
    with db_connect() as conn:
        conn.execute("""
            INSERT INTO warnings
            (guild_id, user_id, moderator_id, reason, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            guild_id,
            user_id,
            moderator_id,
            reason,
            datetime.now(timezone.utc).isoformat()
        ))


# ============================================================
# TRANSLATIONS
# ============================================================

TEXTS = {
    "en": {
        "success": "Operation completed successfully.",
        "error": "An error occurred.",
        "no_permission": "You do not have permission to do that.",
        "not_found": "The requested item was not found.",
        "reason": "Reason",
        "moderator": "Moderator",
        "target": "Target",
        "footer": "Sharky Megalodon • Server Management",
        "warning": "Warning",
        "language_changed": "Language changed to English.",
        "not_guild": "This command can only be used in a server."
    },
    "es": {
        "success": "Operación completada correctamente.",
        "error": "Se produjo un error.",
        "no_permission": "No tienes permiso para realizar esta acción.",
        "not_found": "No se encontró el elemento solicitado.",
        "reason": "Motivo",
        "moderator": "Moderador",
        "target": "Objetivo",
        "footer": "Sharky Megalodon • Administración del servidor",
        "warning": "Advertencia",
        "language_changed": "El idioma se cambió a español.",
        "not_guild": "Este comando solo se puede usar en un servidor."
    },
    "fr": {
        "success": "Opération terminée avec succès.",
        "error": "Une erreur est survenue.",
        "no_permission": "Vous n'avez pas la permission.",
        "not_found": "Élément introuvable.",
        "reason": "Raison",
        "moderator": "Modérateur",
        "target": "Cible",
        "footer": "Sharky Megalodon • Gestion du serveur",
        "warning": "Avertissement",
        "language_changed": "La langue est maintenant le français.",
        "not_guild": "Cette commande doit être utilisée sur un serveur."
    },
    "pt": {
        "success": "Operação concluída com sucesso.",
        "error": "Ocorreu um erro.",
        "no_permission": "Você não tem permissão para isso.",
        "not_found": "O item solicitado não foi encontrado.",
        "reason": "Motivo",
        "moderator": "Moderador",
        "target": "Alvo",
        "footer": "Sharky Megalodon • Administração do servidor",
        "warning": "Aviso",
        "language_changed": "O idioma foi alterado para português.",
        "not_guild": "Este comando só pode ser usado em um servidor."
    }
}


def tr(guild_id: int, key: str):
    language = get_config(guild_id).get("language", "en")
    language = language if language in TEXTS else "en"
    return TEXTS[language].get(key, TEXTS["en"].get(key, key))


# ============================================================
# EMBEDS AND HELPERS
# ============================================================

def make_embed(title, description="", color=COLOR_MAIN):
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="🦈 Sharky Megalodon")
    return embed


def success_embed(title, description):
    return make_embed(
        f"✅ {title}",
        description,
        COLOR_SUCCESS
    )


def error_embed(description):
    return make_embed(
        "❌ Error",
        description,
        COLOR_ERROR
    )


def is_guild(interaction: discord.Interaction):
    return interaction.guild is not None


def log_action(guild, moderator, target, action, reason):
    save_modlog(
        guild.id,
        moderator.id,
        target.id if target else None,
        action,
        reason
    )


async def send_log(guild, title, description, color=COLOR_MAIN):
    config = get_config(guild.id)
    channel_id = config.get("log_channel")

    if not channel_id:
        return

    channel = guild.get_channel(channel_id)

    if not isinstance(channel, discord.TextChannel):
        return

    try:
        await channel.send(
            embed=make_embed(title, description, color)
        )
    except discord.HTTPException:
        pass


def hierarchy_error(guild, moderator, target, bot_member):
    if target.id == moderator.id:
        return "You cannot perform this action on yourself."

    if target.id == guild.owner_id:
        return "You cannot perform this action on the server owner."

    if moderator.id != guild.owner_id:
        if target.top_role >= moderator.top_role:
            return "The target's highest role must be below yours."

    if target.top_role >= bot_member.top_role:
        return "The target's highest role must be below Sharky's role."

    return None


# ============================================================
# INTERACTIVE CONFIRMATION
# ============================================================

class ConfirmView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=30)
        self.author_id = author_id
        self.confirmed = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This confirmation belongs to another moderator.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="Confirm",
        style=discord.ButtonStyle.danger,
        emoji="🔨"
    )
    async def confirm(self, interaction, button):
        self.confirmed = True
        self.stop()

        await interaction.response.edit_message(
            content="✅ Action confirmed.",
            view=None
        )

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="✖️"
    )
    async def cancel(self, interaction, button):
        self.confirmed = False
        self.stop()

        await interaction.response.edit_message(
            content="Action cancelled.",
            view=None
        )


# ============================================================
# COMMANDS 1–5: BAN, UNBAN, KICK, TIMEOUT
# ============================================================

@bot.tree.command(name="ban", description="Ban a member from this server.")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.describe(
    member="Member to ban",
    reason="Reason for the ban",
    delete_days="Days of recent messages to delete (0–7)"
)
async def ban(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided",
    delete_days: app_commands.Range[int, 0, 7] = 0
):
    if not is_guild(interaction):
        return await interaction.response.send_message(
            "Use this command in a server.",
            ephemeral=True
        )

    guild = interaction.guild
    bot_member = guild.me

    problem = hierarchy_error(
        guild, interaction.user, member, bot_member
    )

    if problem:
        return await interaction.response.send_message(
            embed=error_embed(problem),
            ephemeral=True
        )

    view = ConfirmView(interaction.user.id)

    await interaction.response.send_message(
        embed=make_embed(
            "🔨 Confirm Ban",
            f"**Member:** {member.mention}\n"
            f"**Reason:** {reason}\n"
            f"**Delete message history:** {delete_days} day(s)\n\n"
            "Confirm this moderation action?"
        ),
        view=view,
        ephemeral=True
    )

    await view.wait()

    if not view.confirmed:
        return

    try:
        await member.ban(
            reason=f"{reason} | Moderator: {interaction.user}",
            delete_message_seconds=delete_days * 86400
        )

        log_action(guild, interaction.user, member, "BAN", reason)

        await send_log(
            guild,
            "🔨 Member Banned",
            f"**Member:** {member} (`{member.id}`)\n"
            f"**Moderator:** {interaction.user.mention}\n"
            f"**Reason:** {reason}",
            COLOR_ERROR
        )

    except discord.HTTPException as exc:
        await interaction.followup.send(
            embed=error_embed(f"Discord rejected the ban: {exc}"),
            ephemeral=True
        )


@bot.tree.command(name="unban", description="Unban a user by their ID.")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.describe(
    user_id="Discord user ID",
    reason="Reason for the unban"
)
async def unban(
    interaction: discord.Interaction,
    user_id: str,
    reason: str = "No reason provided"
):
    if not user_id.isdigit():
        return await interaction.response.send_message(
            embed=error_embed("The user ID must contain digits only."),
            ephemeral=True
        )

    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(
            user,
            reason=f"{reason} | Moderator: {interaction.user}"
        )

        log_action(
            interaction.guild, interaction.user, user, "UNBAN", reason
        )

        await interaction.response.send_message(
            embed=success_embed(
                "User Unbanned",
                f"**User:** {user.mention}\n**Reason:** {reason}"
            )
        )

    except discord.NotFound:
        await interaction.response.send_message(
            embed=error_embed("That user is not banned or does not exist."),
            ephemeral=True
        )
    except discord.HTTPException as exc:
        await interaction.response.send_message(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


@bot.tree.command(name="kick", description="Kick a member from the server.")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):
    guild = interaction.guild

    problem = hierarchy_error(
        guild, interaction.user, member, guild.me
    )

    if problem:
        return await interaction.response.send_message(
            embed=error_embed(problem),
            ephemeral=True
        )

    try:
        await member.kick(
            reason=f"{reason} | Moderator: {interaction.user}"
        )

        log_action(guild, interaction.user, member, "KICK", reason)

        await interaction.response.send_message(
            embed=success_embed(
                "Member Kicked",
                f"**Member:** {member}\n**Reason:** {reason}"
            )
        )

        await send_log(
            guild,
            "👢 Member Kicked",
            f"**Member:** {member}\n"
            f"**Moderator:** {interaction.user.mention}\n"
            f"**Reason:** {reason}",
            COLOR_WARNING
        )

    except discord.HTTPException as exc:
        await interaction.response.send_message(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


@bot.tree.command(name="timeout", description="Temporarily timeout a member.")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.describe(
    member="Member to timeout",
    minutes="Timeout duration in minutes",
    reason="Reason for the timeout"
)
async def timeout(
    interaction: discord.Interaction,
    member: discord.Member,
    minutes: app_commands.Range[int, 1, 40320],
    reason: str = "No reason provided"
):
    guild = interaction.guild

    problem = hierarchy_error(
        guild, interaction.user, member, guild.me
    )

    if problem:
        return await interaction.response.send_message(
            embed=error_embed(problem),
            ephemeral=True
        )

    try:
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)

        await member.timeout(
            until,
            reason=f"{reason} | Moderator: {interaction.user}"
        )

        log_action(
            guild, interaction.user, member, "TIMEOUT", reason
        )

        await interaction.response.send_message(
            embed=success_embed(
                "Member Timed Out",
                f"**Member:** {member.mention}\n"
                f"**Duration:** {minutes} minutes\n"
                f"**Reason:** {reason}"
            )
        )

        await send_log(
            guild,
            "🔇 Timeout Applied",
            f"**Member:** {member.mention}\n"
            f"**Duration:** {minutes} minutes\n"
            f"**Reason:** {reason}",
            COLOR_WARNING
        )

    except discord.HTTPException as exc:
        await interaction.response.send_message(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


@bot.tree.command(name="untimeout", description="Remove a member's timeout.")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str = "No reason provided"
):
    guild = interaction.guild

    problem = hierarchy_error(
        guild, interaction.user, member, guild.me
    )

    if problem:
        return await interaction.response.send_message(
            embed=error_embed(problem),
            ephemeral=True
        )

    try:
        await member.timeout(
            None,
            reason=f"{reason} | Moderator: {interaction.user}"
        )

        log_action(
            guild, interaction.user, member, "UNTIMEOUT", reason
        )

        await interaction.response.send_message(
            embed=success_embed(
                "Timeout Removed",
                f"Timeout removed from {member.mention}.\n"
                f"**Reason:** {reason}"
            )
        )

    except discord.HTTPException as exc:
        await interaction.response.send_message(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


# ============================================================
# COMMANDS 6–8: WARNINGS
# ============================================================

@bot.tree.command(name="warn", description="Issue a formal warning.")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(
    interaction: discord.Interaction,
    member: discord.Member,
    reason: str
):
    if member.id == interaction.user.id:
        return await interaction.response.send_message(
            embed=error_embed("You cannot warn yourself."),
            ephemeral=True
        )

    add_warning(
        interaction.guild.id,
        member.id,
        interaction.user.id,
        reason
    )

    log_action(
        interaction.guild, interaction.user, member, "WARN", reason
    )

    with db_connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM warnings "
            "WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, member.id)
        ).fetchone()[0]

    await interaction.response.send_message(
        embed=make_embed(
            "⚠️ Warning Issued",
            f"**Member:** {member.mention}\n"
            f"**Reason:** {reason}\n"
            f"**Total warnings:** {count}",
            COLOR_WARNING
        )
    )

    await send_log(
        interaction.guild,
        "⚠️ Warning Issued",
        f"**Member:** {member.mention}\n"
        f"**Moderator:** {interaction.user.mention}\n"
        f"**Reason:** {reason}\n"
        f"**Total warnings:** {count}",
        COLOR_WARNING
    )


@bot.tree.command(name="warnings", description="View a member's warnings.")
@app_commands.checks.has_permissions(moderate_members=True)
async def warnings(
    interaction: discord.Interaction,
    member: discord.Member
):
    with db_connect() as conn:
        rows = conn.execute("""
            SELECT id, moderator_id, reason, created_at
            FROM warnings
            WHERE guild_id = ? AND user_id = ?
            ORDER BY id DESC
            LIMIT 15
        """, (interaction.guild.id, member.id)).fetchall()

    embed = make_embed(
        f"⚠️ Warnings: {member}",
        f"Showing up to 15 most recent warnings.\n"
        f"**Total shown:** {len(rows)}",
        COLOR_WARNING
    )

    if not rows:
        embed.description = "This member has no recorded warnings."
    else:
        for row in rows:
            embed.add_field(
                name=f"Warning #{row['id']}",
                value=(
                    f"**Reason:** {row['reason'][:500]}\n"
                    f"**Moderator ID:** {row['moderator_id']}\n"
                    f"**Date:** {row['created_at'][:10]}"
                ),
                inline=False
            )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


@bot.tree.command(name="clearwarns", description="Clear all warnings for a member.")
@app_commands.checks.has_permissions(moderate_members=True)
async def clearwarns(
    interaction: discord.Interaction,
    member: discord.Member
):
    view = ConfirmView(interaction.user.id)

    await interaction.response.send_message(
        embed=make_embed(
            "🧹 Clear Warnings",
            f"Remove all stored warnings for {member.mention}?"
        ),
        view=view,
        ephemeral=True
    )

    await view.wait()

    if not view.confirmed:
        return

    with db_connect() as conn:
        conn.execute(
            "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
            (interaction.guild.id, member.id)
        )

    log_action(
        interaction.guild,
        interaction.user,
        member,
        "CLEAR_WARNINGS",
        "All warnings cleared"
    )

    await interaction.followup.send(
        embed=success_embed(
            "Warnings Cleared",
            f"All warnings for {member.mention} have been removed."
        ),
        ephemeral=True
    )


# ============================================================
# COMMAND 9: PURGE
# ============================================================

@bot.tree.command(name="purge", description="Delete recent messages in a channel.")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(
    amount="Number of messages to delete (1–100)"
)
async def purge(
    interaction: discord.Interaction,
    amount: app_commands.Range[int, 1, 100]
):
    channel = interaction.channel

    if not isinstance(channel, discord.TextChannel):
        return await interaction.response.send_message(
            embed=error_embed("Use this command in a text channel."),
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)

    try:
        deleted = await channel.purge(
            limit=amount,
            reason=f"Purged by {interaction.user}"
        )

        log_action(
            interaction.guild,
            interaction.user,
            None,
            "PURGE",
            f"Deleted {len(deleted)} messages in #{channel.name}"
        )

        await interaction.followup.send(
            embed=success_embed(
                "Messages Deleted",
                f"Deleted **{len(deleted)}** messages in {channel.mention}."
            ),
            ephemeral=True
        )

    except discord.HTTPException as exc:
        await interaction.followup.send(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


# ============================================================
# COMMAND 10: MODLOGS
# ============================================================

@bot.tree.command(name="modlogs", description="View recent moderation actions.")
@app_commands.checks.has_permissions(view_audit_log=True)
async def modlogs(
    interaction: discord.Interaction,
    limit: app_commands.Range[int, 1, 15] = 10
):
    with db_connect() as conn:
        rows = conn.execute("""
            SELECT moderator_id, target_id, action, reason, created_at
            FROM modlogs
            WHERE guild_id = ?
            ORDER BY id DESC
            LIMIT ?
        """, (interaction.guild.id, limit)).fetchall()

    embed = make_embed(
        "📋 Moderation Logs",
        f"Most recent {len(rows)} stored actions."
    )

    if not rows:
        embed.description = "No moderation actions have been recorded."
    else:
        for row in rows:
            target = (
                f"<@{row['target_id']}>"
                if row["target_id"]
                else "Not applicable"
            )

            embed.add_field(
                name=f"🛡️ {row['action']}",
                value=(
                    f"**Target:** {target}\n"
                    f"**Moderator:** <@{row['moderator_id']}>\n"
                    f"**Reason:** {(row['reason'] or 'None')[:200]}\n"
                    f"**Date:** {row['created_at'][:10]}"
                ),
                inline=False
            )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ============================================================
# COMMANDS 11–13: AUTOMOD, ANTISPAM, ANTILINK
# ============================================================

@bot.tree.command(name="automod", description="Enable or disable basic automod.")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.choices(
    state=[
        app_commands.Choice(name="Enable", value="on"),
        app_commands.Choice(name="Disable", value="off")
    ]
)
async def automod(
    interaction: discord.Interaction,
    state: app_commands.Choice[str]
):
    enabled = 1 if state.value == "on" else 0

    set_config(interaction.guild.id, "automod", enabled)

    await interaction.response.send_message(
        embed=success_embed(
            "Automod Updated",
            f"Basic automod is now **{'enabled' if enabled else 'disabled'}**."
        )
    )


@bot.tree.command(name="antispam", description="Toggle Sharky's basic anti-spam filter.")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.choices(
    state=[
        app_commands.Choice(name="Enable", value="on"),
        app_commands.Choice(name="Disable", value="off")
    ]
)
async def antispam(
    interaction: discord.Interaction,
    state: app_commands.Choice[str]
):
    enabled = 1 if state.value == "on" else 0

    set_config(interaction.guild.id, "anti_spam", enabled)

    await interaction.response.send_message(
        embed=success_embed(
            "Anti-Spam Updated",
            f"Anti-spam is now **{'enabled' if enabled else 'disabled'}**."
        )
    )


@bot.tree.command(name="antilink", description="Toggle basic link filtering.")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.choices(
    state=[
        app_commands.Choice(name="Enable", value="on"),
        app_commands.Choice(name="Disable", value="off")
    ]
)
async def antilink(
    interaction: discord.Interaction,
    state: app_commands.Choice[str]
):
    enabled = 1 if state.value == "on" else 0

    set_config(interaction.guild.id, "anti_link", enabled)

    await interaction.response.send_message(
        embed=success_embed(
            "Anti-Link Updated",
            f"Anti-link filtering is now **{'enabled' if enabled else 'disabled'}**."
        )
    )


# ============================================================
# COMMANDS 14–15: FILTER MANAGEMENT
# ============================================================

@bot.tree.command(name="filteradd", description="Add a phrase to the server filter.")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(phrase="Phrase to filter")
async def filteradd(
    interaction: discord.Interaction,
    phrase: app_commands.Range[str, 1, 100]
):
    phrase = phrase.strip().casefold()

    if not phrase:
        return await interaction.response.send_message(
            embed=error_embed("The phrase cannot be empty."),
            ephemeral=True
        )

    try:
        with db_connect() as conn:
            conn.execute(
                "INSERT INTO filters (guild_id, phrase) VALUES (?, ?)",
                (interaction.guild.id, phrase)
            )

        await interaction.response.send_message(
            embed=success_embed(
                "Filter Added",
                f"The phrase `{phrase}` has been added to the filter list."
            )
        )

    except sqlite3.IntegrityError:
        await interaction.response.send_message(
            embed=error_embed("That phrase is already in the filter list."),
            ephemeral=True
        )


@bot.tree.command(name="filterremove", description="Remove a phrase from the server filter.")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(phrase="Phrase to remove")
async def filterremove(
    interaction: discord.Interaction,
    phrase: app_commands.Range[str, 1, 100]
):
    phrase = phrase.strip().casefold()

    with db_connect() as conn:
        cursor = conn.execute(
            "DELETE FROM filters WHERE guild_id = ? AND phrase = ?",
            (interaction.guild.id, phrase)
        )

    if cursor.rowcount == 0:
        return await interaction.response.send_message(
            embed=error_embed("That phrase is not in the filter list."),
            ephemeral=True
        )

    await interaction.response.send_message(
        embed=success_embed(
            "Filter Removed",
            f"The phrase `{phrase}` has been removed."
        )
    ) 
# ============================================================
# COMMAND 16: FILTERLIST
# ============================================================

@bot.tree.command(
    name="filterlist",
    description="Display the server's filtered phrases."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def filterlist(interaction: discord.Interaction):
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT phrase FROM filters WHERE guild_id = ? ORDER BY phrase",
            (interaction.guild.id,)
        ).fetchall()

    embed = make_embed(
        "🛡️ Filter List",
        f"Configured filtered phrases: **{len(rows)}**"
    )

    if rows:
        embed.description += "\n\n" + "\n".join(
            f"• `{row['phrase']}`" for row in rows[:40]
        )
    else:
        embed.description += "\n\nNo filtered phrases have been configured."

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ============================================================
# COMMAND 17: RAIDMODE
# ============================================================

@bot.tree.command(
    name="raidmode",
    description="Enable or disable server raid mode."
)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.choices(
    state=[
        app_commands.Choice(name="Enable", value="on"),
        app_commands.Choice(name="Disable", value="off")
    ]
)
async def raidmode(
    interaction: discord.Interaction,
    state: app_commands.Choice[str]
):
    enabled = 1 if state.value == "on" else 0

    set_config(interaction.guild.id, "raid_mode", enabled)

    embed = make_embed(
        "🚨 Raid Mode Updated",
        (
            "Raid mode is now **ENABLED**.\n"
            "New members will be subject to additional checks."
            if enabled
            else
            "Raid mode is now **DISABLED**."
        ),
        COLOR_WARNING if enabled else COLOR_SUCCESS
    )

    await interaction.response.send_message(embed=embed)

    await send_log(
        interaction.guild,
        "🚨 Raid Mode Changed",
        f"Changed by {interaction.user.mention}.\n"
        f"Status: **{'Enabled' if enabled else 'Disabled'}**"
    )


# ============================================================
# COMMAND 18: SECURITY
# ============================================================

@bot.tree.command(
    name="security",
    description="View the server's security configuration."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def security(interaction: discord.Interaction):
    config = get_config(interaction.guild.id)

    def status(value):
        return "🟢 Enabled" if value else "🔴 Disabled"

    embed = make_embed(
        "🛡️ Sharky Security Center",
        "Current security configuration for this server."
    )

    embed.add_field(
        name="🚨 Raid Mode",
        value=status(config["raid_mode"]),
        inline=True
    )

    embed.add_field(
        name="🔗 Anti-Link",
        value=status(config["anti_link"]),
        inline=True
    )

    embed.add_field(
        name="💬 Anti-Spam",
        value=status(config["anti_spam"]),
        inline=True
    )

    embed.add_field(
        name="🤖 AutoMod",
        value=status(config["automod"]),
        inline=True
    )

    log_channel = interaction.guild.get_channel(
        config["log_channel"]
    ) if config["log_channel"] else None

    embed.add_field(
        name="📋 Log Channel",
        value=log_channel.mention if log_channel else "Not configured",
        inline=True
    )

    embed.add_field(
        name="🌎 Language",
        value=config["language"],
        inline=True
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )


# ============================================================
# COMMANDS 19–20: LOCK AND UNLOCK
# ============================================================

@bot.tree.command(
    name="lock",
    description="Prevent members from sending messages in a channel."
)
@app_commands.checks.has_permissions(manage_channels=True)
async def lock(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None,
    reason: str = "No reason provided"
):
    channel = channel or interaction.channel

    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False

    try:
        await channel.set_permissions(
            interaction.guild.default_role,
            overwrite=overwrite,
            reason=f"{reason} | Locked by {interaction.user}"
        )

        log_action(
            interaction.guild,
            interaction.user,
            None,
            "LOCK_CHANNEL",
            f"#{channel.name}: {reason}"
        )

        await interaction.response.send_message(
            embed=success_embed(
                "🔒 Channel Locked",
                f"{channel.mention} is now locked.\n**Reason:** {reason}"
            )
        )

        await send_log(
            interaction.guild,
            "🔒 Channel Locked",
            f"**Channel:** {channel.mention}\n"
            f"**Moderator:** {interaction.user.mention}\n"
            f"**Reason:** {reason}"
        )

    except discord.HTTPException as exc:
        await interaction.response.send_message(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


@bot.tree.command(
    name="unlock",
    description="Restore the default message permission in a channel."
)
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None
):
    channel = channel or interaction.channel

    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None

    try:
        await channel.set_permissions(
            interaction.guild.default_role,
            overwrite=overwrite,
            reason=f"Unlocked by {interaction.user}"
        )

        log_action(
            interaction.guild,
            interaction.user,
            None,
            "UNLOCK_CHANNEL",
            f"#{channel.name}"
        )

        await interaction.response.send_message(
            embed=success_embed(
                "🔓 Channel Unlocked",
                f"Default message permissions were restored for {channel.mention}."
            )
        )

    except discord.HTTPException as exc:
        await interaction.response.send_message(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


# ============================================================
# COMMAND 21: SLOWMODE
# ============================================================

@bot.tree.command(
    name="slowmode",
    description="Configure a channel's slowmode."
)
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.describe(
    seconds="Delay between messages, from 0 to 21600 seconds",
    channel="Channel to configure"
)
async def slowmode(
    interaction: discord.Interaction,
    seconds: app_commands.Range[int, 0, 21600],
    channel: discord.TextChannel = None
):
    channel = channel or interaction.channel

    try:
        await channel.edit(
            slowmode_delay=seconds,
            reason=f"Slowmode configured by {interaction.user}"
        )

        await interaction.response.send_message(
            embed=success_embed(
                "⏱️ Slowmode Updated",
                f"**Channel:** {channel.mention}\n"
                f"**Delay:** {seconds} second(s)"
            )
        )

        log_action(
            interaction.guild,
            interaction.user,
            None,
            "SLOWMODE",
            f"#{channel.name}: {seconds} seconds"
        )

    except discord.HTTPException as exc:
        await interaction.response.send_message(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


# ============================================================
# COMMAND 22: ROLE
# ============================================================

@bot.tree.command(
    name="role",
    description="Add or remove a role from a member."
)
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.choices(
    action=[
        app_commands.Choice(name="Add role", value="add"),
        app_commands.Choice(name="Remove role", value="remove")
    ]
)
async def role(
    interaction: discord.Interaction,
    member: discord.Member,
    selected_role: discord.Role,
    action: app_commands.Choice[str],
    reason: str = "No reason provided"
):
    guild = interaction.guild

    if selected_role.is_default():
        return await interaction.response.send_message(
            embed=error_embed("You cannot assign or remove the @everyone role."),
            ephemeral=True
        )

    if selected_role.managed:
        return await interaction.response.send_message(
            embed=error_embed("That role is managed by an integration or bot."),
            ephemeral=True
        )

    if selected_role >= guild.me.top_role:
        return await interaction.response.send_message(
            embed=error_embed("Sharky's highest role must be above that role."),
            ephemeral=True
        )

    if interaction.user.id != guild.owner_id:
        if selected_role >= interaction.user.top_role:
            return await interaction.response.send_message(
                embed=error_embed("Your highest role must be above the selected role."),
                ephemeral=True
            )

    try:
        if action.value == "add":
            await member.add_roles(
                selected_role,
                reason=f"{reason} | By {interaction.user}"
            )
            action_text = "added to"
        else:
            await member.remove_roles(
                selected_role,
                reason=f"{reason} | By {interaction.user}"
            )
            action_text = "removed from"

        log_action(
            guild,
            interaction.user,
            member,
            f"ROLE_{action.value.upper()}",
            f"{selected_role.name}: {reason}"
        )

        await interaction.response.send_message(
            embed=success_embed(
                "Role Updated",
                f"Role **{selected_role.name}** {action_text} "
                f"{member.mention}.\n**Reason:** {reason}"
            )
        )

    except discord.HTTPException as exc:
        await interaction.response.send_message(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


# ============================================================
# COMMAND 23: NICK
# ============================================================

@bot.tree.command(
    name="nick",
    description="Change or reset a member's nickname."
)
@app_commands.checks.has_permissions(manage_nicknames=True)
@app_commands.describe(
    member="Member whose nickname will change",
    nickname="New nickname; leave empty to reset"
)
async def nick(
    interaction: discord.Interaction,
    member: discord.Member,
    nickname: app_commands.Range[str, 1, 32] = None
):
    if member.id == interaction.guild.owner_id:
        return await interaction.response.send_message(
            embed=error_embed("The server owner's nickname cannot be changed by this command."),
            ephemeral=True
        )

    if member.top_role >= interaction.guild.me.top_role:
        return await interaction.response.send_message(
            embed=error_embed("Sharky's highest role must be above the target."),
            ephemeral=True
        )

    if interaction.user.id != interaction.guild.owner_id:
        if member.top_role >= interaction.user.top_role:
            return await interaction.response.send_message(
                embed=error_embed("The target's highest role must be below yours."),
                ephemeral=True
            )

    try:
        await member.edit(
            nick=nickname,
            reason=f"Nickname updated by {interaction.user}"
        )

        shown_name = nickname if nickname else member.name

        await interaction.response.send_message(
            embed=success_embed(
                "Nickname Updated",
                f"Nickname operation completed for {member.mention}.\n"
                f"**New nickname:** {shown_name}"
            )
        )

        log_action(
            interaction.guild,
            interaction.user,
            member,
            "NICKNAME",
            f"Nickname set to {nickname or 'reset'}"
        )

    except discord.HTTPException as exc:
        await interaction.response.send_message(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


# ============================================================
# COMMANDS 24–25: HIDE AND UNHIDE
# ============================================================

@bot.tree.command(
    name="hide",
    description="Hide a text channel from the default role."
)
@app_commands.checks.has_permissions(manage_channels=True)
async def hide(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None
):
    channel = channel or interaction.channel

    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.view_channel = False

    try:
        await channel.set_permissions(
            interaction.guild.default_role,
            overwrite=overwrite,
            reason=f"Channel hidden by {interaction.user}"
        )

        await interaction.response.send_message(
            embed=success_embed(
                "👁️ Channel Hidden",
                f"{channel.mention} is now hidden from the default role."
            ),
            ephemeral=True
        )

    except discord.HTTPException as exc:
        await interaction.response.send_message(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


@bot.tree.command(
    name="unhide",
    description="Restore the default role's channel visibility."
)
@app_commands.checks.has_permissions(manage_channels=True)
async def unhide(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None
):
    channel = channel or interaction.channel

    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.view_channel = None

    try:
        await channel.set_permissions(
            interaction.guild.default_role,
            overwrite=overwrite,
            reason=f"Channel visibility restored by {interaction.user}"
        )

        await interaction.response.send_message(
            embed=success_embed(
                "👁️ Channel Visible",
                f"Default visibility permissions were restored for {channel.mention}."
            ),
            ephemeral=True
        )

    except discord.HTTPException as exc:
        await interaction.response.send_message(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


# ============================================================
# COMMAND 26: ANNOUNCE
# ============================================================

@bot.tree.command(
    name="announce",
    description="Publish a professional announcement embed."
)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(
    title="Announcement title",
    message="Announcement text",
    channel="Channel where the announcement will be posted"
)
async def announce(
    interaction: discord.Interaction,
    title: app_commands.Range[str, 1, 200],
    message: app_commands.Range[str, 1, 3500],
    channel: discord.TextChannel = None
):
    channel = channel or interaction.channel

    embed = make_embed(
        f"📢 {title}",
        message,
        COLOR_MAIN
    )

    embed.set_author(
        name=interaction.guild.name,
        icon_url=interaction.guild.icon.url
        if interaction.guild.icon else discord.Embed.Empty
    )

    embed.add_field(
        name="Published by",
        value=interaction.user.mention,
        inline=False
    )

    try:
        await channel.send(embed=embed)

        await interaction.response.send_message(
            embed=success_embed(
                "Announcement Published",
                f"Your announcement was published in {channel.mention}."
            ),
            ephemeral=True
        )

    except discord.HTTPException as exc:
        await interaction.response.send_message(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


# ============================================================
# COMMAND 27: EMBED
# ============================================================

@bot.tree.command(
    name="embed",
    description="Create a custom embed message."
)
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(
    title="Embed title",
    description="Embed description",
    channel="Destination channel"
)
async def embed_command(
    interaction: discord.Interaction,
    title: app_commands.Range[str, 1, 200],
    description: app_commands.Range[str, 1, 3500],
    channel: discord.TextChannel = None
):
    channel = channel or interaction.channel

    custom_embed = make_embed(title, description, COLOR_MAIN)

    try:
        await channel.send(embed=custom_embed)

        await interaction.response.send_message(
            embed=success_embed(
                "Embed Sent",
                f"Your embed was sent to {channel.mention}."
            ),
            ephemeral=True
        )

    except discord.HTTPException as exc:
        await interaction.response.send_message(
            embed=error_embed(str(exc)),
            ephemeral=True
        )


# ============================================================
# COMMAND 28: POLL
# ============================================================

class PollView(discord.ui.View):
    def __init__(self, question, options, author_id):
        super().__init__(timeout=86400)
        self.question = question
        self.options = options
        self.author_id = author_id
        self.votes = {}
        self.message = None

        for index, option in enumerate(options):
            button = discord.ui.Button(
                label=option[:80],
                style=discord.ButtonStyle.primary,
                custom_id=f"sharky_poll_{index}",
                row=index // 2
            )

            button.callback = self.make_callback(index)
            self.add_item(button)

    def make_callback(self, index):
        async def callback(interaction: discord.Interaction):
            self.votes[interaction.user.id] = index

            counts = [
                sum(1 for vote in self.votes.values() if vote == i)
                for i in range(len(self.options))
            ]

            embed = make_embed(
                f"📊 {self.question}",
                "Select an option to vote. You can change your vote."
            )

            total = sum(counts)

            for i, option in enumerate(self.options):
                percentage = counts[i] / total * 100 if total else 0

                embed.add_field(
                    name=f"{i + 1}. {option}",
                    value=f"**{counts[i]} vote(s)** • {percentage:.1f}%",
                    inline=False
                )

            embed.set_footer(text=f"Total votes: {total}")

            await interaction.response.edit_message(
                embed=embed,
                view=self
            )

        return callback


@bot.tree.command(
    name="poll",
    description="Create an interactive poll with up to four options."
)
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(
    question="Poll question",
    option1="First option",
    option2="Second option",
    option3="Optional third option",
    option4="Optional fourth option"
)
async def poll(
    interaction: discord.Interaction,
    question: app_commands.Range[str, 1, 200],
    option1: app_commands.Range[str, 1, 80],
    option2: app_commands.Range[str, 1, 80],
    option3: app_commands.Range[str, 1, 80] = None,
    option4: app_commands.Range[str, 1, 80] = None
):
    options = [option1, option2]

    if option3:
        options.append(option3)

    if option4:
        options.append(option4)

    embed = make_embed(
        f"📊 {question}",
        "Click an option below to cast your vote."
    )

    for index, option in enumerate(options):
        embed.add_field(
            name=f"Option {index + 1}",
            value=option,
            inline=False
        )

    view = PollView(question, options, interaction.user.id)

    await interaction.response.send_message(
        f"📊 **New poll created by {interaction.user.mention}**"
    )

    message = await interaction.channel.send(
        embed=embed,
        view=view
    )

    view.message = message


# ============================================================
# COMMAND 29: REACTIONROLE
# ============================================================

class RoleSelectView(discord.ui.View):
    def __init__(self, role_id, guild_id):
        super().__init__(timeout=None)
        self.role_id = role_id
        self.guild_id = guild_id

    @discord.ui.button(
        label="Get / Remove Role",
        emoji="🎭",
        style=discord.ButtonStyle.primary,
        custom_id="sharky_role_toggle"
    )
    async def toggle_role(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if interaction.guild is None or interaction.guild.id != self.guild_id:
            return await interaction.response.send_message(
                "This role panel belongs to another server.",
                ephemeral=True
            )

        role_obj = interaction.guild.get_role(self.role_id)

        if role_obj is None:
            return await interaction.response.send_message(
                "That role no longer exists.",
                ephemeral=True
            )

        member = interaction.user

        if not isinstance(member, discord.Member):
            return await interaction.response.send_message(
                "This action is only available to server members.",
                ephemeral=True
            )

        if role_obj.is_default() or role_obj.managed:
            return await interaction.response.send_message(
                "This role cannot be assigned through this panel.",
                ephemeral=True
            )

        if role_obj >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                "Sharky's role must be above the selected role.",
                ephemeral=True
            )

        try:
            if role_obj in member.roles:
                await member.remove_roles(
                    role_obj,
                    reason="Self-service role panel"
                )
                result = f"Removed **{role_obj.name}**."
            else:
                await member.add_roles(
                    role_obj,
                    reason="Self-service role panel"
                )
                result = f"Assigned **{role_obj.name}**."

            await interaction.response.send_message(
                embed=success_embed("Role Updated", result),
                ephemeral=True
            )

        except discord.HTTPException as exc:
            await interaction.response.send_message(
                embed=error_embed(str(exc)),
                ephemeral=True
            )


@bot.tree.command(
    name="reactionrole",
    description="Create a button panel for a self-service role."
)
@app_commands.checks.has_permissions(manage_roles=True)
async def reactionrole(
    interaction: discord.Interaction,
    role: discord.Role,
    description: app_commands.Range[str, 1, 500] = "Click the button to get or remove this role."
):
    if role.is_default() or role.managed:
        return await interaction.response.send_message(
            embed=error_embed("That role cannot be used in a self-service panel."),
            ephemeral=True
        )

    if role >= interaction.guild.me.top_role:
        return await interaction.response.send_message(
            embed=error_embed("Sharky's highest role must be above the selected role."),
            ephemeral=True
        )

    embed = make_embed(
        "🎭 Self-Service Role",
        f"{description}\n\n**Role:** {role.mention}"
    )

    view = RoleSelectView(role.id, interaction.guild.id)

    await interaction.response.send_message(
        embed=success_embed(
            "Role Panel Created",
            f"Creating a self-service panel for {role.mention}."
        ),
        ephemeral=True
    )

    message = await interaction.channel.send(
        embed=embed,
        view=view
    )

    with db_connect() as conn:
        conn.execute("""
            INSERT INTO role_buttons
            (guild_id, message_id, channel_id, role_id, label)
            VALUES (?, ?, ?, ?, ?)
        """, (
            interaction.guild.id,
            message.id,
            interaction.channel.id,
            role.id,
            role.name
        ))


# ============================================================
# COMMAND 30: CONFIG
# ============================================================

@bot.tree.command(
    name="config",
    description="View Sharky's server configuration."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def config_command(interaction: discord.Interaction):
    configuration = get_config(interaction.guild.id)

    embed = make_embed(
        "⚙️ Sharky Configuration",
        f"Configuration for **{interaction.guild.name}**"
    )

    embed.add_field(
        name="🌎 Language",
        value=configuration["language"],
        inline=True
    )

    embed.add_field(
        name="📋 Logs",
        value=(
            f"<#{configuration['log_channel']}>"
            if configuration["log_channel"]
            else "Not configured"
        ),
        inline=True
    )

    embed.add_field(
        name="🚨 Raid Mode",
        value="Enabled" if configuration["raid_mode"] else "Disabled",
        inline=True
    )

    embed.add_field(
        name="🔗 Anti-Link",
        value="Enabled" if configuration["anti_link"] else "Disabled",
        inline=True
    )

    embed.add_field(
        name="💬 Anti-Spam",
        value="Enabled" if configuration["anti_spam"] else "Disabled",
        inline=True
    )

    embed.add_field(
        name="🤖 AutoMod",
        value="Enabled" if configuration["automod"] else "Disabled",
        inline=True
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True
    )
 # ============================================================
# COMMANDS 31–35: INFORMATION
# ============================================================

@bot.tree.command(
    name="serverinfo",
    description="Display detailed server information."
)
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild

    if guild is None:
        return await interaction.response.send_message(
            embed=error_embed("Use this command inside a server."),
            ephemeral=True
        )

    embed = make_embed(
        f"🌐 {guild.name}",
        guild.description or "Server information and statistics."
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(name="🆔 Server ID", value=str(guild.id), inline=True)
    embed.add_field(name="👥 Members", value=str(guild.member_count or 0), inline=True)
    embed.add_field(name="💬 Text Channels", value=str(len(guild.text_channels)), inline=True)
    embed.add_field(name="🔊 Voice Channels", value=str(len(guild.voice_channels)), inline=True)
    embed.add_field(name="🎭 Roles", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="🚀 Boost Level", value=str(guild.premium_tier), inline=True)

    embed.add_field(
        name="📅 Created",
        value=discord.utils.format_dt(guild.created_at, style="D"),
        inline=False
    )

    if guild.owner_id:
        embed.add_field(
            name="👑 Owner",
            value=f"<@{guild.owner_id}>",
            inline=True
        )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="userinfo",
    description="Display information about a server member."
)
async def userinfo(
    interaction: discord.Interaction,
    member: discord.Member = None
):
    member = member or interaction.user

    embed = make_embed(
        f"👤 {member}",
        f"Information about {member.mention}"
    )

    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(name="🆔 User ID", value=str(member.id), inline=True)
    embed.add_field(
        name="🤖 Bot",
        value="Yes" if member.bot else "No",
        inline=True
    )

    embed.add_field(
        name="📅 Account Created",
        value=discord.utils.format_dt(member.created_at, style="D"),
        inline=False
    )

    if member.joined_at:
        embed.add_field(
            name="📥 Joined Server",
            value=discord.utils.format_dt(member.joined_at, style="D"),
            inline=False
        )

    roles = [role.mention for role in reversed(member.roles) if not role.is_default()]

    embed.add_field(
        name=f"🎭 Roles ({len(roles)})",
        value=", ".join(roles[:15]) or "No roles",
        inline=False
    )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="avatar",
    description="Show a member's profile picture."
)
async def avatar(
    interaction: discord.Interaction,
    member: discord.Member = None
):
    member = member or interaction.user

    embed = make_embed(
        f"🖼️ {member.display_name}'s Avatar",
        f"[Open full-size avatar]({member.display_avatar.url})"
    )

    embed.set_image(url=member.display_avatar.url)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="roleinfo",
    description="Display information about a server role."
)
async def roleinfo(
    interaction: discord.Interaction,
    role: discord.Role
):
    embed = make_embed(
        f"🎭 Role: {role.name}",
        f"Information about {role.mention}"
    )

    embed.add_field(name="🆔 Role ID", value=str(role.id), inline=True)
    embed.add_field(name="👥 Members", value=str(len(role.members)), inline=True)
    embed.add_field(name="🎨 Color", value=str(role.color), inline=True)
    embed.add_field(name="📌 Hoisted", value="Yes" if role.hoist else "No", inline=True)
    embed.add_field(name="🔔 Mentionable", value="Yes" if role.mentionable else "No", inline=True)
    embed.add_field(name="🔐 Managed", value="Yes" if role.managed else "No", inline=True)

    embed.add_field(
        name="📅 Created",
        value=discord.utils.format_dt(role.created_at, style="D"),
        inline=False
    )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="channelinfo",
    description="Display information about a text channel."
)
async def channelinfo(
    interaction: discord.Interaction,
    channel: discord.TextChannel = None
):
    channel = channel or interaction.channel

    embed = make_embed(
        f"💬 #{channel.name}",
        "Channel information"
    )

    embed.add_field(name="🆔 Channel ID", value=str(channel.id), inline=True)
    embed.add_field(name="📂 Category", value=channel.category.name if channel.category else "None", inline=True)
    embed.add_field(name="⏱️ Slowmode", value=f"{channel.slowmode_delay}s", inline=True)
    embed.add_field(
        name="📅 Created",
        value=discord.utils.format_dt(channel.created_at, style="D"),
        inline=False
    )

    await interaction.response.send_message(embed=embed)


# ============================================================
# COMMAND 36: HELP
# ============================================================

class HelpView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id

        self.add_item(HelpCategorySelect())

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This help panel belongs to another user.",
                ephemeral=True
            )
            return False

        return True


class HelpCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="Moderation",
                description="Ban, kick, warnings and timeouts",
                emoji="🛡️",
                value="moderation"
            ),
            discord.SelectOption(
                label="Security",
                description="Anti-spam, filters and raid mode",
                emoji="🔒",
                value="security"
            ),
            discord.SelectOption(
                label="Administration",
                description="Channels, roles and announcements",
                emoji="⚙️",
                value="administration"
            ),
            discord.SelectOption(
                label="Information",
                description="Server, member and role information",
                emoji="📊",
                value="information"
            ),
            discord.SelectOption(
                label="All commands",
                description="Show the complete command list",
                emoji="📚",
                value="all"
            )
        ]

        super().__init__(
            placeholder="Choose a command category...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]

        descriptions = {
            "moderation": (
                "**Moderation commands**\n"
                "`/ban` `/unban` `/kick` `/timeout` `/untimeout`\n"
                "`/warn` `/warnings` `/clearwarns` `/purge` `/modlogs`"
            ),
            "security": (
                "**Security commands**\n"
                "`/automod` `/antispam` `/antilink` `/filteradd`\n"
                "`/filterremove` `/filterlist` `/raidmode` `/security`"
            ),
            "administration": (
                "**Administration commands**\n"
                "`/lock` `/unlock` `/slowmode` `/role` `/nick`\n"
                "`/hide` `/unhide` `/announce` `/embed` `/poll`\n"
                "`/reactionrole` `/config` `/setlog` `/lockdown`\n"
                "`/unlockdown` `/setup`"
            ),
            "information": (
                "**Information commands**\n"
                "`/serverinfo` `/userinfo` `/avatar` `/roleinfo`\n"
                "`/channelinfo` `/botinfo` `/membercount` `/serverstats`"
            ),
            "all": (
                "**Sharky Megalodon — Command Directory**\n\n"
                "Moderation: `/ban`, `/unban`, `/kick`, `/timeout`, "
                "`/untimeout`, `/warn`, `/warnings`, `/clearwarns`, "
                "`/purge`, `/modlogs`\n\n"
                "Security: `/automod`, `/antispam`, `/antilink`, "
                "`/filteradd`, `/filterremove`, `/filterlist`, "
                "`/raidmode`, `/security`\n\n"
                "Administration: `/lock`, `/unlock`, `/slowmode`, "
                "`/role`, `/nick`, `/hide`, `/unhide`, `/announce`, "
                "`/embed`, `/poll`, `/reactionrole`, `/config`, "
                "`/setlog`, `/lockdown`, `/unlockdown`, `/setup`\n\n"
                "Information: `/serverinfo`, `/userinfo`, `/avatar`, "
                "`/roleinfo`, `/channelinfo`, `/botinfo`, "
                "`/membercount`, `/serverstats`\n\n"
                "Utilities: `/help`, `/dashboard`, `/language`"
            )
        }

        await interaction.response.edit_message(
            embed=make_embed(
                "🦈 Sharky Help Center",
                descriptions[category]
            ),
            view=self.view
        )


@bot.tree.command(
    name="help",
    description="Open Sharky's interactive command guide."
)
async def help_command(interaction: discord.Interaction):
    embed = make_embed(
        "🦈 Sharky Megalodon",
        "Welcome to the command center.\n\n"
        "Choose a category from the menu below to explore Sharky's commands."
    )

    embed.add_field(
        name="💎 Edition",
        value="Megalodon",
        inline=True
    )

    embed.add_field(
        name="⚡ Interface",
        value="Interactive",
        inline=True
    )

    await interaction.response.send_message(
        embed=embed,
        view=HelpView(interaction.user.id),
        ephemeral=True
    )


# ============================================================
# COMMAND 37: DASHBOARD
# ============================================================

class DashboardView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "This dashboard belongs to another user.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="Security",
        emoji="🛡️",
        style=discord.ButtonStyle.primary
    )
    async def security_button(self, interaction, button):
        config = get_config(interaction.guild.id)

        embed = make_embed(
            "🛡️ Security Dashboard",
            f"Raid mode: **{'Enabled' if config['raid_mode'] else 'Disabled'}**\n"
            f"Anti-link: **{'Enabled' if config['anti_link'] else 'Disabled'}**\n"
            f"Anti-spam: **{'Enabled' if config['anti_spam'] else 'Disabled'}**\n"
            f"AutoMod: **{'Enabled' if config['automod'] else 'Disabled'}**"
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    @discord.ui.button(
        label="Server",
        emoji="🌐",
        style=discord.ButtonStyle.secondary
    )
    async def server_button(self, interaction, button):
        guild = interaction.guild

        embed = make_embed(
            "🌐 Server Dashboard",
            f"**Name:** {guild.name}\n"
            f"**Members:** {guild.member_count or 0}\n"
            f"**Roles:** {len(guild.roles)}\n"
            f"**Text channels:** {len(guild.text_channels)}\n"
            f"**Voice channels:** {len(guild.voice_channels)}"
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


@bot.tree.command(
    name="dashboard",
    description="Open Sharky's interactive administration dashboard."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def dashboard(interaction: discord.Interaction):
    embed = make_embed(
        "🦈 MEGALODON CONTROL CENTER",
        "Use the buttons below to inspect your server's configuration.\n\n"
        "🛡️ **Security:** review protection settings.\n"
        "🌐 **Server:** view server statistics."
    )

    await interaction.response.send_message(
        embed=embed,
        view=DashboardView(interaction.user.id),
        ephemeral=True
    )


# ============================================================
# COMMAND 38: LANGUAGE
# ============================================================

class LanguageSelect(discord.ui.Select):
    def __init__(self, guild_id: int):
        self.guild_id = guild_id

        options = [
            discord.SelectOption(
                label="English",
                description="Use English messages",
                emoji="🇺🇸",
                value="en"
            ),
            discord.SelectOption(
                label="Español",
                description="Usar mensajes en español",
                emoji="🇲🇽",
                value="es"
            ),
            discord.SelectOption(
                label="Français",
                description="Utiliser le français",
                emoji="🇫🇷",
                value="fr"
            ),
            discord.SelectOption(
                label="Português",
                description="Usar mensagens em português",
                emoji="🇧🇷",
                value="pt"
            )
        ]

        super().__init__(
            placeholder="Select the server language...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        language = self.values[0]

        set_config(self.guild_id, "language", language)

        await interaction.response.edit_message(
            embed=success_embed(
                "🌎 Language Updated",
                f"The server language is now **{language}**."
            ),
            view=None
        )


class LanguageView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=120)
        self.add_item(LanguageSelect(guild_id))


@bot.tree.command(
    name="language",
    description="Choose Sharky's language for this server."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def language(interaction: discord.Interaction):
    embed = make_embed(
        "🌎 Language Settings",
        "Choose the language used for supported Sharky messages."
    )

    await interaction.response.send_message(
        embed=embed,
        view=LanguageView(interaction.guild.id),
        ephemeral=True
    )


# ============================================================
# COMMANDS 39–41: BOT AND SERVER STATISTICS
# ============================================================

@bot.tree.command(
    name="botinfo",
    description="Display information about Sharky."
)
async def botinfo(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    uptime = int(time.time() - START_TIME)

    days, remainder = divmod(uptime, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)

    embed = make_embed(
        "🦈 Sharky Megalodon",
        "Professional server administration assistant."
    )

    embed.add_field(name="⚡ Latency", value=f"{latency} ms", inline=True)
    embed.add_field(name="🌐 Servers", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="🔢 Commands", value=str(len(bot.tree.get_commands())), inline=True)
    embed.add_field(name="⏱️ Uptime", value=f"{days}d {hours}h {minutes}m {seconds}s", inline=False)

    if bot.user:
        embed.set_thumbnail(url=bot.user.display_avatar.url)

    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="membercount",
    description="Display the server's member count."
)
async def membercount(interaction: discord.Interaction):
    guild = interaction.guild

    if guild is None:
        return await interaction.response.send_message(
            embed=error_embed("Use this command inside a server."),
            ephemeral=True
        )

    bots_count = sum(1 for member in guild.members if member.bot)
    humans_count = sum(1 for member in guild.members if not member.bot)

    embed = make_embed(
        "👥 Member Statistics",
        f"**Total members:** {guild.member_count or 0}\n"
        f"**Humans in cache:** {humans_count}\n"
        f"**Bots in cache:** {bots_count}"
    )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="serverstats",
    description="Display detailed channel and role statistics."
)
async def serverstats(interaction: discord.Interaction):
    guild = interaction.guild

    embed = make_embed(
        "📊 Server Statistics",
        f"Statistics for **{guild.name}**"
    )

    embed.add_field(name="👥 Members", value=str(guild.member_count or 0), inline=True)
    embed.add_field(name="💬 Text channels", value=str(len(guild.text_channels)), inline=True)
    embed.add_field(name="🔊 Voice channels", value=str(len(guild.voice_channels)), inline=True)
    embed.add_field(name="📁 Categories", value=str(len(guild.categories)), inline=True)
    embed.add_field(name="🎭 Roles", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="😀 Emojis", value=str(len(guild.emojis)), inline=True)

    await interaction.response.send_message(embed=embed)


# ============================================================
# COMMAND 42: SETLOG
# ============================================================

@bot.tree.command(
    name="setlog",
    description="Configure the channel for Sharky's moderation logs."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def setlog(
    interaction: discord.Interaction,
    channel: discord.TextChannel
):
    set_config(
        interaction.guild.id,
        "log_channel",
        channel.id
    )

    await interaction.response.send_message(
        embed=success_embed(
            "📋 Log Channel Configured",
            f"Moderation logs will be sent to {channel.mention}."
        ),
        ephemeral=True
    )

    await send_log(
        interaction.guild,
        "🦈 Sharky Logs Activated",
        f"Log channel configured by {interaction.user.mention}."
    )


# ============================================================
# COMMANDS 43–44: LOCKDOWN
# ============================================================

@bot.tree.command(
    name="lockdown",
    description="Lock all text channels in the server."
)
@app_commands.checks.has_permissions(manage_channels=True)
async def lockdown(interaction: discord.Interaction):
    view = ConfirmView(interaction.user.id)

    await interaction.response.send_message(
        embed=make_embed(
            "🚨 Server Lockdown",
            "This will deny the default role permission to send messages "
            "in all text channels where Sharky can change permissions.\n\n"
            "Do you want to continue?",
            COLOR_ERROR
        ),
        view=view,
        ephemeral=True
    )

    await view.wait()

    if not view.confirmed:
        return

    await interaction.followup.send(
        "Lockdown started. Processing channels...",
        ephemeral=True
    )

    success_count = 0
    failed_count = 0

    for channel in interaction.guild.text_channels:
        try:
            overwrite = channel.overwrites_for(
                interaction.guild.default_role
            )

            overwrite.send_messages = False

            await channel.set_permissions(
                interaction.guild.default_role,
                overwrite=overwrite,
                reason=f"Server lockdown by {interaction.user}"
            )

            success_count += 1

        except discord.HTTPException:
            failed_count += 1

        await asyncio.sleep(0.25)

    log_action(
        interaction.guild,
        interaction.user,
        None,
        "LOCKDOWN",
        f"Locked {success_count} channels; failed: {failed_count}"
    )

    await interaction.followup.send(
        embed=make_embed(
            "🚨 Lockdown Results",
            f"**Locked:** {success_count}\n"
            f"**Failed:** {failed_count}",
            COLOR_WARNING
        ),
        ephemeral=True
    )


@bot.tree.command(
    name="unlockdown",
    description="Restore default send-message permissions across text channels."
)
@app_commands.checks.has_permissions(manage_channels=True)
async def unlockdown(interaction: discord.Interaction):
    view = ConfirmView(interaction.user.id)

    await interaction.response.send_message(
        embed=make_embed(
            "🔓 End Server Lockdown",
            "This restores the default role's send-message permission "
            "to its inherited setting across text channels.\n\n"
            "Continue?",
            COLOR_WARNING
        ),
        view=view,
        ephemeral=True
    )

    await view.wait()

    if not view.confirmed:
        return

    await interaction.followup.send(
        "Restoring channel permissions...",
        ephemeral=True
    )

    success_count = 0
    failed_count = 0

    for channel in interaction.guild.text_channels:
        try:
            overwrite = channel.overwrites_for(
                interaction.guild.default_role
            )

            overwrite.send_messages = None

            await channel.set_permissions(
                interaction.guild.default_role,
                overwrite=overwrite,
                reason=f"Server lockdown ended by {interaction.user}"
            )

            success_count += 1

        except discord.HTTPException:
            failed_count += 1

        await asyncio.sleep(0.25)

    log_action(
        interaction.guild,
        interaction.user,
        None,
        "UNLOCKDOWN",
        f"Restored {success_count} channels; failed: {failed_count}"
    )

    await interaction.followup.send(
        embed=success_embed(
            "🔓 Lockdown Ended",
            f"**Processed:** {success_count}\n"
            f"**Failed:** {failed_count}"
        ),
        ephemeral=True
    )


# ============================================================
# COMMAND 45: SETUP
# ============================================================

class SetupView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the moderator who opened this panel can use it.",
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="Set this channel as logs",
        emoji="📋",
        style=discord.ButtonStyle.primary
    )
    async def set_logs(self, interaction, button):
        set_config(
            interaction.guild.id,
            "log_channel",
            interaction.channel.id
        )

        await interaction.response.send_message(
            embed=success_embed(
                "Log Channel Configured",
                f"{interaction.channel.mention} is now the log channel."
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="Enable security",
        emoji="🛡️",
        style=discord.ButtonStyle.success
    )
    async def enable_security(self, interaction, button):
        set_config(interaction.guild.id, "anti_spam", 1)
        set_config(interaction.guild.id, "anti_link", 1)
        set_config(interaction.guild.id, "automod", 1)

        await interaction.response.send_message(
            embed=success_embed(
                "Security Settings Updated",
                "Anti-spam, anti-link and AutoMod settings have been enabled."
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="View configuration",
        emoji="⚙️",
        style=discord.ButtonStyle.secondary
    )
    async def show_config(self, interaction, button):
        config = get_config(interaction.guild.id)

        embed = make_embed(
            "⚙️ Current Configuration",
            f"**Language:** {config['language']}\n"
            f"**Raid mode:** {'Enabled' if config['raid_mode'] else 'Disabled'}\n"
            f"**Anti-link:** {'Enabled' if config['anti_link'] else 'Disabled'}\n"
            f"**Anti-spam:** {'Enabled' if config['anti_spam'] else 'Disabled'}\n"
            f"**AutoMod:** {'Enabled' if config['automod'] else 'Disabled'}\n"
            f"**Logs:** {f'<#{config['log_channel']}>' if config['log_channel'] else 'Not configured'}"
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )


@bot.tree.command(
    name="setup",
    description="Open Sharky's interactive server setup."
)
@app_commands.checks.has_permissions(manage_guild=True)
async def setup(interaction: discord.Interaction):
    ensure_guild(interaction.guild.id)

    embed = make_embed(
        "🦈 Sharky Megalodon Setup",
        "Welcome to your server's control panel.\n\n"
        "Use the buttons to configure logs, enable security settings "
        "or inspect your current configuration.\n\n"
        "You can also use `/language` to change the language."
    )

    await interaction.response.send_message(
        embed=embed,
        view=SetupView(interaction.user.id),
        ephemeral=True
    )


# ============================================================
# AUTOMATIC MESSAGE PROTECTION
# ============================================================

message_history = {}


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or message.guild is None:
        return

    config = get_config(message.guild.id)
    content = message.content.casefold()

    # Filtered phrases
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT phrase FROM filters WHERE guild_id = ?",
            (message.guild.id,)
        ).fetchall()

    matched_phrase = next(
        (row["phrase"] for row in rows if row["phrase"] in content),
        None
    )

    if matched_phrase:
        if message.author.guild_permissions.manage_messages:
            return await bot.process_commands(message)

        try:
            await message.delete()

            await message.channel.send(
                f"{message.author.mention}, your message was removed "
                "because it matched a server filter.",
                delete_after=5
            )
        except discord.HTTPException:
            pass

        return

    # Anti-link
    if config["anti_link"]:
        has_link = bool(
            re.search(
                r"(https?://|www\.)\S+",
                content,
                flags=re.IGNORECASE
            )
        )

        if has_link and not message.author.guild_permissions.manage_messages:
            try:
                await message.delete()

                await message.channel.send(
                    f"{message.author.mention}, links are restricted here.",
                    delete_after=5
                )
            except discord.HTTPException:
                pass

            return

    # Anti-spam: five messages in five seconds
    if config["anti_spam"]:
        now = time.monotonic()
        key = (message.guild.id, message.author.id)

        recent = [
            stamp
            for stamp in message_history.get(key, [])
            if now - stamp < 5
        ]

        recent.append(now)
        message_history[key] = recent

        if len(recent) >= 5:
            if not message.author.guild_permissions.manage_messages:
                try:
                    await message.delete()

                    await message.channel.send(
                        f"{message.author.mention}, please slow down.",
                        delete_after=5
                    )
                except discord.HTTPException:
                    pass

                return

    await bot.process_commands(message)


# ============================================================
# RAID MODE JOIN CHECK
# ============================================================

@bot.event
async def on_member_join(member: discord.Member):
    config = get_config(member.guild.id)

    if not config["raid_mode"]:
        return

    account_age = datetime.now(timezone.utc) - member.created_at

    # Accounts younger than 24 hours receive a short timeout.
    if account_age < timedelta(hours=24):
        try:
            await member.timeout(
                timedelta(minutes=10),
                reason="Raid mode: newly created account"
            )

            await send_log(
                member.guild,
                "🚨 Raid Mode Action",
                f"**Member:** {member.mention}\n"
                f"**Action:** 10-minute timeout\n"
                "**Reason:** Account younger than 24 hours.",
                COLOR_WARNING
            )

        except discord.HTTPException:
            pass


# ============================================================
# ERROR HANDLING
# ============================================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.MissingPermissions):
        message = "You do not have the required Discord permissions."

    elif isinstance(error, app_commands.BotMissingPermissions):
        message = "Sharky is missing permissions required for this action."

    elif isinstance(error, app_commands.CommandOnCooldown):
        message = "This command is on cooldown. Please try again shortly."

    else:
        original = getattr(error, "original", error)
        print(
            f"[COMMAND ERROR] {interaction.command}: "
            f"{type(original).__name__}: {original}"
        )
        message = "Something went wrong while executing this command."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                embed=error_embed(message),
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                embed=error_embed(message),
                ephemeral=True
            )
    except discord.HTTPException:
        pass


# ============================================================
# BOT STARTUP
# ============================================================

@bot.event
async def on_ready():
    print("=" * 55)
    print(f"🦈 Sharky Megalodon online as {bot.user}")
    print(f"🌐 Servers: {len(bot.guilds)}")
    print(f"⚡ Latency: {round(bot.latency * 1000)} ms")
    print(f"📚 Registered local commands: {len(bot.tree.get_commands())}")
    print("=" * 55)


async def main():
    init_database()

    # Restore persistent self-service role buttons.
    with db_connect() as conn:
        saved_panels = conn.execute(
            "SELECT DISTINCT guild_id, role_id FROM role_buttons"
        ).fetchall()

    for panel in saved_panels:
        bot.add_view(
            RoleSelectView(
                role_id=panel["role_id"],
                guild_id=panel["guild_id"]
            )
        )

    async with bot:
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
