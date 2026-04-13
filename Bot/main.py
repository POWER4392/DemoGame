import discord
from discord.ext import commands, tasks
import yt_dlp
import asyncio
import datetime
import json
import requests
import os
import re
import random
import math
import time
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageOps
import sqlite3
import threading
import xml.etree.ElementTree as ET
from aiohttp import web

db_lock = threading.Lock()
os.makedirs("databases", exist_ok=True)
conn = sqlite3.connect("databases/bot_core.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                    guild_id TEXT, user_id TEXT,
                    xp INTEGER, level INTEGER,
                    PRIMARY KEY (guild_id, user_id)
                )''')
cursor.execute('''CREATE TABLE IF NOT EXISTS social_tracker (
                    guild_id TEXT, platform TEXT, 
                    target_id TEXT, channel_id TEXT, 
                    ping_role TEXT, last_post_id TEXT,
                    PRIMARY KEY (guild_id, platform, target_id)
                )''')
cursor.execute('''CREATE TABLE IF NOT EXISTS warnings (
                    guild_id TEXT, user_id TEXT,
                    warn_count INTEGER,
                    PRIMARY KEY (guild_id, user_id)
                )''')
cursor.execute('''CREATE TABLE IF NOT EXISTS timed_roles (
                    guild_id TEXT, user_id TEXT, role_id TEXT,
                    expires_at REAL,
                    PRIMARY KEY (guild_id, user_id, role_id)
                )''')
cursor.execute('''CREATE TABLE IF NOT EXISTS reaction_panels (
                    message_id TEXT PRIMARY KEY,
                    guild_id TEXT,
                    roles_json TEXT
                )''')
cursor.execute('''CREATE TABLE IF NOT EXISTS gui_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT, payload TEXT
                )''')
conn.commit()

def db_get_user(guild_id, user_id):
    with db_lock:
        cursor.execute("SELECT xp, level FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        row = cursor.fetchone()
        if not row:
            cursor.execute("INSERT INTO users (guild_id, user_id, xp, level) VALUES (?, ?, 0, 1)", (guild_id, user_id))
            conn.commit()
            return (0, 1)
        return row

def db_update_xp(guild_id, user_id, xp_add):
    with db_lock:
        cursor.execute("SELECT xp, level FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        row = cursor.fetchone()
        if row:
            nxp, clvl = row[0] + xp_add, row[1]
            nlvl = max(1, int((nxp / 100) ** (1/1.5)))
            if nlvl < clvl: nlvl = clvl
            cursor.execute("UPDATE users SET xp=?, level=? WHERE guild_id=? AND user_id=?", (nxp, nlvl, guild_id, user_id))
            conn.commit()
            return clvl, nlvl
        return 1, 1

# 1. TẢI CẤU HÌNH
try:
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
except Exception as e:
    print(f"❌ Lỗi đọc file config.json: {e}")
    config = {}

# 2. KHỞI TẠO BOT
intents = discord.Intents.all()
bot = commands.AutoShardedBot(command_prefix=config.get("prefix", "!"), intents=intents)
bot.remove_command('help') # Xoá lệnh help mặc định

YDL_OPTIONS = {'format': 'bestaudio/best', 'noplaylist': 'True', 'quiet': True, 'default_search': 'ytsearch'}
FFMPEG_OPTIONS = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}

# ================= VIEWS (TƯƠNG TÁC) =================
class MusicControlView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    async def interaction_check(self, interaction: discord.Interaction):
        # BUG FIX: voice_client có thể là None nếu bot đã rời kênh
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message("❌ Bot hiện không ở trong kênh thoại nào.", ephemeral=True)
            return False
        if not interaction.user.voice or interaction.user.voice.channel != vc.channel:
            await interaction.response.send_message("❌ Bạn phải vào chung Kênh Thoại với Bot thì mới được bấm!", ephemeral=True)
            return False
        return True
    @discord.ui.button(label="Tạm Dừng / Phát", style=discord.ButtonStyle.primary, emoji="⏸️", custom_id="m_pause")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing(): vc.pause(); await interaction.response.send_message("⏸️ Đã tạm dừng nhạc.", ephemeral=False)
        elif vc and vc.is_paused(): vc.resume(); await interaction.response.send_message("▶️ Tiếp tục phát nhạc.", ephemeral=False)
        else: await interaction.response.send_message("❌ Chưa đến lượt.", ephemeral=True)
    @discord.ui.button(label="Bỏ Qua", style=discord.ButtonStyle.secondary, emoji="⏭️", custom_id="m_skip")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing(): vc.stop(); await interaction.response.send_message("⏭️ Tiến lên bài tiếp theo!", ephemeral=False)
    @discord.ui.button(label="Tắt Nhạc", style=discord.ButtonStyle.danger, emoji="⏹️", custom_id="m_stop")
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc:
            music_queues.pop(interaction.guild.id, None)
            vc.stop(); await vc.disconnect(); await interaction.response.send_message("⏹️ Đã giải phóng kênh thoại.", ephemeral=False)
            
    @discord.ui.button(label="Trộn Bài", style=discord.ButtonStyle.success, emoji="🔀", custom_id="m_shuffle")
    async def shuffle(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        if guild_id in music_queues and len(music_queues[guild_id]) > 1:
            random.shuffle(music_queues[guild_id])
            await interaction.response.send_message(f"🔀 Đã xáo trộn ngẫu nhiên {len(music_queues[guild_id])} bài trong danh sách chờ!", ephemeral=False)
        else:
            await interaction.response.send_message("❌ Hàng đợi phải có từ 2 bài trở lên mới đảo thuật toán được.", ephemeral=True)
            
    @discord.ui.button(label="Tự Động Phát", style=discord.ButtonStyle.secondary, emoji="🎲", custom_id="m_autoplay")
    async def autoplay_toggle(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild.id
        if guild_id in autoplay_disabled:
            autoplay_disabled.remove(guild_id)
            await interaction.response.send_message("✅ Đã **BẬT** Tự động phát nhạc (AutoPlay). Sẽ tự chọn bài nã tiếp khi hết danh sách!", ephemeral=False)
        else:
            autoplay_disabled.add(guild_id)
            await interaction.response.send_message("🛑 Đã **TẮT** Tự động phát nhạc (AutoPlay). Nhạc sẽ dừng khi hết hàng đợi.", ephemeral=False)

class TicketControlView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Khoá & Khắc Phục", style=discord.ButtonStyle.danger, emoji="🔒", custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if "ticket-" in interaction.channel.name:
            await interaction.response.send_message("🔒 Vé hỗ trợ này sẽ bị rã đông và xoá sau 5 giây...")
            await asyncio.sleep(5); await interaction.channel.delete()
        else: await interaction.response.send_message("❌ Kênh này không phải vé hỗ trợ.", ephemeral=True)

class TicketView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Tạo Vé Hỗ Trợ Mới", style=discord.ButtonStyle.success, emoji="🎫", custom_id="create_ticket")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild, user = interaction.guild, interaction.user
        if discord.utils.get(guild.channels, name=f"ticket-{user.name.lower()}"):
            return await interaction.response.send_message(f"❌ Bạn đã có một vé hỗ trợ đang mở rồi!", ephemeral=True)
        overwrites = { guild.default_role: discord.PermissionOverwrite(read_messages=False), user: discord.PermissionOverwrite(read_messages=True, send_messages=True), guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True) }
        mod_role_ids = config.get("servers", {}).get(str(guild.id), config).get("mod_role_ids", [])
        old_mod_role_id = config.get("servers", {}).get(str(guild.id), config).get("mod_role_id")
        if old_mod_role_id and old_mod_role_id not in mod_role_ids: mod_role_ids.append(old_mod_role_id)
        for m_id in mod_role_ids:
            role = guild.get_role(int(m_id))
            if role: overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
        category = discord.utils.get(guild.categories, name="HỖ TRỢ (TICKETS)")
        if not category: category = await guild.create_category("HỖ TRỢ (TICKETS)")
        ticket_channel = await guild.create_text_channel(f"ticket-{user.name}", category=category, overwrites=overwrites)
        
        embed = discord.Embed(title="🎫 Kênh Hỗ Trợ Độc Quyền", description=f"Xin chào {user.mention}! Vui lòng mô tả vấn đề của bạn ở đây.\nĐội ngũ Ban Quản Trị sẽ phản hồi sớm nhất có thể.", color=0x5865F2)
        await ticket_channel.send(content=f"{user.mention}", embed=embed, view=TicketControlView())
        await interaction.response.send_message(f"✅ Vé của bạn đã được tạo tại {ticket_channel.mention}", ephemeral=True)

class VoiceNameModal(discord.ui.Modal, title="Đăng Ký Khởi Tạo Phòng Thoại"):
    room_name = discord.ui.TextInput(
        label="Nhập Tên Phòng Bạn Muốn:",
        placeholder="VD: Hội chém gió, Tìm Party Rank...",
        min_length=2, max_length=50
    )
    user_limit = discord.ui.TextInput(
        label="Số người tối đa (bỏ trống = không giới hạn):",
        placeholder="VD: 5, 10...",
        required=False, max_length=2
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild = interaction.guild
        
        server_cfg = config.get("servers", {}).get(str(guild.id), config)
        category_id = server_cfg.get("voice_category_id")
        if category_id: category = guild.get_channel(int(category_id))
        else: category = discord.utils.get(guild.categories, name="TRẠM DỪNG CHÂN")
        
        if not category: category = await guild.create_category("TRẠM DỪNG CHÂN")
        
        limit = 0
        if self.user_limit.value.isdigit():
            limit = int(self.user_limit.value)
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=True),
            interaction.user: discord.PermissionOverwrite(manage_channels=True, connect=True)
        }
        
        new_channel = await guild.create_voice_channel(
            name=f"🎧 {self.room_name.value}",
            category=category,
            overwrites=overwrites,
            user_limit=limit
        )
        temp_voices.add(new_channel.id)
        
        await interaction.response.send_message(f"✅ Bùm! Phòng của bạn đã được đắp lên: {new_channel.mention}\n*(Lưu ý: Bạn được cấp full quyền Sửa Tên & Khoá Kênh này. Kênh sẽ tự sát sau 60s nếu không ai nói chuyện).* ", ephemeral=True)
        
        async def cleanup_unjoined():
            await asyncio.sleep(60)
            try:
                chan = bot.get_channel(new_channel.id)
                if chan and len(chan.members) == 0:
                    await chan.delete()
                    if new_channel.id in temp_voices: temp_voices.remove(new_channel.id)
            except: pass
        bot.loop.create_task(cleanup_unjoined())

class VoiceGeneratorView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Tạo Kênh Thoại Mới", style=discord.ButtonStyle.primary, emoji="🎙️", custom_id="btn_create_voice")
    async def create_voice_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VoiceNameModal())

class RoleButton(discord.ui.Button):
    def __init__(self, role_dict, custom_id_suffix):
        self.role_id = int(role_dict["id"])
        self.role_name = role_dict["name"]
        super().__init__(label=self.role_name, style=discord.ButtonStyle.secondary, custom_id=f"btn_role_{self.role_id}_{custom_id_suffix}")

    async def callback(self, interaction: discord.Interaction):
        guild, member = interaction.guild, interaction.user
        role = guild.get_role(self.role_id)
        if not role:
            return await interaction.response.send_message("❌ Vai trò này không còn khả dụng trên máy chủ.", ephemeral=True)
            
        if role in member.roles:
            try:
                await member.remove_roles(role)
                await interaction.response.send_message(f"✅ Đã gỡ bỏ vai trò **{self.role_name}**.", ephemeral=True)
            except discord.errors.Forbidden:
                await interaction.response.send_message("❌ Bot không đủ quyền để gỡ vai trò này.", ephemeral=True)
        else:
            try:
                await member.add_roles(role)
                await interaction.response.send_message(f"✅ Đã cấp phát vai trò **{self.role_name}**.", ephemeral=True)
            except discord.errors.Forbidden:
                await interaction.response.send_message("❌ Bot không đủ quyền để cấp vai trò này.", ephemeral=True)

class PersistentRoleView(discord.ui.View):
    def __init__(self, roles_data, custom_id):
        super().__init__(timeout=None)
        for r in roles_data:
            self.add_item(RoleButton(r, custom_id))

# Gắn setup_hook để nút bấm không bị tịt sau khi Khởi động lại Bot
async def setup_hook():
    bot.add_view(TicketView())
    bot.add_view(TicketControlView())
    bot.add_view(MusicControlView())
    bot.add_view(VoiceGeneratorView())
    with db_lock:
        cursor.execute("SELECT message_id, roles_json FROM reaction_panels")
        panels = cursor.fetchall()
    for msg_id, rjson in panels:
        try:
            roles_data = json.loads(rjson)
            bot.add_view(PersistentRoleView(roles_data, f"rr_panel_{msg_id}"))
        except: pass
    await bot.tree.sync()

bot.setup_hook = setup_hook

async def export_server_data():
    server_data = {}
    for guild in bot.guilds:
        roles = [{"id": r.id, "name": r.name} for r in guild.roles if r.name != "@everyone"]
        channels = [{"id": c.id, "name": c.name} for c in guild.text_channels]
        categories = [{"id": c.id, "name": c.name} for c in guild.categories]
        server_data[str(guild.id)] = {"name": guild.name, "roles": roles, "channels": channels, "categories": categories}
    with open("roles_list.json", "w", encoding="utf-8") as f:
        json.dump(server_data, f, indent=4, ensure_ascii=False)

@tasks.loop(minutes=1)
async def check_timed_roles():
    now = datetime.datetime.now().timestamp()
    with db_lock:
        cursor.execute("SELECT guild_id, user_id, role_id FROM timed_roles WHERE expires_at <= ?", (now,))
        expired = cursor.fetchall()
        
    for guild_id, user_id, role_id in expired:
        guild = bot.get_guild(int(guild_id))
        if guild:
            member = guild.get_member(int(user_id))
            role = guild.get_role(int(role_id))
            if member and role:
                try: await member.remove_roles(role)
                except: pass
    # BUG FIX: Batch-delete thay vì lock/unlock từng cái trong vòng lặp
    if expired:
        with db_lock:
            cursor.executemany(
                "DELETE FROM timed_roles WHERE guild_id=? AND user_id=? AND role_id=?",
                expired
            )
            conn.commit()

@tasks.loop(seconds=3)
async def check_gui_tasks():
    with db_lock:
        cursor.execute("SELECT id, action, payload FROM gui_tasks")
        tasks_list = cursor.fetchall()
        for t in tasks_list:
            cursor.execute("DELETE FROM gui_tasks WHERE id=?", (t[0],))
        conn.commit()
    
    for task_id, action, payload in tasks_list:
        try:
            if action == "SPAWN_RR_PANEL":
                data = json.loads(payload)
                guild_id = data.get("guild_id")
                channel_id = data.get("channel_id")
                title = data.get("title")
                roles_data = data.get("roles")
                
                guild = bot.get_guild(int(guild_id))
                if guild:
                    channel = guild.get_channel(int(channel_id))
                    if channel:
                        panel_desc = data.get("desc", "Nhấn vào các nút bên dưới để tự cấp / gỡ vai trò cho bản thân.")
                        embed = discord.Embed(
                            title=title,
                            description=panel_desc,
                            color=0x5865F2
                        )
                        # Build grid fields (3 per row - inline)
                        for role_info in roles_data:
                            r_name = role_info.get("name", "?")
                            r_desc = role_info.get("desc", "")
                            field_val = f"• {r_desc}" if r_desc else "• Nhấn nút bên dưới để chọn."
                            embed.add_field(
                                name=f"◆  @{r_name}",
                                value=field_val,
                                inline=True
                            )
                        # Pad to fill last row (Discord shows 3 per row)
                        remainder = len(roles_data) % 3
                        if remainder == 1:
                            embed.add_field(name="\u200b", value="\u200b", inline=True)
                            embed.add_field(name="\u200b", value="\u200b", inline=True)
                        elif remainder == 2:
                            embed.add_field(name="\u200b", value="\u200b", inline=True)
                        
                        footer_text = data.get("footer", "❕ Nhấn nút để nhận thông báo và kết nối với cộng đồng server.")
                        embed.set_footer(text=footer_text)
                        
                        panel_id = str(int(datetime.datetime.now().timestamp() * 1000))
                        custom_id = f"rr_panel_{panel_id}"
                        view = PersistentRoleView(roles_data, custom_id)
                        await channel.send(embed=embed, view=view)
                        
                        with db_lock:
                            cursor.execute("INSERT INTO reaction_panels (message_id, guild_id, roles_json) VALUES (?, ?, ?)", 
                                           (panel_id, guild_id, json.dumps(roles_data)))
                            conn.commit()
        except Exception as e: print(f"Lỗi IPC: {e}")


@bot.event
async def on_ready():
    print(f'[THONG BAO] Bot {bot.user} da Started thanh cong!')
    if not social_media_loop.is_running():
        social_media_loop.start()
    if not check_timed_roles.is_running():
        check_timed_roles.start()
    if not check_gui_tasks.is_running():
        check_gui_tasks.start()
    await export_server_data()
    print("[THONG BAO] Da cap nhat danh sach Role và Channel moi nhat.")

@bot.event
async def on_guild_join(g): await export_server_data()
@bot.event
async def on_guild_remove(g): await export_server_data()
@bot.event
async def on_guild_role_create(r): await export_server_data()
anti_nuke_tracker = {}

async def check_anti_nuke(guild, action_type):
    now = datetime.datetime.now().timestamp()
    bot_member = guild.me
    if not bot_member.guild_permissions.view_audit_log: return
    try:
        action_mapping = {"channel_delete": discord.AuditLogAction.channel_delete, "role_delete": discord.AuditLogAction.role_delete}
        async for entry in guild.audit_logs(action=action_mapping[action_type], limit=1):
            user = entry.user
            if user.bot: return
            
            guild_id = str(guild.id)
            if guild_id not in anti_nuke_tracker: anti_nuke_tracker[guild_id] = {}
            if user.id not in anti_nuke_tracker[guild_id]: anti_nuke_tracker[guild_id][user.id] = []
            
            anti_nuke_tracker[guild_id][user.id] = [t for t in anti_nuke_tracker[guild_id][user.id] if now - t <= 30]
            anti_nuke_tracker[guild_id][user.id].append(now)
            
            if len(anti_nuke_tracker[guild_id][user.id]) >= 3:
                server_cfg = config.get("servers", {}).get(guild_id, config)
                log_channel_id = server_cfg.get("log_channel_id") or server_cfg.get("automod_channel_id")
                if log_channel_id:
                    log_channel = bot.get_channel(int(log_channel_id))
                    if log_channel:
                        embed = discord.Embed(title="🚨 ANTI-NUKE TRIGGERED 🚨", description=f"**{user.name}** đã xóa liên tục kênh/vai trò ({len(anti_nuke_tracker[guild_id][user.id])} lần/30s)!\nHành vi phá hoại đang diễn ra!", color=0x990000)
                        try: await log_channel.send(embed=embed)
                        except: pass
                
                try: # Optional: Remove roles if possible
                    for r in user.roles:
                        if r.name != "@everyone" and bot_member.top_role > r:
                            await user.remove_roles(r)
                except: pass
                anti_nuke_tracker[guild_id][user.id].clear()
            break
    except: pass

@bot.event
async def on_guild_role_delete(r): 
    await export_server_data()
    await check_anti_nuke(r.guild, "role_delete")

@bot.event
async def on_guild_role_update(b, a): await export_server_data()

@bot.event
async def on_guild_channel_create(c): await export_server_data()

@bot.event
async def on_guild_channel_delete(c): 
    await export_server_data()
    await check_anti_nuke(c.guild, "channel_delete")

@bot.event
async def on_guild_channel_update(b, a): await export_server_data()

@bot.event
async def on_message_delete(message):
    if message.author.bot: return
    guild_id = str(message.guild.id) if message.guild else None
    if not guild_id: return
    server_cfg = config.get("servers", {}).get(guild_id, config)
    log_channel_id = server_cfg.get("log_channel_id") or server_cfg.get("automod_channel_id")
    if log_channel_id:
        log_channel = bot.get_channel(int(log_channel_id))
        if log_channel:
            # BUG FIX: message.content có thể là None/rỗng nếu chỉ có ảnh hoặc file đính kèm
            content_display = message.content or "*(Không có nội dung văn bản — có thể là ảnh/file)*"
            embed = discord.Embed(title="🗑️ Tin nhắn bị Xóa", description=content_display[:2000], color=0xFF0000)
            embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
            embed.set_footer(text=f"Kênh: {message.channel.name} | {datetime.datetime.now().strftime('%H:%M:%S')}")
            # Nếu có file đính kèm, liệt kê tên file
            if message.attachments:
                att_list = "\n".join(f"📎 {a.filename}" for a in message.attachments)
                embed.add_field(name="File đính kèm", value=att_list[:1024], inline=False)
            try: await log_channel.send(embed=embed)
            except: pass

@bot.event
async def on_message_edit(before, after):
    if before.author.bot or before.content == after.content: return
    guild_id = str(before.guild.id) if before.guild else None
    if not guild_id: return
    server_cfg = config.get("servers", {}).get(guild_id, config)
    log_channel_id = server_cfg.get("log_channel_id") or server_cfg.get("automod_channel_id")
    if log_channel_id:
        log_channel = bot.get_channel(int(log_channel_id))
        if log_channel:
            embed = discord.Embed(title="📝 Tin nhắn bị Sửa", color=0xFFA500)
            embed.set_author(name=before.author.name, icon_url=before.author.display_avatar.url)
            embed.add_field(name="Trước", value=before.content[:1024] or "None", inline=False)
            embed.add_field(name="Sau", value=after.content[:1024] or "None", inline=False)
            embed.set_footer(text=f"Kênh: {before.channel.name}")
            try: await log_channel.send(embed=embed)
            except: pass

@bot.event
async def on_member_join(member):
    guild_id = str(member.guild.id)
    server_cfg = config.get("servers", {}).get(guild_id, config)
    
    # --- PHẦN 1: TỰ ĐỘNG CẤP ROLE ---
    role_id = server_cfg.get("auto_role_id")
    if role_id:
        role = member.guild.get_role(int(role_id))
        if role:
            try:
                await member.add_roles(role)
                print(f"[THONG BAO] Da cap role {role.name} cho {member.name}")
            except Exception as e:
                print(f"[LOI] Loi cap role: {e}")
                

    # --- PHẦN 2: GỬI CARD CHÀO MỪNG ---
    channel_id = server_cfg.get("welcome_channel_id")
    channel = bot.get_channel(int(channel_id)) if channel_id else None
    
    if channel:
        try:
            # 1. Load Background
            bg_path = server_cfg.get("background_image", "background.png")
            try:
                background = Image.open(bg_path).convert("RGBA")
            except:
                background = Image.new("RGBA", (800, 450), (35, 39, 42, 255))

            # 2. Tải và xử lý Avatar (Phải làm bước này trước khi dán!)
            avatar_url = member.display_avatar.url
            response = requests.get(avatar_url)
            av_size = server_cfg.get("avatar_size", 200)
            avatar = Image.open(BytesIO(response.content)).convert("RGBA").resize((av_size, av_size))
            
            mask = Image.new("L", (av_size, av_size), 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0, av_size, av_size), fill=255)
            avatar.putalpha(mask)

            # 3. Lấy tọa độ từ config và dán (Đã fix tự động resize)
            avg_x = server_cfg.get("avatar_x", 300)
            avg_y = server_cfg.get("avatar_y", 50)
            background.paste(avatar, (avg_x, avg_y), avatar)

            # 5. Gửi ảnh
            with BytesIO() as image_binary:
                background.save(image_binary, "PNG")
                image_binary.seek(0)
                welcome_pattern = server_cfg.get("welcome_message", "🚀 Welcome {mention}!")
                await channel.send(content=welcome_pattern.format(mention=member.mention), 
                                 file=discord.File(fp=image_binary, filename="welcome.png"))
            
            print(f"🖼️ Đã quẩy Card cho {member.name}")
        except Exception as e:
            print(f"❌ Lỗi Card: {e}")

@bot.event
async def on_member_remove(member):
    guild_id = str(member.guild.id)
    server_cfg = config.get("servers", {}).get(guild_id, config)
    channel_id = server_cfg.get("welcome_channel_id")
    channel = bot.get_channel(int(channel_id)) if channel_id else None
    if channel:
        await channel.send(server_cfg.get("leave_message", "{name} đã rời đi.").format(name=member.name))

@bot.event
async def on_member_update(before, after):
    guild = after.guild
    guild_id = str(guild.id)
    server_cfg = config.get("servers", {}).get(guild_id, config)
    
    # Phát hiện Boost mới (premium_since thay đổi từ None -> có giá trị)
    if before.premium_since is None and after.premium_since is not None:
        # 1. Tự động cấp Booster Role
        booster_role_id = server_cfg.get("booster_role_id")
        if booster_role_id:
            booster_role = guild.get_role(int(booster_role_id))
            if booster_role:
                try: await after.add_roles(booster_role)
                except: pass
        
        # 3. Gửi thông báo boost
        boost_channel_id = server_cfg.get("boost_channel_id")
        if boost_channel_id:
            boost_channel = bot.get_channel(int(boost_channel_id))
            if boost_channel:
                boost_msg = server_cfg.get(
                    "boost_message",
                    "🚀 **{mention}** vừa boost server! Cảm ơn vì sự ủng hộ của bạn! 💜"
                ).format(mention=after.mention, name=after.display_name)
                
                embed = discord.Embed(
                    title="💜 SERVER ĐÃ ĐƯỢC BOOST!",
                    description=boost_msg,
                    color=0xFF73FA
                )
                embed.set_author(name=after.display_name, icon_url=after.display_avatar.url)
                embed.set_thumbnail(url=after.display_avatar.url)
                bonus_xp = server_cfg.get("boost_bonus_xp", 500)
                if bonus_xp > 0:
                    db_get_user(str(guild.id), str(after.id))
                    db_update_xp(str(guild.id), str(after.id), bonus_xp)
                    embed.add_field(name="⚡ Phần Thưởng", value=f"+**{bonus_xp:,} XP** đã được nạp vào tài khoản!", inline=False)
                embed.add_field(
                    name="🎉 Server Boost",
                    value=f"Server hiện có **{guild.premium_subscription_count}** boost · Level **{guild.premium_tier}**",
                    inline=False
                )
                embed.set_footer(text="💜 Cảm ơn vì đã ủng hộ server!")
                try:
                    await boost_channel.send(content=after.mention, embed=embed)
                except: pass

temp_voices = set() # Chứa ID của các kênh thoại dùng 1 lần


@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot: return
    
    # 1. Bấm tạo phòng — BUG FIX: lấy tên kênh trigger từ config thay vì hardcode
    if after.channel:
        guild = member.guild
        server_cfg = config.get("servers", {}).get(str(guild.id), config)
        trigger_name = server_cfg.get("voice_trigger_name", "➕ Bấm Tạo Phòng")
        if after.channel.name == trigger_name:
            category = after.channel.category
            new_channel = await guild.create_voice_channel(name=f"🎧 Phòng của {member.display_name}", category=category)
            temp_voices.add(new_channel.id)
            try: await member.move_to(new_channel)
            except: pass
        
    # 2. Huỷ phòng nếu trống (Chờ 60 giây để member chui lại trước khi sập)
    if before.channel and before.channel.id in temp_voices:
        if len(before.channel.members) == 0:
            async def delete_after_delay(channel_id):
                await asyncio.sleep(60)
                try:
                    chan = bot.get_channel(channel_id)
                    if chan and len(chan.members) == 0:
                        await chan.delete()
                        if channel_id in temp_voices: temp_voices.remove(channel_id)
                except: pass
            bot.loop.create_task(delete_after_delay(before.channel.id))

level_cooldown = {}
spam_tracker = {}

@bot.event
async def on_message(message):
    if message.author.bot:
        return
        
    guild_id = str(message.guild.id) if message.guild else None
    if guild_id:
        server_cfg = config.get("servers", {}).get(guild_id, config)
        
        # === PHÂN HỆ CẤP ĐỘ (SQLITE) ===
        user_id = str(message.author.id)
        current_time = time.time()  # BUG FIX: 'import time' đã được chuyển lên đầu file
        if user_id not in level_cooldown or current_time - level_cooldown[user_id] >= 60:
            level_cooldown[user_id] = current_time
            # Đảm bảo record tồn tại
            db_get_user(guild_id, user_id)
            
            earned_xp = random.randint(15, 25)
            
            old_level, new_level = db_update_xp(guild_id, user_id, earned_xp)
            
            if new_level > old_level:
                await message.channel.send(f"🎉 Chúc mừng {message.author.mention}! Cày cuốc chăm chỉ đã giúp bạn đột phá lên **Cấp {new_level}**! 🚀 (+{earned_xp} XP)")
        
        is_mod_or_admin = message.author.guild_permissions.administrator
        if not is_mod_or_admin:
            mod_role_ids = server_cfg.get("mod_role_ids", [])
            old_mod_role_id = server_cfg.get("mod_role_id")
            if old_mod_role_id and old_mod_role_id not in mod_role_ids: mod_role_ids.append(old_mod_role_id)
            user_role_ids = [str(r.id) for r in message.author.roles]
            if any(str(m_id) in user_role_ids for m_id in mod_role_ids):
                is_mod_or_admin = True
                
        if not is_mod_or_admin:
            # BUG FIX: message.content có thể là None (tin nhắn chỉ có ảnh/sticker)
            msg_text = message.content or ""
            # === ANTI-PHISHING / SCAM LINK ===
            SCAM_REGEX = re.compile(r"(discord\.gift\/|steamcommun.*\.com|discorcl\.gift|discordapp\.click|free-nitro|robux-free)", re.IGNORECASE)
            if msg_text and SCAM_REGEX.search(msg_text):
                try: await message.delete()
                except: pass
                try:
                    await message.author.timeout(datetime.timedelta(hours=1), reason="Phát tán Phishing/Scam Link")
                    await message.channel.send(f"🚨 Đã bắt giữ và Timeout {message.author.mention} 1 giờ vì phát tán Link độc hại/Phishing!")
                except: pass
                log_chan = bot.get_channel(int(server_cfg.get("log_channel_id") or 0)) or bot.get_channel(int(server_cfg.get("automod_channel_id") or 0))
                if log_chan:
                    try: await log_chan.send(embed=discord.Embed(title="🚧 SYSTEM: Phishing Detected", description=f"Kẻ phát tán: {message.author.mention}\nNội dung: {message.content}", color=0xFF0000))
                    except: pass
                return
                
            # === ANTI-SPAM (Rate Limit) ===
            if guild_id not in spam_tracker: spam_tracker[guild_id] = {}
            if user_id not in spam_tracker[guild_id]: spam_tracker[guild_id][user_id] = []
            
            now_ts = time.time()
            spam_tracker[guild_id][user_id] = [t for t in spam_tracker[guild_id][user_id] if now_ts - t <= 3.5]
            spam_tracker[guild_id][user_id].append(now_ts)
            
            if len(spam_tracker[guild_id][user_id]) >= 5:
                try: await message.delete()
                except: pass
                try:
                    await message.author.timeout(datetime.timedelta(minutes=5), reason="Spam chat")
                    await message.channel.send(f"🔇 {message.author.mention} đã bị Timeout 5 phút vì chat quá trớn (Spam)!")
                except: pass
                log_chan = bot.get_channel(int(server_cfg.get("log_channel_id") or 0)) or bot.get_channel(int(server_cfg.get("automod_channel_id") or 0))
                if log_chan:
                    try: await log_chan.send(embed=discord.Embed(title="🚧 SYSTEM: Anti-Spam Triggered", description=f"Tội phạm: {message.author.mention} nháy >5 tin / 3.5s", color=0xFFA500))
                    except: pass
                spam_tracker[guild_id][user_id].clear()
                return

        # Đọc blacklist file
        banned_words = []
        path = f"blacklists/{guild_id}.json"
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    banned_words = json.load(f)
            except: pass
            
        if banned_words and not is_mod_or_admin:
            banned_words = [w.strip().lower() for w in banned_words if w.strip()]
            # BUG FIX: dùng msg_text đã được guard None từ trên (nếu in DM thì dùng fallback)
            msg_lower = (message.content or "").lower()
            trigger_word = None
            for word in banned_words:
                if word in msg_lower:
                    trigger_word = word
                    break
            
            if trigger_word:
                try:
                    await message.delete()
                except discord.errors.NotFound:
                    pass
                except Exception as e:
                    print(f"[LOI] Khong the xoa tin nhan AutoMod: {e}")
                
                # Mute
                mute_minutes = server_cfg.get("automod_mute_minutes", 5)
                try:
                    duration = datetime.timedelta(minutes=int(mute_minutes))
                    await message.author.timeout(duration, reason=f"AutoMod: Sử dụng từ cấm ({trigger_word})")
                except Exception as e:
                    print(f"[LOI] Khong the mute AutoMod: {e}")
                
                # Log
                log_channel_id = server_cfg.get("automod_channel_id")
                
                # Giả lập lại embed giao diện Discord AutoMod
                embed = discord.Embed(color=0x2B2D31, description=message.content)
                embed.set_author(name=message.author.name, icon_url=message.author.display_avatar.url)
                embed.set_footer(text=f"Từ khóa: {trigger_word} • Quy tắc: Chặn các từ bị cấm • Lý do: Gửi tin nhắn chứa từ cấm")
                
                log_msg = f"**AutoMod** ☑️ `[CHÍNH THỨC]` đã cách ly một thành viên do sử dụng ngôn từ không phù hợp."
                
                if log_channel_id:
                    log_channel = bot.get_channel(int(log_channel_id))
                    if log_channel:
                        try:
                            await log_channel.send(content=log_msg, embed=embed)
                        except:
                            pass
                else:
                    # Gửi vào chính kênh đó nếu không set kênh
                    try:
                        await message.channel.send(content=log_msg, embed=embed)
                    except:
                        pass
                
                return # Ngưng xử lý các lệnh khác nếu đã bị AutoMod chặn

    await bot.process_commands(message)

# --- LỆNH NHẠC TÙY BIẾN CẤP CAO (QUEUE & AUTOPLAY) ---
music_queues = {}
play_history = {} # Lưu bài cuối để tạo nhạc Autoplay 
autoplay_disabled = set() # Các server đã tắt AutoPlay

def make_music_embed(info, title="Đang Phát"):
    duration = info.get('duration', 0)
    minutes, seconds = divmod(duration, 60)
    embed = discord.Embed(title=f"🎶 {title}", description=f"**[{info.get('title')}]({info.get('webpage_url', '')})**", color=0x5865F2)
    if 'thumbnail' in info: embed.set_thumbnail(url=info['thumbnail'])
    embed.add_field(name="⏱️ Thời lượng", value=f"{minutes}:{seconds:02d}" if duration else "Phát Trực Tiếp")
    embed.add_field(name="👤 Kênh", value=info.get('uploader', 'Không xác định'))
    return embed

def play_next(ctx):
    guild_id = ctx.guild.id
    if guild_id in music_queues and len(music_queues[guild_id]) > 0:
        info = music_queues[guild_id].pop(0)
        play_history[guild_id] = info
        source = discord.FFmpegPCMAudio(info['url'], executable=config.get("ffmpeg_path", "./ffmpeg.exe"), **FFMPEG_OPTIONS)
        ctx.voice_client.play(source, after=lambda e: play_next(ctx))
        coro = ctx.send(embed=make_music_embed(info, "Hàng Đợi Kế Tiếp"), view=MusicControlView())
        asyncio.run_coroutine_threadsafe(coro, bot.loop)
    else:
        # Autoplay Mới: Thuật toán tìm kiếm thông minh liên kết theo Nguồn Gốc + Tên Ca Sĩ (Khắc phục giới hạn YouTube MIX)
        if guild_id in play_history and guild_id not in autoplay_disabled:
            last_song = play_history[guild_id]
            async def auto_play_task():
                status_msg = await ctx.send("🔍 Đang rà đài phát bài ngẫu nhiên cùng phân khúc...")
                def fetch_related():
                    q = f"ytsearch10:{last_song.get('uploader', '')} {last_song.get('title', '').split()[0]} tracks"
                    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                        return ydl.extract_info(q, download=False)
                try:
                    results = await bot.loop.run_in_executor(None, fetch_related)
                    if 'entries' in results and len(results['entries']) > 0:
                        candidates = [e for e in results['entries'] if e.get('id') != last_song.get('id')]
                        if len(candidates) > 0:
                            next_info = random.choice(candidates)
                            play_history[guild_id] = next_info
                            source = discord.FFmpegPCMAudio(next_info['url'], executable=config.get("ffmpeg_path", "./ffmpeg.exe"), **FFMPEG_OPTIONS)
                            ctx.voice_client.play(source, after=lambda e: play_next(ctx))
                            await status_msg.edit(content=None, embed=make_music_embed(next_info, "🎵 Nhạc Đề Xuất (AutoPlay)"), view=MusicControlView())
                            return
                except:
                    pass
                await status_msg.edit(content="⏸️ Hàng đợi trống. (Tạm tắt đề xuất do cạn kho nhạc tương thích).")
            asyncio.run_coroutine_threadsafe(auto_play_task(), bot.loop)


@bot.hybrid_command(name=config.get("cmd_play", "play") or "play")
async def play(ctx, *, search: str):
    if not ctx.author.voice: return await ctx.send("Vào voice đi bạn ơi!")
    
    if ctx.voice_client:
        if ctx.voice_client.channel != ctx.author.voice.channel:
            await ctx.voice_client.move_to(ctx.author.voice.channel)
        vc = ctx.voice_client
    else:
        vc = await ctx.author.voice.channel.connect()
        
    async with ctx.typing():
        status_msg = await ctx.send("🔍 Đang kết nối với vệ tinh âm thanh...")
        def fetch_youtube_data():
            nonlocal search
            # Quét Spotify URL qua web thô để lấy tên Tác Phẩm + Tác Giả 
            if "spoti" in search and search.startswith("http"):
                try:
                    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
                    html = requests.get(search, headers=headers, timeout=5).text
                    t_match = re.search(r'<title>(.*?)</title>', html)
                    if t_match:
                        title_text = t_match.group(1).replace(" - song and lyrics by ", " ")
                        title_text = re.sub(r' \| Spotify$', '', title_text).replace("&#39;", "'").replace("&amp;", "&")
                        search = title_text.strip()
                    else: search = "Spotify unsupported DRM track"
                except: search = "Spotify fallback error"
            
            query = f"ytsearch:{search}" if not search.startswith("http") else search
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl: return ydl.extract_info(query, download=False)
                
        results = await bot.loop.run_in_executor(None, fetch_youtube_data)
        if not results: return await status_msg.edit(content=f"❌ Không tìm thấy bài hát nào!")
        
        if 'entries' in results:
            if len(results['entries']) == 0: return await status_msg.edit(content=f"❌ Không tìm được bài.")
            info = results['entries'][0]
        else:
            info = results
            
    guild_id = ctx.guild.id
    if guild_id not in music_queues: music_queues[guild_id] = []
    
    if vc.is_playing() or vc.is_paused():
        music_queues[guild_id].append(info)
        await status_msg.edit(content=None, embed=make_music_embed(info, f"Danh Sách Chờ (Vị trí thứ {len(music_queues[guild_id])})"))
    else:
        play_history[guild_id] = info
        vc.play(discord.FFmpegPCMAudio(info['url'], executable=config.get("ffmpeg_path", "./ffmpeg.exe"), **FFMPEG_OPTIONS), after=lambda e: play_next(ctx))
        await status_msg.edit(content=None, embed=make_music_embed(info, "Bắt Đầu Phát"), view=MusicControlView())

@bot.hybrid_command(name=config.get("cmd_skip", "skip") or "skip")
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop()
        await ctx.send("⏭️ Đã nhảy bài!")

@bot.hybrid_command(name=config.get("cmd_pause", "pause") or "pause")
async def pause(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.pause()
        await ctx.send("⏸️ Đứng hình mất 5 giây! (Đã Tạm Dừng)")

@bot.hybrid_command(name=config.get("cmd_resume", "resume") or "resume")
async def resume(ctx):
    if ctx.voice_client and ctx.voice_client.is_paused():
        ctx.voice_client.resume()
        await ctx.send("▶️ Dẩy lên nào! (Đã Phát Tiếp)")

@bot.hybrid_command(name=config.get("cmd_stop", "stop") or "stop")
async def stop(ctx):
    if ctx.guild.id in music_queues: music_queues[ctx.guild.id].clear()
    if ctx.voice_client: 
        ctx.voice_client.stop()
        await ctx.voice_client.disconnect()
        await ctx.send("⏹️ Đã cháy máy. Rút phích cắm!")


# --- LỆNH QUẢN TRỊ (MODERATION) ---
def is_mod():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator: return True
        guild_id = str(ctx.guild.id)
        server_cfg = config.get("servers", {}).get(guild_id, config)
        # Hỗ trợ cả mod_role_ids (mảng) lẫn mod_role_id (đơn - legacy)
        mod_role_ids = server_cfg.get("mod_role_ids", [])
        old_mod = server_cfg.get("mod_role_id")
        if old_mod and str(old_mod) not in [str(x) for x in mod_role_ids]:
            mod_role_ids = list(mod_role_ids) + [old_mod]
        if not mod_role_ids: return False
        user_role_ids = [r.id for r in ctx.author.roles]
        return any(int(m) in user_role_ids for m in mod_role_ids)
    return commands.check(predicate)

@bot.hybrid_command(name=config.get("cmd_warn", "warn") or "warn", description="Cảnh cáo thành viên. 3 lần = Mute 10p, 5 lần = Kick.")
@is_mod()
async def warn_user(ctx, member: discord.Member, *, reason: str = "Không có lý do"):
    guild_id, user_id = str(ctx.guild.id), str(member.id)
    with db_lock:
        cursor.execute("SELECT warn_count FROM warnings WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        row = cursor.fetchone()
        warn_count = row[0] + 1 if row else 1
        cursor.execute("INSERT OR REPLACE INTO warnings (guild_id, user_id, warn_count) VALUES (?, ?, ?)", (guild_id, user_id, warn_count))
        conn.commit()
    
    await ctx.send(f"⚠️ **{member.name}** đã bị cảnh cáo lần {warn_count}! Lý do: {reason}")
    
    if warn_count == 3:
        try:
            duration = datetime.timedelta(minutes=10)
            await member.timeout(duration, reason="Phạt cảnh cáo 3 lần")
            await ctx.send(f"🔇 **{member.name}** đã bị tự động Timeout 10 phút do nhận 3 cảnh cáo!")
        except: pass
    elif warn_count >= 5:
        try:
            await member.kick(reason="Phạt cảnh cáo 5 lần")
            await ctx.send(f"🔨 **{member.name}** đã bị tự động Kick khỏi server do nhận 5 cảnh cáo!")
            with db_lock:
                cursor.execute("DELETE FROM warnings WHERE guild_id=? AND user_id=?", (guild_id, user_id))
                conn.commit()
        except: pass

@bot.hybrid_command(name="unwarn", description="Xoá toàn bộ cảnh cáo của một thành viên.")
@is_mod()
async def unwarn_user(ctx, member: discord.Member):
    guild_id, user_id = str(ctx.guild.id), str(member.id)
    with db_lock:
        cursor.execute("DELETE FROM warnings WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        conn.commit()
    await ctx.send(f"✅ Đã xoá sạch toàn bộ cảnh cáo của **{member.name}**. Tờ giấy trắng tinh!") 

@bot.hybrid_command(name="warns", description="Xem số lượng cảnh cáo của một thành viên.")
@is_mod()
async def warns_user(ctx, member: discord.Member):
    guild_id, user_id = str(ctx.guild.id), str(member.id)
    with db_lock:
        cursor.execute("SELECT warn_count FROM warnings WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        row = cursor.fetchone()
    count = row[0] if row else 0
    # BUG FIX: Logic cũ có nhánh 'else' không bao giờ đạt được (count<3 và count>=3 đã cover hết)
    if count == 0:
        status_msg = "✅ Thành viên này chưa có cảnh cáo nào."
    elif count < 3:
        status_msg = f"⚠️ Còn {3 - count} lần nữa sẽ bị Timeout 10 phút."
    elif count < 5:
        status_msg = f"🔇 Còn {5 - count} lần nữa sẽ bị Kick khỏi server!"
    else:
        status_msg = "🔨 Đã đủ 5 cảnh cáo — sẽ bị Kick ngay lần vi phạm tiếp theo!"
    embed = discord.Embed(
        title=f"⚠️ Hồ Sơ Vi Phạm — {member.display_name}",
        description=f"Số cảnh cáo: **{count}/5**\n{status_msg}",
        color=0xFF0000 if count >= 5 else (0xFFA500 if count >= 3 else 0xF1C40F)
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)

@bot.hybrid_command(name=config.get("cmd_timed_role", "timed_role") or "timed_role", description="Cấp vai trò cho người dùng trong thời gian nhất định (Giờ).")
@is_mod()
async def add_timed_role(ctx, member: discord.Member, role: discord.Role, hours: float):
    try:
        await member.add_roles(role)
        expires_at = datetime.datetime.now().timestamp() + (hours * 3600)
        with db_lock:
            cursor.execute("INSERT OR REPLACE INTO timed_roles (guild_id, user_id, role_id, expires_at) VALUES (?, ?, ?, ?)", 
                           (str(ctx.guild.id), str(member.id), str(role.id), expires_at))
            conn.commit()
        await ctx.send(f"⏳ Đã cấp quyền **{role.name}** cho **{member.name}** trong {hours} giờ.")
    except Exception as e:
        await ctx.send(f"❌ Thuật toán thất bại. Bot không có quyền cấp Role này: {e}")

@bot.hybrid_command(name="setup_roles", description="Tạo một bảng Chọn Vai Trò (Tối đa 5 vai trò)")
@is_mod()
async def setup_roles(ctx, title: str, r1: discord.Role, r2: discord.Role=None, r3: discord.Role=None, r4: discord.Role=None, r5: discord.Role=None):
    roles = [r for r in [r1, r2, r3, r4, r5] if r]
    roles_data = [{"id": str(r.id), "name": r.name} for r in roles]
    
    embed = discord.Embed(title=title, description="Sử dụng Menu bên dưới để tự Cấp/Gỡ vai trò cho bản thân nhé!", color=0x3498DB)
    panel_id = str(int(datetime.datetime.now().timestamp() * 1000))
    custom_id = f"rr_panel_{panel_id}"
    view = PersistentRoleView(roles_data, custom_id)
    
    await ctx.send(embed=embed, view=view)
    
    with db_lock:
        cursor.execute("INSERT INTO reaction_panels (message_id, guild_id, roles_json) VALUES (?, ?, ?)", 
                       (panel_id, str(ctx.guild.id), json.dumps(roles_data)))
        conn.commit()

@bot.hybrid_command(name=config.get("cmd_kick", "kick") or "kick")
@is_mod()
async def kick_user(ctx, member: discord.Member, *, reason: str = "Không có lý do"):
    try:
        await member.kick(reason=reason)
        await ctx.send(f"🔨 Đã sút **{member.name}** rời khỏi nhóm! Lý do: {reason}")
    except Exception as e:
        await ctx.send(f"❌ Lỗi: {e}")

@bot.hybrid_command(name=config.get("cmd_mute", "mute") or "mute")
@is_mod()
async def mute_user(ctx, member: discord.Member, minutes: int, *, reason: str = "Không có lý do"):
    try:
        duration = datetime.timedelta(minutes=minutes)
        await member.timeout(duration, reason=reason)
        await ctx.send(f"🔇 Đã cấm ngôn **{member.name}** trong {minutes} phút. Lý do: {reason}")
    except Exception as e:
        await ctx.send(f"❌ Lỗi: {e}")

@bot.hybrid_command(name=config.get("cmd_ban", "ban") or "ban")
@is_mod()
async def ban_user(ctx, member: discord.Member, *, reason: str = "Không có lý do"):
    try:
        await member.ban(reason=reason)
        await ctx.send(f"⛔ Đã tử hình **{member.name}** vĩnh viễn khỏi server! Lời cuối: {reason}")
    except Exception as e:
        await ctx.send(f"❌ Lỗi: {e}")

@bot.hybrid_command(name="unban", description="Gỡ lệnh cấm cho người dùng theo User ID.")
@is_mod()
async def unban_user(ctx, user_id: str, *, reason: str = "Không có lý do"):
    try:
        user = await bot.fetch_user(int(user_id))
        await ctx.guild.unban(user, reason=reason)
        await ctx.send(f"✅ Đã ân xá **{user.name}** khỏi danh sách đen! Lý do: {reason}")
    except discord.NotFound:
        await ctx.send(f"❌ Không tìm thấy User ID `{user_id}` trong danh sách bị ban.")
    except Exception as e:
        await ctx.send(f"❌ Lỗi: {e}")

@bot.hybrid_command(name=config.get("cmd_clear", "clear") or "clear")
@is_mod()
async def clear_messages(ctx, amount: int = 5):
    try:
        await ctx.channel.purge(limit=amount + 1)
        msg = await ctx.send(f"🧹 Đã quét dọn {amount} cọng rác tin nhắn!")
        await asyncio.sleep(4)
        await msg.delete()
    except Exception as e:
        await ctx.send(f"❌ Lỗi quét rác: {e}")

@bot.hybrid_command(name=config.get("cmd_addword", "addword") or "addword")
@is_mod()
async def block_addword(ctx, *, word: str):
    guild_id = str(ctx.guild.id)
    path = f"blacklists/{guild_id}.json"
    os.makedirs("blacklists", exist_ok=True)
    words = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: words = json.load(f)
        except: pass
    word = word.strip().lower()
    if word in words: return await ctx.send(f"⚠️ Từ `{word}` đã tồn tại trong danh sách cấm.")
    words.append(word)
    with open(path, "w", encoding="utf-8") as f: json.dump(words, f, ensure_ascii=False, indent=4)
    await ctx.send(f"✅ Đã thêm `{word}` vào danh sách từ cấm của Server.")

@bot.hybrid_command(name=config.get("cmd_delword", "delword") or "delword")
@is_mod()
async def block_delword(ctx, *, word: str):
    guild_id = str(ctx.guild.id)
    path = f"blacklists/{guild_id}.json"
    words = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f: words = json.load(f)
        except: pass
    word = word.strip().lower()
    if word not in words: return await ctx.send(f"⚠️ Từ `{word}` không nằm trong danh sách cấm.")
    words.remove(word)
    with open(path, "w", encoding="utf-8") as f: json.dump(words, f, ensure_ascii=False, indent=4)
    await ctx.send(f"🗑️ Đã xoá `{word}` khỏi danh sách từ cấm của Server.")

@bot.hybrid_command(name=config.get("cmd_ping", "ping") or "ping")
async def ping_cmd(ctx):
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Tốc độ truyền tải: `{latency}ms`")

@bot.hybrid_command(name="top", description="Bảng xếp hạng XP Top 10 của Server.")
async def leaderboard(ctx):
    guild_id = str(ctx.guild.id)
    with db_lock:
        cursor.execute("SELECT user_id, xp, level FROM users WHERE guild_id=? ORDER BY xp DESC LIMIT 10", (guild_id,))
        rows = cursor.fetchall()
    if not rows:
        return await ctx.send("📊 Chưa có ai tích lũy XP trên server này!")
    
    embed = discord.Embed(title="🏆 BẢNG XẾP HẠNG XP SERVER", color=0xF1C40F)
    medals = ["🥇", "🥈", "🥉"]
    desc = ""
    for i, (uid, xp, lvl) in enumerate(rows):
        medal = medals[i] if i < 3 else f"`#{i+1}`"
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"User#{uid[-4:]}"
        desc += f"{medal} **{name}** — Cấp **{lvl}** · `{xp:,} XP`\n"
    embed.description = desc
    embed.set_footer(text=f"Top 10 thành viên tích cực nhất · {ctx.guild.name}")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="queue", description="Xem danh sách bài đang chờ phát.")
async def queue_cmd(ctx):
    guild_id = ctx.guild.id
    q = music_queues.get(guild_id, [])
    if not q:
        return await ctx.send("📭 Hàng đợi trống rỗng. Dùng lệnh play để thêm bài!")
    embed = discord.Embed(title=f"📋 Danh Sách Chờ — {len(q)} bài", color=0x5865F2)
    for i, info in enumerate(q[:10]):
        duration = info.get('duration', 0)
        mins, secs = divmod(duration, 60)
        dur_str = f"{mins}:{secs:02d}" if duration else "Live"
        embed.add_field(name=f"`#{i+1}` {info.get('title', 'Unknown')[:50]}", value=f"⏱ {dur_str} · 👤 {info.get('uploader', '?')}", inline=False)
    if len(q) > 10:
        embed.set_footer(text=f"... và {len(q)-10} bài nữa")
    await ctx.send(embed=embed)

# (Mod errors moved to bottom)

@bot.hybrid_command(name=config.get("cmd_ticket_setup", "ticket_setup") or "ticket_setup")
@is_mod()
async def ticket_setup(ctx):
    embed = discord.Embed(
        title="🎫 TRUNG TÂM HỖ TRỢ CHIẾN LƯỢC",
        description="Bạn có vấn đề cần giải quyết, muốn khiếu nại hoặc đóng góp ý kiến?\nVui lòng ấn vào nút bên dưới để mở một Phiên Hỗ Trợ bí mật cùng Ban Quản Trị.",
        color=0x2B2D31
    )
    if ctx.guild.icon: embed.set_thumbnail(url=ctx.guild.icon.url)
    await ctx.send(embed=embed, view=TicketView())

@bot.hybrid_command(name=config.get("cmd_rank", "rank") or "rank")
async def rank(ctx, member: discord.Member = None):
    member = member or ctx.author
    guild_id = str(ctx.guild.id)
    user_id = str(member.id)
    
    current_data = db_get_user(guild_id, user_id)
    xp, level = current_data[0], current_data[1]
    
    # BUG FIX: Trước đây tính next_level_xp 3 lần thừa — gộp lại 1 dòng
    next_level_xp = int(100 * (level ** 1.5)) + 100
    
    sorted_users = []
    with db_lock:
        cursor.execute("SELECT user_id, xp FROM users WHERE guild_id=? ORDER BY xp DESC", (guild_id,))
        sorted_users = cursor.fetchall()
        
    rank_pos = next((i + 1 for i, row in enumerate(sorted_users) if row[0] == str(member.id)), "?")

    async with ctx.typing():
        bg = Image.new("RGBA", (800, 250), (43, 45, 49, 255))
        try:
            response = requests.get(member.display_avatar.url)
            avatar = Image.open(BytesIO(response.content)).convert("RGBA").resize((180, 180))
            mask = Image.new("L", (180, 180), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, 180, 180), fill=255)
            bg.paste(avatar, (35, 35), mask)
        except: pass
        
        draw = ImageDraw.Draw(bg)
        try: 
            font_path = config.get("servers", {}).get(guild_id, {}).get("font_file", "")
            if not os.path.exists(font_path): raise Exception
            font_l, font_s = ImageFont.truetype(font_path, 48), ImageFont.truetype(font_path, 28)
        except: 
            font_l = font_s = ImageFont.load_default()
        
        draw.text((250, 40), str(member.name), font=font_l, fill=(255, 255, 255))
        draw.text((250, 100), f"Rank: #{rank_pos}  |  Level: {level}", font=font_s, fill=(185, 187, 190))
        
        bar_x, bar_y, bar_w, bar_h = 250, 170, 500, 30
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=15, fill=(64, 68, 75))
        
        current_lvl_xp = int(100 * ((level-1) ** 1.5)) if level > 1 else 0
        xp_in_level = max(0, xp - current_lvl_xp)
        xp_needed = max(1, next_level_xp - current_lvl_xp)
        progress = min(1.0, xp_in_level / xp_needed)
        fill_w = max(30, int(bar_w * progress))
        draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), radius=15, fill=(88, 101, 242))
        draw.text((bar_x + bar_w - 200, bar_y - 35), f"{xp} / {next_level_xp} XP", font=font_s, fill=(255, 255, 255))

        with BytesIO() as image_binary:
            bg.save(image_binary, "PNG")
            image_binary.seek(0)
            await ctx.send(file=discord.File(fp=image_binary, filename="rank.png"))

@bot.hybrid_command(name=config.get("cmd_profile", "profile") or "profile")
async def profile_cmd(ctx, member: discord.Member = None):
    member = member or ctx.author
    guild_id, user_id = str(ctx.guild.id), str(member.id)
    data = db_get_user(guild_id, user_id)
    xp, level = data[0], data[1]
    
    next_level_xp = int(100 * (level ** 1.5)) + 100
    current_lvl_xp = int(100 * ((level - 1) ** 1.5)) if level > 1 else 0
    xp_in_level = max(0, xp - current_lvl_xp)
    xp_needed = max(1, next_level_xp - current_lvl_xp)
    progress_pct = min(100, int(xp_in_level / xp_needed * 100))
    bar_filled = int(progress_pct / 10)
    bar = "\u2588" * bar_filled + "\u2591" * (10 - bar_filled)
    
    embed = discord.Embed(title=f"\ud83c\udfc6 H\u1ed3 S\u01a1 c\u1ee7a {member.display_name}", color=0x5865F2)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="\ud83c\udf1f Level", value=f"**{level}**", inline=True)
    embed.add_field(name="\u26a1 XP", value=f"**{xp:,}** XP", inline=True)
    embed.add_field(name="\ud83d\udcca Ti\u1ebfn \u0111\u1ed9", value=f"`{bar}` {progress_pct}%\n({xp_in_level}/{xp_needed} XP \u0111\u1ebfn c\u1ea5p {level+1})", inline=False)
    await ctx.send(embed=embed)


@bot.hybrid_command(name=config.get("cmd_setup_voice", "setup_voice") or "setup_voice")
@is_mod()
async def setup_voice(ctx):
    guild = ctx.guild
    server_cfg = config.get("servers", {}).get(str(guild.id), config)
    category_id = server_cfg.get("voice_category_id")
    if category_id: category = guild.get_channel(int(category_id))
    else: category = discord.utils.get(guild.categories, name="TRẠM DỪNG CHÂN")
    
    if not category: category = await guild.create_category("TRẠM DỪNG CHÂN")
    
    embed = discord.Embed(
        title="🎙️ TRẠM THÔNG TIN LIÊN LẠC",
        description="👉 Chào mừng đến với Cục Tần Số.\nNhấn vào Nút bên dưới để đệ đơn xin cấp một Kênh Thoại với tên tùy chỉnh cho riêng bạn nhé!\n*(Chỉ người lập phòng mới có quyền đổi tên/Đuổi người).* ",
        color=0x3498DB
    )
    if ctx.guild.icon: embed.set_thumbnail(url=ctx.guild.icon.url)
    await ctx.send(embed=embed, view=VoiceGeneratorView())

@bot.hybrid_command(name="myvoice")
async def user_create_voice(ctx, limit: int = 0, *, room_name: str = None):
    if not room_name:
        room_name = f"Lãnh địa của {ctx.author.name}"
    
    guild = ctx.guild
    server_cfg = config.get("servers", {}).get(str(guild.id), config)
    category_id = server_cfg.get("voice_category_id")
    if category_id: category = guild.get_channel(int(category_id))
    else: category = discord.utils.get(guild.categories, name="TRẠM DỪNG CHÂN")
    
    if not category: category = await guild.create_category("TRẠM DỪNG CHÂN")
    
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(connect=True),
        ctx.author: discord.PermissionOverwrite(manage_channels=True, connect=True)
    }
    
    new_channel = await guild.create_voice_channel(
        name=f"🎧 {room_name}",
        category=category,
        overwrites=overwrites,
        user_limit=limit
    )
    temp_voices.add(new_channel.id)
    
    await ctx.send(f"✅ Triệu hồi thành công! Phòng của bạn ở đây: {new_channel.mention}\n*(Bạn có toàn quyền đổi tên phòng. Kênh sẽ tự sát sau 60s nếu không ai nói chuyện).*")
    
    async def cleanup_unjoined():
        await asyncio.sleep(60)
        try:
            chan = bot.get_channel(new_channel.id)
            if chan and len(chan.members) == 0:
                await chan.delete()
                if new_channel.id in temp_voices: temp_voices.remove(new_channel.id)
        except: pass
    bot.loop.create_task(cleanup_unjoined())

PLATFORM_EMOJI = {
    "youtube": "▶️",
    "reddit":  "🟧",
    "tiktok":  "🎵",
    "facebook":"🔵",
}

class DoiLinkView(discord.ui.View):
    def __init__(self, platform, link):
        super().__init__(timeout=None)
        emoji = PLATFORM_EMOJI.get(platform, "🔗")
        self.add_item(discord.ui.Button(label=f"Xem trực tiếp trên {platform.capitalize()}", url=link, emoji=emoji))

SCAM_REGEX_GLOBAL = re.compile(r"(discord\.gift\/|steamcommun.*\.com|discorcl\.gift|discordapp\.click|free-nitro|robux-free)", re.IGNORECASE)

@tasks.loop(minutes=5)
async def social_media_loop():
    with db_lock:
        cursor.execute("SELECT guild_id, platform, target_id, channel_id, ping_role, last_post_id FROM social_tracker")
        rows = cursor.fetchall()
        
    for guild_id, platform, target_id, channel_id, ping_role, last_post_id in rows:
        channel = bot.get_channel(int(channel_id))
        if not channel: continue
        new_post_id = last_post_id
        post_data = None
        
        try:
            if platform == "youtube":
                # BUG FIX: wrap blocking requests trong run_in_executor để không block event loop
                def _fetch_yt(): return requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={target_id}", timeout=10)
                resp = await bot.loop.run_in_executor(None, _fetch_yt)
                if resp.status_code == 200:
                    root = ET.fromstring(resp.content)
                    ns = {'yt': 'http://www.youtube.com/xml/schemas/2015', 'ns': 'http://www.w3.org/2005/Atom'}
                    entry = root.find('ns:entry', ns)
                    if entry is not None:
                        video_id = entry.find('yt:videoId', ns).text
                        if video_id != last_post_id:
                            new_post_id = video_id
                            title = entry.find('ns:title', ns).text
                            author = entry.find('ns:author/ns:name', ns).text
                            link = entry.find('ns:link', ns).attrib['href']
                            mgrp = entry.find('{http://search.yahoo.com/mrss/}group')
                            thumb_el = mgrp.find('{http://search.yahoo.com/mrss/}thumbnail') if mgrp else None
                            thumbnail = thumb_el.attrib['url'] if thumb_el is not None else ""
                            post_data = {
                                "title": f"🎥 {author} vừa ra video mới!",
                                "desc": f"**{title}**\n\n👇 Ấn vào liên kết dưới để xem ngay!",
                                "url": link, "color": 0xFF0000, "image": thumbnail
                            }
            elif platform == "reddit":
                def _fetch_reddit(): return requests.get(f"https://www.reddit.com/r/{target_id}/new.json?limit=1", headers={"User-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, timeout=10)
                resp = await bot.loop.run_in_executor(None, _fetch_reddit)
                if resp.status_code == 200:
                    data = resp.json()
                    children = data.get("data", {}).get("children", [])
                    if children:
                        post = children[0]["data"]
                        if post["id"] != last_post_id:
                            new_post_id = post["id"]
                            link = f"https://reddit.com{post['permalink']}"
                            img = post.get("url_overridden_by_dest", "")
                            if not img.endswith(('.png', '.jpg', '.jpeg', '.gif')): img = ""
                            post_data = {
                                "title": f"🟧 Cập nhật r/{target_id} Mới Nóng Hổi!",
                                "desc": f"**{post['title']}**\n✍️ Bởi u/{post['author']}\n\n👇 Nhanh tay vào đọc ngay!",
                                "url": link, "color": 0xFF4500, "image": img
                            }

            elif platform == "tiktok":
                # RSSHub public instance: rsshub.app/tiktok/user/@username
                rss_url = f"https://rsshub.app/tiktok/user/@{target_id}"
                def _fetch_tiktok(): return requests.get(rss_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                resp = await bot.loop.run_in_executor(None, _fetch_tiktok)
                if resp.status_code == 200:
                    root = ET.fromstring(resp.content)
                    chan = root.find('channel')
                    item = chan.find('item') if chan is not None else None
                    if item is not None:
                        vid_link = item.findtext('link', '')
                        vid_id = vid_link.split('/')[-1].split('?')[0]
                        if vid_id and vid_id != last_post_id:
                            new_post_id = vid_id
                            vid_title = item.findtext('title', 'Video mới')
                            # Try to grab thumbnail from enclosure or description img tag
                            enclosure = item.find('enclosure')
                            thumb = enclosure.attrib.get('url', '') if enclosure is not None else ''
                            if not thumb:
                                desc_text = item.findtext('description', '')
                                m_img = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc_text)
                                if m_img: thumb = m_img.group(1)
                            post_data = {
                                "title": f"🎵 @{target_id} vừa đăng video TikTok mới!",
                                "desc": f"**{vid_title}**\n\n👇 Ấn vào xem ngay!",
                                "url": vid_link, "color": 0x010101, "image": thumb
                            }

            elif platform == "facebook":
                # Dùng rss.app free proxy, user phải cung cấp sẵn RSS link từ rss.app
                # target_id ở đây là URL RSS đầy đủ từ rss.app hoặc rssbridge
                def _fetch_fb(): return requests.get(target_id, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                resp = await bot.loop.run_in_executor(None, _fetch_fb)
                if resp.status_code == 200:
                    root = ET.fromstring(resp.content)
                    # Hỗ trợ cả RSS 2.0 và Atom
                    ns_atom = {'a': 'http://www.w3.org/2005/Atom'}
                    entry = root.find('a:entry', ns_atom)
                    if entry is None:
                        chan = root.find('channel')
                        entry = chan.find('item') if chan else None
                        if entry is not None:
                            post_link = entry.findtext('link', '')
                            post_id = entry.findtext('guid', post_link)
                            post_title = entry.findtext('title', 'Bài viết mới')
                            desc_raw = entry.findtext('description', '')
                        else: post_link = post_id = post_title = desc_raw = None
                    else:
                        post_link = entry.findtext('a:link', '', ns_atom) or (entry.find('a:link', ns_atom).attrib.get('href','') if entry.find('a:link', ns_atom) is not None else '')
                        post_id = entry.findtext('a:id', post_link, ns_atom)
                        post_title = entry.findtext('a:title', 'Bài viết mới', ns_atom)
                        desc_raw = entry.findtext('a:summary', '', ns_atom)
                    
                    if post_id and post_id != last_post_id:
                        new_post_id = post_id
                        # Extract image from description html
                        m_img = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc_raw or '')
                        thumb = m_img.group(1) if m_img else ''
                        post_data = {
                            "title": "🔵 Bài viết Facebook mới!",
                            "desc": f"**{post_title}**\n\n👇 Xem trực tiếp tại đây!",
                            "url": post_link, "color": 0x1877F2, "image": thumb
                        }
                            
            if post_data and new_post_id != last_post_id:
                embed = discord.Embed(title=post_data["title"], description=post_data["desc"], color=post_data["color"])
                if post_data["image"]: embed.set_image(url=post_data["image"])
                await channel.send(content=ping_role if ping_role else "", embed=embed, view=DoiLinkView(platform, post_data["url"]))
                with db_lock:
                    cursor.execute("UPDATE social_tracker SET last_post_id=? WHERE guild_id=? AND platform=? AND target_id=?", (new_post_id, guild_id, platform, target_id))
                    conn.commit()
        except Exception as e:
            print(f"[Loop] Lỗi Radar {platform} tại {target_id}: {e}")

@bot.hybrid_command(name="add_social")
@is_mod()
async def add_social(ctx, platform: str, target: str, channel: discord.TextChannel = None, ping_role: discord.Role = None):
    platform = platform.lower()
    SUPPORTED = ["youtube", "reddit", "tiktok", "facebook"]
    if platform not in SUPPORTED: return await ctx.send(f"❌ Máy quét chỉ bắt sóng: `{'`, `'.join(SUPPORTED)}`.")
    channel = channel or ctx.channel
    target_id = target
    
    if platform == "youtube":
        if "youtube.com" in target or "youtu.be" in target:
            m = re.search(r'youtube\.com/channel/(UC[\w-]+)', target)
            if m: target_id = m.group(1)
            else:
                resp = requests.get(target, timeout=10)
                m2 = re.search(r'channel_id=([\w-]+)', resp.text)
                if m2: target_id = m2.group(1)
                else: return await ctx.send("❌ Thất bại: Không thu thập được Channel ID ẩn của liên kết YouTube này.")
    elif platform == "reddit":
        if "reddit.com/r/" in target:
            target_id = target.split("reddit.com/r/")[1].split("/")[0]
    elif platform == "tiktok":
        # Chỉ cần username (không cần @)
        target_id = target.lstrip("@").split("/")[-1].split("?")[0]
    elif platform == "facebook":
        # Facebook: user dán URL RSS từ rss.app hoặc RSS Bridge
        # target_id được lưu nguyên là RSS URL
        await ctx.send("⚠️ **Lưu ý Facebook:** Facebook chặn truy cập thẳng nên bạn cần dùng dịch vụ tạo RSS trước:\n> 1. Vào **rss.app** hoặc **rssbridge** để tạo RSS Link từ trang Facebook.\n> 2. Dán URL RSS vừa tạo làm giá trị āng-ten (target).\nBot sẽ quét RSS link đó mỗi 5 phút.")
        target_id = target  # Toàn bộ RSS URL chính là "target_id"
            
    ping_str = ping_role.mention if ping_role else ""
    with db_lock:
        cursor.execute("INSERT OR REPLACE INTO social_tracker (guild_id, platform, target_id, channel_id, ping_role, last_post_id) VALUES (?, ?, ?, ?, ?, ?)", 
                      (str(ctx.guild.id), platform, target_id, str(channel.id), ping_str, "NO_POST_YET"))
        conn.commit()
    await ctx.send(f"✅ Đã cắm Ăng-ten sóng **{platform.upper()}** (ID: `{target_id}`)! Hễ rục rịch là Bot réo tại {channel.mention}.")

@bot.hybrid_command(name="rm_social")
@is_mod()
async def rm_social(ctx, platform: str, target_id: str):
    with db_lock:
        cursor.execute("DELETE FROM social_tracker WHERE guild_id=? AND platform=? AND target_id=?", (str(ctx.guild.id), platform.lower(), target_id))
        conn.commit()
    await ctx.send(f"🗑️ Đã nhổ Ăng-ten **{platform.upper()}** (ID: `{target_id}`). Ngừng theo dõi.")

@bot.hybrid_command(name="list_social")
async def list_social(ctx):
    with db_lock:
        cursor.execute("SELECT platform, target_id, channel_id FROM social_tracker WHERE guild_id=?", (str(ctx.guild.id),))
        rows = cursor.fetchall()
    if not rows: return await ctx.send("📡 Trạm vô tuyến hiện tại đang rống. Chưa chĩa chảo thu sóng nào.")
    msg = "📡 **CÁC THỤ THỂ RADAR ĐANG BẮT SÓNG TRONG MÁY CHỦ:**\n\n"
    for r in rows:
        c = bot.get_channel(int(r[2]))
        msg += f"• **{r[0].capitalize()}** `[ID: {r[1]}]` ➡ Rót bài vào: {c.mention if c else 'Rác'}\n"
    await ctx.send(msg)

@bot.hybrid_command(name="help")
async def custom_help(ctx):
    prefix = config.get("prefix", "!")
    p = prefix  # shorthand
    
    # Bảng 1: Nhạc & Giải Trí
    embed_music = discord.Embed(title="🎵 NHẠC & GIẢI TRÍ", color=0x5865F2)
    embed_music.add_field(name=f"`{p}{config.get('cmd_play','play')} <tên/link>`", value="Phát nhạc từ YouTube/Spotify. Tự thêm vào hàng đợi nếu đang phát.", inline=False)
    embed_music.add_field(name=f"`{p}{config.get('cmd_skip','skip')}` · `{p}{config.get('cmd_pause','pause')}` · `{p}{config.get('cmd_resume','resume')}` · `{p}{config.get('cmd_stop','stop')}`", value="Điều hướng nhạc cơ bản. Có thể bấm nút trực tiếp trên bảng Nhạc.", inline=False)
    embed_music.add_field(name=f"`{p}queue`", value="Xem danh sách bài đang chờ phát.", inline=False)
    embed_music.add_field(name=f"`{p}ping`", value="Đo độ trễ kết nối.", inline=False)

    # Bảng 2: XP & Cộng đồng
    embed_xp = discord.Embed(title="⚡ XP & CỘNG ĐỒNG", color=0xF1C40F)
    embed_xp.add_field(name=f"`{p}{config.get('cmd_rank','rank')} [@user]`", value="Xem thẻ XP & cấp độ của bản thân hoặc người khác.", inline=False)
    embed_xp.add_field(name=f"`{p}{config.get('cmd_profile','profile')} [@user]`", value="Xem hồ sơ cấp độ chi tiết dạng embed.", inline=False)
    embed_xp.add_field(name=f"`{p}top`", value="Bảng xếp hạng Top 10 XP của server.", inline=False)
    embed_xp.add_field(name=f"`{p}myvoice [số_người] [tên phòng]`", value="Tự tạo kênh thoại riêng (tự xoá khi trống).", inline=False)

    # Bảng 3: Moderation
    embed_mod = discord.Embed(title="🛡️ QUẢN TRỊ & KỶ LUẬT", color=0xED4245, description="*Chỉ dành cho Ban Quản Trị có vai trò Mod hợp lệ.*")
    embed_mod.add_field(name=f"`{p}{config.get('cmd_mute','mute')} @user <phút> [lý do]`", value="Timeout (bịt miệng) thành viên.", inline=False)
    embed_mod.add_field(name=f"`{p}{config.get('cmd_kick','kick')} @user` · `{p}{config.get('cmd_ban','ban')} @user`", value="Kick tạm / Ban vĩnh viễn.", inline=False)
    embed_mod.add_field(name=f"`{p}unban <UserID>`", value="Gỡ lệnh ban cho thành viên theo ID.", inline=False)
    embed_mod.add_field(name=f"`{p}{config.get('cmd_warn','warn')} @user [lý do]`", value="Cảnh cáo thành viên. 3 lần = Timeout 10p, 5 lần = Kick.", inline=False)
    embed_mod.add_field(name=f"`{p}unwarn @user` · `{p}warns @user`", value="Xoá cảnh cáo / Xem hồ sơ vi phạm.", inline=False)
    embed_mod.add_field(name=f"`{p}{config.get('cmd_clear','clear')} <số lượng>`", value="Xoá hàng loạt tin nhắn.", inline=False)
    embed_mod.add_field(name=f"`{p}{config.get('cmd_addword','addword')} <từ>` · `{p}{config.get('cmd_delword','delword')} <từ>`", value="Thêm/Xoá từ khỏi danh sách AutoMod.", inline=False)
    embed_mod.add_field(name=f"`{p}{config.get('cmd_timed_role','timed_role')} @user @role <giờ>`", value="Cấp role tạm thời trong N giờ, tự động thu hồi.", inline=False)

    # Bảng 4: Tiện ích & Setup
    embed_util = discord.Embed(title="🔧 TIỆN ÍCH & THIẾT LẬP", color=0x23A559)
    embed_util.add_field(name=f"`{p}ticket_setup`", value="Tạo panel mở vé hỗ trợ trong kênh hiện tại.", inline=False)
    embed_util.add_field(name=f"`{p}setup_voice`", value="Tạo nút bấm tạo kênh thoại tự động.", inline=False)
    embed_util.add_field(name=f"`{p}setup_roles <tiêu đề> @role1 [@role2...]`", value="Tạo bảng chọn vai trò (tối đa 5 role).", inline=False)
    embed_util.add_field(name=f"`{p}add_social <platform> <link/ID> [#kênh] [@role]`", value="Theo dõi YouTube/Reddit/TikTok/Facebook và thông báo tự động.", inline=False)
    embed_util.add_field(name=f"`{p}list_social` · `{p}rm_social <platform> <ID>`", value="Xem danh sách / Gỡ ăng-ten theo dõi mạng xã hội.", inline=False)

    await ctx.send(embeds=[embed_music, embed_xp, embed_mod, embed_util])

@kick_user.error
@mute_user.error
@ban_user.error
@clear_messages.error
@ticket_setup.error
@setup_voice.error
@warn_user.error
@unwarn_user.error
@warns_user.error
@unban_user.error
@add_timed_role.error
async def mod_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("🛑 Ấy dza! Quyền lực của bạn chỉ bằng 0 so với lệnh này!")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Thiếu tham số! Hãy dùng `{config.get('prefix','!')}help` để xem cú pháp đúng.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Sai định dạng tham số! Hãy chắc chắn mention đúng @User hoặc nhập đúng số.")

# ==================== HTTP API SERVER (GUI REMOTE CONTROL) ====================
API_SECRET = config.get("api_secret", "changeme123")  # Đặt key bí mật trong config.json

async def handle_api(request: web.Request):
    """Endpoint nhận lệnh từ GUI chạy trên máy tính local."""
    # Xác thực API key
    auth = request.headers.get("X-API-Key", "")
    if auth != API_SECRET:
        return web.json_response({"ok": False, "error": "Unauthorized"}, status=401)
    
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
    
    action = data.get("action", "")
    
    # --- Action: SPAWN_RR_PANEL (tạo bảng chọn role) ---
    if action == "SPAWN_RR_PANEL":
        with db_lock:
            cursor.execute(
                "INSERT INTO gui_tasks (action, payload) VALUES (?, ?)",
                ("SPAWN_RR_PANEL", json.dumps(data.get("payload", {})))
            )
            conn.commit()
        return web.json_response({"ok": True, "msg": "Task queued"})
    
    # --- Action: RELOAD_CONFIG (đọc lại config.json) ---
    elif action == "RELOAD_CONFIG":
        global config
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                config = json.load(f)
            return web.json_response({"ok": True, "msg": "Config reloaded"})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)})
    
    # --- Action: STATUS (kiểm tra bot còn sống) ---
    elif action == "STATUS":
        return web.json_response({
            "ok": True,
            "bot": str(bot.user),
            "guilds": len(bot.guilds),
            "latency_ms": round(bot.latency * 1000)
        })
    
    return web.json_response({"ok": False, "error": "Unknown action"}, status=400)

async def start_api_server():
    app = web.Application()
    app.router.add_post("/api", handle_api)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(config.get("api_port", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[API] HTTP API server đang lắng nghe tại cổng {port}")

if __name__ == "__main__":
    token = config.get("token")
    if token:
        loop = asyncio.get_event_loop()
        loop.create_task(start_api_server())
        bot.run(token)
    else: print("❌ Thiếu Token!")