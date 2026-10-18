"""Sharky — Discord moderation bot. Python 3.10+, discord.py 2.5+.
Configure DISCORD_TOKEN in your host's environment variables. Never publish your token.
"""
from __future__ import annotations
import os, sqlite3, time, asyncio
from collections import defaultdict, deque
from datetime import timedelta
import discord
from discord import app_commands
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
DB_PATH = os.getenv("SHARKY_DB_PATH", "sharky.sqlite3")
BLUE = discord.Colour.from_rgb(42, 116, 255)
DARK = discord.Colour.from_rgb(20, 31, 56)
LANGUAGES = {"en": "English", "es": "Español", "pt": "Português", "fr": "Français"}
TEXT = {
 "en": {"done":"Done","error":"Something went wrong.","no_perm":"You don't have permission to do that.","not_found":"No results found.","welcome":"Sharky Control Center","language":"Language","configured":"Configuration saved.","warn":"Warning issued","warnings":"Warnings","empty":"No warnings found.","reason":"Reason","target":"Target","moderator":"Moderator","enabled":"enabled","disabled":"disabled"},
 "es": {"done":"Listo","error":"Ocurrió un error.","no_perm":"No tienes permiso para hacer eso.","not_found":"No se encontraron resultados.","welcome":"Centro de control Sharky","language":"Idioma","configured":"Configuración guardada.","warn":"Advertencia emitida","warnings":"Advertencias","empty":"No hay advertencias.","reason":"Motivo","target":"Usuario","moderator":"Moderador","enabled":"activado","disabled":"desactivado"},
 "pt": {"done":"Concluído","error":"Algo deu errado.","no_perm":"Você não tem permissão para fazer isso.","not_found":"Nenhum resultado encontrado.","welcome":"Central de controle Sharky","language":"Idioma","configured":"Configuração salva.","warn":"Aviso emitido","warnings":"Avisos","empty":"Nenhum aviso encontrado.","reason":"Motivo","target":"Usuário","moderator":"Moderador","enabled":"ativado","disabled":"desativado"},
 "fr": {"done":"Terminé","error":"Une erreur est survenue.","no_perm":"Vous n'avez pas la permission.","not_found":"Aucun résultat trouvé.","welcome":"Centre de contrôle Sharky","language":"Langue","configured":"Configuration enregistrée.","warn":"Avertissement émis","warnings":"Avertissements","empty":"Aucun avertissement.","reason":"Raison","target":"Utilisateur","moderator":"Modérateur","enabled":"activé","disabled":"désactivé"},
}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS config(guild_id INTEGER PRIMARY KEY, log_channel INTEGER, language TEXT DEFAULT 'en', automod INTEGER DEFAULT 1, antispam INTEGER DEFAULT 1, antilink INTEGER DEFAULT 0, raidmode INTEGER DEFAULT 0, slowmode INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS warnings(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, user_id INTEGER, moderator_id INTEGER, reason TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS filters(guild_id INTEGER, word TEXT, PRIMARY KEY(guild_id, word));
        CREATE TABLE IF NOT EXISTS role_buttons(message_id INTEGER, channel_id INTEGER, role_id INTEGER, PRIMARY KEY(message_id, role_id));
        CREATE TABLE IF NOT EXISTS modlogs(id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, target_id INTEGER, moderator_id INTEGER, action TEXT, reason TEXT, created REAL);
        ''')

def ensure_guild(gid: int):
    with db() as c:
        c.execute("INSERT OR IGNORE INTO config(guild_id) VALUES(?)", (gid,))

def cfg(gid: int):
    ensure_guild(gid)
    with db() as c: return dict(c.execute("SELECT * FROM config WHERE guild_id=?", (gid,)).fetchone())

def tr(gid: int, key: str):
    return TEXT.get(cfg(gid).get('language') or 'en', TEXT['en']).get(key, TEXT['en'].get(key, key))

def embed(title: str, description: str = "", colour: discord.Colour = BLUE):
    e = discord.Embed(title=title[:256], description=description[:4000] if description else None, colour=colour, timestamp=discord.utils.utcnow())
    e.set_footer(text="SHARKY • Moderation Suite")
    return e

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
spam_cache = defaultdict(lambda: deque())

async def log_action(guild: discord.Guild, action: str, target, moderator, reason: str = "No reason provided"):
    with db() as c:
        c.execute("INSERT INTO modlogs(guild_id,target_id,moderator_id,action,reason,created) VALUES(?,?,?,?,?,?)",
                  (guild.id, getattr(target, 'id', 0), getattr(moderator, 'id', 0), action, reason, time.time()))
    conf = cfg(guild.id)
    channel = guild.get_channel(conf['log_channel']) if conf.get('log_channel') else None
    if isinstance(channel, discord.TextChannel):
        e = embed(f"{action}", f"**Target:** {getattr(target,'mention',str(target))}\n**Moderator:** {getattr(moderator,'mention',str(moderator))}\n**Reason:** {reason}", DARK)
        try: await channel.send(embed=e)
        except discord.HTTPException: pass

async def reply(interaction: discord.Interaction, title: str, description: str = "", ephemeral: bool = True, colour=BLUE):
    e = embed(title, description, colour)
    if interaction.response.is_done(): await interaction.followup.send(embed=e, ephemeral=ephemeral)
    else: await interaction.response.send_message(embed=e, ephemeral=ephemeral)

def guild_only(interaction: discord.Interaction) -> bool: return interaction.guild is not None

def bot_can_manage(interaction: discord.Interaction, member: discord.Member) -> bool:
    me = interaction.guild.me
    return bool(me and me.guild_permissions.moderate_members and member.top_role < me.top_role and member != interaction.user and member != interaction.guild.owner)

async def member_action(interaction, member, action, reason, func):
    if not interaction.guild or not isinstance(interaction.user, discord.Member): return await reply(interaction, "Sharky", "Use this command inside a server.")
    if member == interaction.user: return await reply(interaction, "Sharky", "You can't target yourself.")
    try:
        await func()
        await log_action(interaction.guild, action, member, interaction.user, reason)
        await reply(interaction, f"{action} • {tr(interaction.guild.id,'done')}", f"**User:** {member.mention}\n**Reason:** {reason}", colour=BLUE)
    except discord.Forbidden: await reply(interaction, "Permission error", "Check Sharky's role hierarchy and permissions.", colour=discord.Colour.red())
    except discord.HTTPException as ex: await reply(interaction, "Discord API error", str(ex)[:500], colour=discord.Colour.red())

class RoleButtonView(discord.ui.View):
    def __init__(self, role_id: int):
        super().__init__(timeout=None)
        button = discord.ui.Button(label="Get / Remove role", style=discord.ButtonStyle.primary, custom_id=f"sharky:role:{role_id}", emoji="🔹")
        async def callback(interaction: discord.Interaction):
            if not interaction.guild or not isinstance(interaction.user, discord.Member):
                return await reply(interaction, "Sharky", "This button only works in a server.")
            role = interaction.guild.get_role(role_id)
            if not role: return await reply(interaction, "Role unavailable", "An administrator may need to recreate this button.")
            if role >= interaction.guild.me.top_role or role.is_default():
                return await reply(interaction, "Role hierarchy", "Move Sharky's role above the requested role.")
            try:
                if role in interaction.user.roles:
                    await interaction.user.remove_roles(role, reason="Sharky self-role button")
                    await reply(interaction, "Role removed", f"Removed {role.mention}.")
                else:
                    await interaction.user.add_roles(role, reason="Sharky self-role button")
                    await reply(interaction, "Role added", f"Added {role.mention}.")
            except discord.Forbidden: await reply(interaction, "Permission error", "Sharky cannot manage that role.")
        button.callback = callback
        self.add_item(button)

initialized = False

@bot.event
async def on_ready():
    global initialized
    if not initialized:
        init_db()
        with db() as c:
            rows = c.execute("SELECT DISTINCT role_id FROM role_buttons").fetchall()
        for row in rows: bot.add_view(RoleButtonView(row['role_id']))
        try:
            synced = await bot.tree.sync()
            print(f"Sharky synced {len(synced)} slash commands.")
        except Exception as e: print(f"Slash-command sync failed: {e}")
        initialized = True
    print(f"Sharky online as {bot.user} | servers: {len(bot.guilds)}")
    try: await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="server safety • /help"))
    except Exception: pass

@bot.event
async def on_guild_join(guild): ensure_guild(guild.id)

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return await bot.process_commands(message)
    conf = cfg(message.guild.id)
    member = message.author
    if isinstance(member, discord.Member) and not member.guild_permissions.manage_messages:
        content = message.content.lower()
        if conf['automod']:
            with db() as c: blocked = [r['word'] for r in c.execute("SELECT word FROM filters WHERE guild_id=?", (message.guild.id,)).fetchall()]
            if any(w and w in content for w in blocked):
                try: await message.delete()
                except discord.HTTPException: pass
                await log_action(message.guild, "Blocked word removed", member, bot.user or member, "Matched server word filter")
                return
        if conf['antilink'] and ("http://" in content or "https://" in content or "discord.gg/" in content):
            try: await message.delete()
            except discord.HTTPException: pass
            return
        if conf['antispam']:
            now = time.time(); q = spam_cache[(message.guild.id, member.id)]; q.append(now)
            while q and now - q[0] > 7: q.popleft()
            if len(q) >= 6:
                try:
                    await message.delete()
                    await member.timeout(timedelta(seconds=15), reason="Sharky anti-spam")
                    await log_action(message.guild, "Anti-spam timeout", member, bot.user or member, "6+ messages within 7 seconds")
                except discord.HTTPException: pass
                q.clear()
    await bot.process_commands(message)

@bot.event
async def on_member_join(member: discord.Member):
    if cfg(member.guild.id)['raidmode']:
        try: await member.timeout(timedelta(minutes=10), reason="Sharky raid mode")
        except (discord.Forbidden, discord.HTTPException): pass

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions): msg = tr(interaction.guild.id, 'no_perm') if interaction.guild else "Missing permission."
    elif isinstance(error, app_commands.BotMissingPermissions): msg = "Sharky is missing a required permission. Check its role and server permissions."
    else:
        print(f"Slash command error: {error}")
        msg = tr(interaction.guild.id, 'error') if interaction.guild else "Something went wrong."
    await reply(interaction, "Sharky", msg, colour=discord.Colour.red())

# 1
@bot.tree.command(name="ban", description="Ban a member from this server")
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.describe(member="Member to ban", reason="Reason for the ban")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str="No reason provided"):
    await member_action(interaction, member, "Ban", reason, lambda: member.ban(reason=reason, delete_message_seconds=0))
# 2
@bot.tree.command(name="unban", description="Unban a user by their Discord ID")
@app_commands.checks.has_permissions(ban_members=True)
async def unban(interaction: discord.Interaction, user_id: str, reason: str="No reason provided"):
    if not interaction.guild: return await reply(interaction,"Sharky","Use this command in a server.")
    try:
        uid=int(user_id); user=await bot.fetch_user(uid); await interaction.guild.unban(user, reason=reason)
        await log_action(interaction.guild,"Unban",user,interaction.user,reason); await reply(interaction,"User unbanned",f"{user.mention} • {reason}")
    except (ValueError, discord.NotFound): await reply(interaction,"User not found","Provide a valid banned user ID.")
    except discord.Forbidden: await reply(interaction,"Permission error","Sharky needs Ban Members permission.")
# 3
@bot.tree.command(name="kick", description="Kick a member from this server")
@app_commands.checks.has_permissions(kick_members=True)
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str="No reason provided"):
    await member_action(interaction,member,"Kick",reason,lambda:member.kick(reason=reason))
# 4
@bot.tree.command(name="timeout", description="Temporarily timeout a member")
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.describe(minutes="Duration from 1 to 10080 minutes")
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int,1,10080], reason: str="No reason provided"):
    await member_action(interaction,member,"Timeout",reason,lambda:member.timeout(timedelta(minutes=minutes),reason=reason))
# 5
@bot.tree.command(name="untimeout", description="Remove a member's timeout")
@app_commands.checks.has_permissions(moderate_members=True)
async def untimeout(interaction: discord.Interaction, member: discord.Member, reason: str="Timeout removed by staff"):
    await member_action(interaction,member,"Remove timeout",reason,lambda:member.timeout(None,reason=reason))
# 6
@bot.tree.command(name="warn", description="Issue a recorded warning")
@app_commands.checks.has_permissions(moderate_members=True)
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str="No reason provided"):
    if not interaction.guild: return await reply(interaction,"Sharky","Use this in a server.")
    with db() as c: c.execute("INSERT INTO warnings(guild_id,user_id,moderator_id,reason,created) VALUES(?,?,?,?,?)",(interaction.guild.id,member.id,interaction.user.id,reason,time.time()))
    await log_action(interaction.guild,"Warning",member,interaction.user,reason)
    try: await member.send(embed=embed(f"Warning • {interaction.guild.name}",reason,discord.Colour.orange()))
    except discord.HTTPException: pass
    await reply(interaction,tr(interaction.guild.id,'warn'),f"{member.mention}\n**Reason:** {reason}")
# 7
@bot.tree.command(name="warnings", description="View a member's recorded warnings")
@app_commands.checks.has_permissions(moderate_members=True)
async def warnings(interaction: discord.Interaction, member: discord.Member):
    with db() as c: rows=c.execute("SELECT id,moderator_id,reason,created FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",(interaction.guild.id,member.id)).fetchall()
    if not rows: return await reply(interaction,"Warnings",tr(interaction.guild.id,'empty'))
    e=embed(f"Warnings • {member}","\n".join(f"`#{r['id']}` <t:{int(r['created'])}:R> — <@{r['moderator_id']}>\n{r['reason']}" for r in rows))
    await interaction.response.send_message(embed=e,ephemeral=True)
# 8
@bot.tree.command(name="clearwarns", description="Clear all warnings for a member")
@app_commands.checks.has_permissions(moderate_members=True)
async def clearwarns(interaction: discord.Interaction, member: discord.Member):
    with db() as c: cur=c.execute("DELETE FROM warnings WHERE guild_id=? AND user_id=?",(interaction.guild.id,member.id))
    await log_action(interaction.guild,"Clear warnings",member,interaction.user,f"Removed {cur.rowcount} warnings")
    await reply(interaction,"Warnings cleared",f"Removed **{cur.rowcount}** warning(s) for {member.mention}.")
# 9
@bot.tree.command(name="purge", description="Delete a number of recent messages")
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.describe(amount="Number of messages, 1–100")
async def purge(interaction: discord.Interaction, amount: app_commands.Range[int,1,100]):
    if not isinstance(interaction.channel,discord.TextChannel): return await reply(interaction,"Sharky","Use in a text channel.")
    await interaction.response.defer(ephemeral=True)
    deleted=await interaction.channel.purge(limit=amount,reason=f"Purge by {interaction.user}")
    await log_action(interaction.guild,"Purge",interaction.channel,interaction.user,f"Deleted {len(deleted)} messages")
    await interaction.followup.send(embed=embed("Messages purged",f"Deleted **{len(deleted)}** messages."),ephemeral=True)
# 10
@bot.tree.command(name="modlogs", description="View recent moderation actions for a member")
@app_commands.checks.has_permissions(view_audit_log=True)
async def modlogs(interaction: discord.Interaction, member: discord.Member):
    with db() as c: rows=c.execute("SELECT action,moderator_id,reason,created FROM modlogs WHERE guild_id=? AND target_id=? ORDER BY id DESC LIMIT 8",(interaction.guild.id,member.id)).fetchall()
    desc="\n\n".join(f"**{r['action']}** • <t:{int(r['created'])}:R>\nBy <@{r['moderator_id']}> — {r['reason']}" for r in rows) or "No moderation history stored yet."
    await reply(interaction,f"Moderation history • {member}",desc)
# 11
@bot.tree.command(name="automod", description="Enable or disable blocked-word filtering")
@app_commands.checks.has_permissions(manage_guild=True)
async def automod(interaction: discord.Interaction, enabled: bool):
    with db() as c: c.execute("UPDATE config SET automod=? WHERE guild_id=?",(int(enabled),interaction.guild.id))
    await reply(interaction,"AutoMod updated",f"Blocked-word filter is now **{tr(interaction.guild.id,'enabled' if enabled else 'disabled')}**.")
# 12
@bot.tree.command(name="antispam", description="Enable or disable automatic spam protection")
@app_commands.checks.has_permissions(manage_guild=True)
async def antispam(interaction: discord.Interaction, enabled: bool):
    with db() as c: c.execute("UPDATE config SET antispam=? WHERE guild_id=?",(int(enabled),interaction.guild.id))
    await reply(interaction,"Anti-spam updated",f"Anti-spam is now **{tr(interaction.guild.id,'enabled' if enabled else 'disabled')}**.")
# 13
@bot.tree.command(name="antilink", description="Enable or disable automatic link filtering")
@app_commands.checks.has_permissions(manage_guild=True)
async def antilink(interaction: discord.Interaction, enabled: bool):
    with db() as c: c.execute("UPDATE config SET antilink=? WHERE guild_id=?",(int(enabled),interaction.guild.id))
    await reply(interaction,"Anti-link updated",f"Anti-link is now **{tr(interaction.guild.id,'enabled' if enabled else 'disabled')}**.")
# 14
@bot.tree.command(name="filteradd", description="Add a blocked word or phrase")
@app_commands.checks.has_permissions(manage_guild=True)
async def filteradd(interaction: discord.Interaction, word: str):
    word=word.strip().lower()
    if not word or len(word) > 50: return await reply(interaction,"Invalid filter","Enter a word or phrase.")
    with db() as c: c.execute("INSERT OR IGNORE INTO filters(guild_id,word) VALUES(?,?)",(interaction.guild.id,word))
    await reply(interaction,"Filter added",f"Added `{word}` to the blocked-word list.")
# 15
@bot.tree.command(name="filterremove", description="Remove a blocked word or phrase")
@app_commands.checks.has_permissions(manage_guild=True)
async def filterremove(interaction: discord.Interaction, word: str):
    with db() as c: cur=c.execute("DELETE FROM filters WHERE guild_id=? AND word=?",(interaction.guild.id,word.strip().lower()))
    await reply(interaction,"Filter removed" if cur.rowcount else "Filter not found",f"`{word}` {'removed.' if cur.rowcount else 'was not on the list.'}")
# 16
@bot.tree.command(name="filterlist", description="List the blocked words and phrases")
@app_commands.checks.has_permissions(manage_guild=True)
async def filterlist(interaction: discord.Interaction):
    with db() as c: rows=c.execute("SELECT word FROM filters WHERE guild_id=? ORDER BY word LIMIT 50",(interaction.guild.id,)).fetchall()
    await reply(interaction,"Blocked-word filters", "\n".join(f"• `{r['word']}`" for r in rows) if rows else "No filters configured.")
# 17
@bot.tree.command(name="lock", description="Lock this text channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def lock(interaction: discord.Interaction):
    ch=interaction.channel
    if not isinstance(ch,discord.TextChannel): return await reply(interaction,"Sharky","This channel cannot be locked by this command.")
    await ch.set_permissions(interaction.guild.default_role,send_messages=False,reason=f"Locked by {interaction.user}")
    await log_action(interaction.guild,"Channel lock",ch,interaction.user,"Channel locked")
    await reply(interaction,"Channel locked",f"{ch.mention} is now locked.")
# 18
@bot.tree.command(name="unlock", description="Unlock this text channel")
@app_commands.checks.has_permissions(manage_channels=True)
async def unlock(interaction: discord.Interaction):
    ch=interaction.channel
    if not isinstance(ch,discord.TextChannel): return await reply(interaction,"Sharky","This channel cannot be unlocked by this command.")
    await ch.set_permissions(interaction.guild.default_role,send_messages=None,reason=f"Unlocked by {interaction.user}")
    await log_action(interaction.guild,"Channel unlock",ch,interaction.user,"Channel unlocked")
    await reply(interaction,"Channel unlocked",f"{ch.mention} is unlocked.")
# 19
@bot.tree.command(name="slowmode", description="Set this channel's slowmode")
@app_commands.checks.has_permissions(manage_channels=True)
async def slowmode(interaction: discord.Interaction, seconds: app_commands.Range[int,0,21600]):
    if not isinstance(interaction.channel,discord.TextChannel): return await reply(interaction,"Sharky","Use in a text channel.")
    await interaction.channel.edit(slowmode_delay=seconds,reason=f"Slowmode set by {interaction.user}")
    await reply(interaction,"Slowmode updated",f"Slowmode is now **{seconds} seconds**.")
# 20
@bot.tree.command(name="raidmode", description="Enable or disable new-member raid protection")
@app_commands.checks.has_permissions(manage_guild=True)
async def raidmode(interaction: discord.Interaction, enabled: bool):
    with db() as c: c.execute("UPDATE config SET raidmode=? WHERE guild_id=?",(int(enabled),interaction.guild.id))
    await reply(interaction,"Raid mode updated",f"Raid mode is now **{tr(interaction.guild.id,'enabled' if enabled else 'disabled')}**. New members will be timed out for 10 minutes while enabled.")
# 21
@bot.tree.command(name="role", description="Add or remove a role from a member")
@app_commands.checks.has_permissions(manage_roles=True)
async def role(interaction: discord.Interaction, member: discord.Member, role: discord.Role, action: str):
    if action not in ("add","remove"): return await reply(interaction,"Invalid action","Choose `add` or `remove`.")
    if role.is_default() or role >= interaction.guild.me.top_role: return await reply(interaction,"Role hierarchy","Sharky's highest role must be above that role.")
    try:
        if action=="add": await member.add_roles(role,reason=f"Role action by {interaction.user}")
        else: await member.remove_roles(role,reason=f"Role action by {interaction.user}")
        await log_action(interaction.guild,f"Role {action}",member,interaction.user,str(role))
        await reply(interaction,"Role updated",f"{role.mention} {'added to' if action=='add' else 'removed from'} {member.mention}.")
    except discord.Forbidden: await reply(interaction,"Permission error","Sharky cannot manage this role.")
# 22
@bot.tree.command(name="nick", description="Change a member's server nickname")
@app_commands.checks.has_permissions(manage_nicknames=True)
async def nick(interaction: discord.Interaction, member: discord.Member, nickname: str):
    try:
        await member.edit(nick=nickname[:32],reason=f"Nickname set by {interaction.user}")
        await log_action(interaction.guild,"Nickname change",member,interaction.user,nickname)
        await reply(interaction,"Nickname updated",f"Updated nickname for {member.mention}.")
    except discord.Forbidden: await reply(interaction,"Permission error","Sharky cannot change that nickname.")
# 23
@bot.tree.command(name="hide", description="Hide this channel from the @everyone role")
@app_commands.checks.has_permissions(manage_channels=True)
async def hide(interaction: discord.Interaction):
    if not isinstance(interaction.channel,discord.TextChannel): return await reply(interaction,"Sharky","Use in a text channel.")
    await interaction.channel.set_permissions(interaction.guild.default_role,view_channel=False,reason=f"Hidden by {interaction.user}")
    await reply(interaction,"Channel hidden",f"{interaction.channel.mention} is hidden from @everyone.")
# 24
@bot.tree.command(name="unhide", description="Show this channel to the @everyone role")
@app_commands.checks.has_permissions(manage_channels=True)
async def unhide(interaction: discord.Interaction):
    if not isinstance(interaction.channel,discord.TextChannel): return await reply(interaction,"Sharky","Use in a text channel.")
    await interaction.channel.set_permissions(interaction.guild.default_role,view_channel=None,reason=f"Unhidden by {interaction.user}")
    await reply(interaction,"Channel visible",f"{interaction.channel.mention} is visible to @everyone again.")
# 25
@bot.tree.command(name="announce", description="Send an announcement to a channel")
@app_commands.checks.has_permissions(manage_messages=True)
async def announce(interaction: discord.Interaction, channel: discord.TextChannel, message: str):
    await channel.send(embed=embed("📣 Announcement",message,BLUE))
    await reply(interaction,"Announcement sent",f"Published in {channel.mention}.")
# 26
@bot.tree.command(name="embed", description="Create a custom embed message")
@app_commands.checks.has_permissions(manage_messages=True)
async def embed_command(interaction: discord.Interaction, channel: discord.TextChannel, title: str, description: str):
    await channel.send(embed=embed(title,description))
    await reply(interaction,"Embed published",f"Sent your embed to {channel.mention}.")
# 27
@bot.tree.command(name="poll", description="Create a simple yes/no poll")
@app_commands.checks.has_permissions(manage_messages=True)
async def poll(interaction: discord.Interaction, question: str, channel: discord.TextChannel=None):
    target=channel or interaction.channel
    msg=await target.send(embed=embed("📊 Community poll",question))
    await msg.add_reaction("👍"); await msg.add_reaction("👎")
    await reply(interaction,"Poll created",f"Your poll is live in {target.mention}.")
# 28
@bot.tree.command(name="reactionrole", description="Create a button members can use to toggle a role")
@app_commands.checks.has_permissions(manage_roles=True)
async def reactionrole(interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role, label: str="Get / Remove role"):
    if role.is_default() or role >= interaction.guild.me.top_role: return await reply(interaction,"Role hierarchy","Move Sharky's role above the requested role first.")
    view=RoleButtonView(role.id)
    view.children[0].label=label[:80]
    msg=await channel.send(embed=embed("Self-role",f"Press the button below to toggle {role.mention}."),view=view)
    with db() as c: c.execute("INSERT OR IGNORE INTO role_buttons(message_id,channel_id,role_id) VALUES(?,?,?)",(msg.id,channel.id,role.id))
    await reply(interaction,"Role button created",f"Posted in {channel.mention}.")
# 29
@bot.tree.command(name="config", description="View or change Sharky server settings")
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.choices(setting=[app_commands.Choice(name="log_channel",value="log_channel"),app_commands.Choice(name="language",value="language")])
async def config(interaction: discord.Interaction, setting: app_commands.Choice[str], value: str):
    if setting.value=="language":
        value=value.lower()
        if value not in LANGUAGES: return await reply(interaction,"Invalid language","Choose one: `en`, `es`, `pt`, `fr`.")
        with db() as c: c.execute("UPDATE config SET language=? WHERE guild_id=?",(value,interaction.guild.id))
        return await reply(interaction,"Language updated",f"Sharky language: **{LANGUAGES[value]}**.")
    try: cid=int(value); channel=interaction.guild.get_channel(cid)
    except ValueError: channel=None
    if not isinstance(channel,discord.TextChannel): return await reply(interaction,"Invalid channel","For `log_channel`, enter a text-channel ID.")
    with db() as c: c.execute("UPDATE config SET log_channel=? WHERE guild_id=?",(channel.id,interaction.guild.id))
    await reply(interaction,"Log channel saved",f"Moderation logs will be sent to {channel.mention}.")
# 30
@bot.tree.command(name="serverinfo", description="Show server information")
async def serverinfo(interaction: discord.Interaction):
    g=interaction.guild
    if not g: return await reply(interaction,"Sharky","Use in a server.")
    e=embed(g.name,f"**Owner:** {g.owner.mention if g.owner else 'Unknown'}\n**Members:** {g.member_count}\n**Channels:** {len(g.channels)}\n**Roles:** {len(g.roles)}\n**Created:** <t:{int(g.created_at.timestamp())}:D>")
    if g.icon: e.set_thumbnail(url=g.icon.url)
    await interaction.response.send_message(embed=e,ephemeral=True)
# 31
@bot.tree.command(name="userinfo", description="Show information about a server member")
async def userinfo(interaction: discord.Interaction, member: discord.Member=None):
    m=member or interaction.user
    e=embed(f"User profile • {m}",f"**ID:** `{m.id}`\n**Joined:** <t:{int(m.joined_at.timestamp())}:R>\n**Created:** <t:{int(m.created_at.timestamp())}:D>\n**Top role:** {m.top_role.mention}\n**Bot:** {'Yes' if m.bot else 'No'}")
    e.set_thumbnail(url=m.display_avatar.url)
    await interaction.response.send_message(embed=e,ephemeral=True)
# 32
@bot.tree.command(name="avatar", description="Show a user's avatar")
async def avatar(interaction: discord.Interaction, member: discord.User=None):
    u=member or interaction.user
    e=embed(f"Avatar • {u}",f"[Open full image]({u.display_avatar.url})")
    e.set_image(url=u.display_avatar.url)
    await interaction.response.send_message(embed=e,ephemeral=True)
# 33
@bot.tree.command(name="roleinfo", description="Show information about a server role")
async def roleinfo(interaction: discord.Interaction, role: discord.Role):
    e=embed(f"Role • {role.name}",f"**ID:** `{role.id}`\n**Members:** {len(role.members)}\n**Position:** {role.position}\n**Mentionable:** {role.mentionable}\n**Hoisted:** {role.hoist}\n**Created:** <t:{int(role.created_at.timestamp())}:D>")
    await interaction.response.send_message(embed=e,ephemeral=True)
# 34
@bot.tree.command(name="channelinfo", description="Show information about a channel")
async def channelinfo(interaction: discord.Interaction, channel: discord.TextChannel=None):
    ch=channel or interaction.channel
    e=embed(f"Channel • #{ch.name}",f"**ID:** `{ch.id}`\n**Category:** {ch.category.mention if ch.category else 'None'}\n**Slowmode:** {getattr(ch,'slowmode_delay',0)} seconds\n**Created:** <t:{int(ch.created_at.timestamp())}:D>")
    await interaction.response.send_message(embed=e,ephemeral=True)
# 35
@bot.tree.command(name="help", description="Open Sharky's command guide")
async def help_command(interaction: discord.Interaction):
    e=embed("🦈 SHARKY • COMMAND CENTER","A moderation and server-management toolkit. Use `/` to browse all 35 commands.")
    groups=[("Moderation","/ban • /unban • /kick • /timeout • /untimeout • /warn • /warnings • /clearwarns • /purge • /modlogs"),("Protection","/automod • /antispam • /antilink • /filteradd • /filterremove • /filterlist • /raidmode"),("Server tools","/lock • /unlock • /slowmode • /role • /nick • /hide • /unhide • /reactionrole • /config"),("Community","/announce • /embed • /poll • /serverinfo • /userinfo • /avatar • /roleinfo • /channelinfo")]
    for name,value in groups: e.add_field(name=name,value=value,inline=False)
    e.add_field(name="Quick setup",value="1. Invite Sharky with the permissions it needs.\n2. Run `/config` and set `log_channel` using the channel ID.\n3. Set `language` to `en`, `es`, `pt`, or `fr`.\n4. Keep Sharky's role above roles it must manage.",inline=False)
    await interaction.response.send_message(embed=e,ephemeral=True)

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN environment variable. Add your bot token in Fadehost's environment variables.")
    bot.run(TOKEN, log_handler=None)
