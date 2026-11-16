import sqlite3
import hashlib
import discord
from discord import app_commands
from discord.ext import commands
import aiohttp
from aiohttp import web
import asyncio
import os
import sys
from datetime import datetime, timedelta
from typing import Optional

# --- AYARLAR ---
BOT_TOKEN = os.environ.get("DISCORD_TOKEN", "")
API_HOST = "0.0.0.0"
API_PORT = int(os.environ.get("PORT", 47820))

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth.db")
UPDATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "updates")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
JUMPSCARE_DIR = os.path.join(STATIC_DIR, "jumpscare")
os.makedirs(UPDATES_DIR, exist_ok=True)
os.makedirs(JUMPSCARE_DIR, exist_ok=True)
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# Tablolar
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    discord_id TEXT PRIMARY KEY,
    hwid TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
)
""")
conn.commit()

try:
    cursor.execute("ALTER TABLE users ADD COLUMN expires_at TIMESTAMP")
    conn.commit()
except Exception:
    pass

cursor.execute("""
CREATE TABLE IF NOT EXISTS updates (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version TEXT,
    sha256 TEXT,
    filename TEXT,
    file_size INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# Jumpscare / Remote Overlay / Canli Takip Sutunlari
for col, col_type, default_val in [
    ("jumpscare_image_url", "TEXT", "NULL"),
    ("jumpscare_audio_url", "TEXT", "NULL"),
    ("pending_jumpscare", "INTEGER", "0"),
    ("last_triggered_at", "TEXT", "NULL"),
    ("jumpscare_duration", "INTEGER", "4"),
    ("last_seen_at", "TEXT", "NULL")
]:
    try:
        cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type} DEFAULT {default_val}")
        conn.commit()
    except Exception:
        pass

# Eski tablodaki is_killed vs varsa hepsini temizle/resetle
try:
    cursor.execute("UPDATE users SET is_killed = 0")
    conn.commit()
except Exception:
    pass

# Discord Bot
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

def is_admin(interaction: discord.Interaction) -> bool:
    if interaction.guild and interaction.user.guild_permissions.administrator:
        return True
    if interaction.guild and interaction.guild.owner_id == interaction.user.id:
        return True
    if interaction.user.id in [1188473961139425341]:
        return True
    return False

def parse_duration_to_expiry(duration_str: str):
    clean = duration_str.strip().lower()
    if clean in ["0", "-1", "limitsiz", "ömürboyu", "omurboyu", "sinirsiz", "sınırsız", "perm", "lifetime"]:
        return None

    days = 0
    if clean.endswith("g") or clean.endswith("d"):
        days = int(clean[:-1])
    elif clean.endswith("a") or clean.endswith("m"):
        days = int(clean[:-1]) * 30
    elif clean.endswith("y"):
        days = int(clean[:-1]) * 365
    elif clean.endswith("s") or clean.endswith("h"):
        hours = int(clean[:-1])
        return datetime.utcnow() + timedelta(hours=hours)
    else:
        days = int(clean)

    return datetime.utcnow() + timedelta(days=days)

@bot.event
async def on_ready():
    print(f"[+] Bot aktif: {bot.user.name} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()
        print(f"[+] {len(synced)} Slash komutu senkronize edildi.")
    except Exception as e:
        print(f"[-] Slash sync hatasi: {e}")
    try:
        await bot.change_presence(status=discord.Status.online, activity=discord.Activity(type=discord.ActivityType.watching, name="Mardin 7/24 Auth"))
    except Exception as e:
        pass

# --- MODALLAR & MENÜLER ---

class AddLicenseWithDurationModal(discord.ui.Modal, title="Yeni Süreli Lisans Ekle"):
    discord_id_input = discord.ui.TextInput(
        label="Kullanıcı Discord ID",
        placeholder="Örn: 1188473961139425341",
        required=True
    )
    duration_input = discord.ui.TextInput(
        label="Süre (Gün veya 'limitsiz')",
        placeholder="Örn: 1, 7, 30, limitsiz",
        default="30",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            clean_id = self.discord_id_input.value.replace("<@", "").replace(">", "").replace("!", "").strip()
            expiry = parse_duration_to_expiry(self.duration_input.value)
            expiry_str = expiry.strftime("%Y-%m-%d %H:%M:%S") if expiry else None

            cursor.execute("""
            INSERT OR REPLACE INTO users (discord_id, hwid, updated_at, expires_at)
            VALUES (?, NULL, CURRENT_TIMESTAMP, ?)
            """, (clean_id, expiry_str))
            conn.commit()

            dur_text = f"📅 Bitiş: `{expiry_str} UTC`" if expiry_str else "♾️ Süresiz (Lifetime)"

            embed = discord.Embed(
                title="✅ Lisans Başarıyla Oluşturuldu!",
                description=f"👤 **Kullanıcı:** <@{clean_id}> (`{clean_id}`)\n"
                            f"⏳ **Süre:** {dur_text}\n"
                            f"🔑 **Durum:** `[Aktif - F5 Bekleniyor]`",
                color=0x00FF00
            )
            await interaction.response.send_message(embed=embed, ephemeral=False)
        except Exception as e:
            await interaction.response.send_message(f"❌ Hata: `{str(e)}`", ephemeral=True)

class ResetHWIDModal(discord.ui.Modal, title="HWID Sıfırlama (Reset)"):
    discord_id_input = discord.ui.TextInput(
        label="Kullanıcı Discord ID",
        placeholder="Örn: 1188473961139425341",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            clean_id = self.discord_id_input.value.replace("<@", "").replace(">", "").replace("!", "").strip()
            cursor.execute("UPDATE users SET hwid = NULL, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (clean_id,))
            conn.commit()
            await interaction.response.send_message(
                f"🔄 <@{clean_id}> kullanıcısının HWID kilidi sıfırlandı!",
                ephemeral=False
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Hata: `{str(e)}`", ephemeral=True)

class DeleteLicenseModal(discord.ui.Modal, title="Lisans Sil"):
    discord_id_input = discord.ui.TextInput(
        label="Kullanıcı Discord ID",
        placeholder="Örn: 1188473961139425341",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            clean_id = self.discord_id_input.value.replace("<@", "").replace(">", "").replace("!", "").strip()
            cursor.execute("DELETE FROM users WHERE discord_id = ?", (clean_id,))
            conn.commit()
            await interaction.response.send_message(f"🗑️ <@{clean_id}> lisansı tamamen silindi.", ephemeral=False)
        except Exception as e:
            await interaction.response.send_message(f"❌ Hata: `{str(e)}`", ephemeral=True)

def get_user_spotibe_status(last_seen_str):
    if not last_seen_str:
        return False, "⚪ **Hiç açılmadı**"
    try:
        last_dt = datetime.strptime(last_seen_str, "%Y-%m-%d %H:%M:%S")
        diff = (datetime.utcnow() - last_dt).total_seconds()
        if diff <= 8:
            return True, "🟢 **Açık (Online)**"
        elif diff < 60:
            return False, f"🔴 **Kapalı** ({int(diff)} sn önce)"
        elif diff < 3600:
            return False, f"🔴 **Kapalı** ({int(diff // 60)} dk önce)"
        elif diff < 86400:
            return False, f"🔴 **Kapalı** ({int(diff // 3600)} sa önce)"
        else:
            return False, f"🔴 **Kapalı** ({int(diff // 86400)} gün önce)"
    except Exception:
        return False, "⚪ **Bilinmiyor**"

class AuthControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Yeni Lisans Ekle", style=discord.ButtonStyle.green, custom_id="btn_add_lic")
    async def btn_add_lic(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ Sadece yetkililer kullanabilir.", ephemeral=True)
            return
        await interaction.response.send_modal(AddLicenseWithDurationModal())

    @discord.ui.button(label="🔄 HWID Sıfırla (Reset)", style=discord.ButtonStyle.blurple, custom_id="btn_reset_hwid")
    async def btn_reset_hwid(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ Sadece yetkililer kullanabilir.", ephemeral=True)
            return
        await interaction.response.send_modal(ResetHWIDModal())

    @discord.ui.button(label="📜 Kayıtlı Lisanslar & Durumlar", style=discord.ButtonStyle.secondary, custom_id="btn_list_users")
    async def btn_list_users(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ Sadece yetkililer kullanabilir.", ephemeral=True)
            return

        cursor.execute("SELECT discord_id, hwid, expires_at, last_seen_at FROM users")
        rows = cursor.fetchall()

        if not rows:
            await interaction.response.send_message("Kayıtlı lisans bulunmuyor.", ephemeral=True)
            return

        now = datetime.utcnow()
        embed = discord.Embed(title="📋 Kayıtlı Lisans Listesi", color=0x00FF00)
        desc = ""
        for r in rows:
            d_id, hw, exp_str, last_seen = r[0], r[1], r[2], r[3]
            hw_status = "✅ Kilitli" if hw else "⏳ F5 Bekliyor"

            if exp_str:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S")
                if now > exp_date:
                    dur_info = "❌ **SÜRESİ BİTTİ**"
                else:
                    kalan = exp_date - now
                    dur_info = f"⏳ `{kalan.days}g {kalan.seconds // 3600}sa`"
            else:
                dur_info = "♾️ Süresiz"

            is_online, spotibe_str = get_user_spotibe_status(last_seen)
            online_tag = "🟢 Açık" if is_online else "🔴 Kapalı"

            desc += f"• <@{d_id}> (`{d_id}`) | {hw_status} | {dur_info} | {online_tag}\n"

        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🎧 Spotibe Canlı Durumu", style=discord.ButtonStyle.success, custom_id="btn_spotibe_status")
    async def btn_spotibe_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ Sadece yetkililer kullanabilir.", ephemeral=True)
            return

        cursor.execute("SELECT discord_id, hwid, last_seen_at FROM users")
        rows = cursor.fetchall()
        if not rows:
            await interaction.response.send_message("Kayıtlı kullanıcı bulunmuyor.", ephemeral=True)
            return

        embed = discord.Embed(title="🎧 Spotibe Canlı İstemci Durumları", color=0x1DB954)
        desc = ""
        for r in rows:
            d_id, hw, last_seen = r[0], r[1], r[2]
            is_online, status_text = get_user_spotibe_status(last_seen)
            desc += f"• <@{d_id}> (`{d_id}`): {status_text}\n"

        embed.description = desc
        embed.set_footer(text="Spotibe istemcisi açıkken her 1.5 saniyede bir canlı yoklama yapar.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🗑️ Lisans Sil", style=discord.ButtonStyle.gray, custom_id="btn_del_license")
    async def btn_del_license(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ Sadece yetkililer kullanabilir.", ephemeral=True)
            return
        await interaction.response.send_modal(DeleteLicenseModal())

# --- SLASH KOMUTLARI ---

@bot.tree.command(name="wh", description="HWID Auth Panelini açar.")
async def slash_wh(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Bu komutu sadece yetkililer kullanabilir.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🛡️ Mardin Auth Kontrol Paneli",
        description="**Yönetim Seçenekleri:**\n\n"
                    "• **➕ Yeni Lisans Ekle**: Süreli veya süresiz yeni üyelik açar.\n"
                    "• **🔄 HWID Sıfırla**: Kullanıcının HWID kilidini kaldırır.\n"
                    "• **📜 Kayıtlı Lisanslar**: Kalan süreleri ve aktif kullanıcıları döker.\n"
                    "• **🎧 Spotibe Canlı Durumu**: Hedefin Spotibe'si şu an açık mı kapalı mı canlı bakar.",
        color=0xED4245
    )
    embed.set_footer(text="Mardin Private Auth • 7/24 Kesintisiz Koruma")
    await interaction.response.send_message(embed=embed, view=AuthControlView())

@bot.tree.command(name="wh_ekle", description="Bir kullanıcıya gün süreli lisans tanımlar.")
@app_commands.describe(
    kullanici="Lisans verilecek kullanıcı (@etiket veya Discord ID)",
    sure="Lisans süresi: Örn: 1, 7, 30, limitsiz"
)
async def slash_wh_ekle(interaction: discord.Interaction, kullanici: str, sure: str = "30"):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Yetkiniz yok!", ephemeral=True)
        return

    clean_id = kullanici.replace("<@", "").replace(">", "").replace("!", "").strip()
    try:
        expiry = parse_duration_to_expiry(sure)
        expiry_str = expiry.strftime("%Y-%m-%d %H:%M:%S") if expiry else None
    except Exception:
        await interaction.response.send_message("❌ Geçersiz süre formatı! Örnek: `7`, `30`, `limitsiz`", ephemeral=True)
        return

    cursor.execute("""
    INSERT OR REPLACE INTO users (discord_id, hwid, updated_at, expires_at)
    VALUES (?, NULL, CURRENT_TIMESTAMP, ?)
    """, (clean_id, expiry_str))
    conn.commit()

    dur_text = f"📅 Bitiş: `{expiry_str} UTC`" if expiry_str else "♾️ Süresiz (Lifetime)"
    embed = discord.Embed(
        title="✅ Lisans Başarıyla Oluşturuldu!",
        description=f"👤 **Kullanıcı:** <@{clean_id}> (`{clean_id}`)\n"
                    f"⏳ **Süre:** {dur_text}\n"
                    f"🔑 **Durum:** `[İlk Girişte HWID Otomatik Kilitlenecek]`",
        color=0x00FF00
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="wh_sure_uzat", description="Mevcut bir kullanıcının süresini uzatır.")
@app_commands.describe(
    kullanici="Kullanıcı (@etiket veya ID)",
    eklenecek_gun="Eklenecek gün sayısı (Örn: 30)"
)
async def slash_wh_sure_uzat(interaction: discord.Interaction, kullanici: str, eklenecek_gun: int):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Yetkiniz yok!", ephemeral=True)
        return

    clean_id = kullanici.replace("<@", "").replace(">", "").replace("!", "").strip()
    cursor.execute("SELECT expires_at FROM users WHERE discord_id = ?", (clean_id,))
    row = cursor.fetchone()

    if not row:
        await interaction.response.send_message("❌ Bu kullanıcının kayıtlı lisansı bulunamadı.", ephemeral=True)
        return

    now = datetime.utcnow()
    exp_str = row[0]
    if exp_str:
        curr_exp = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S")
        base_time = curr_exp if curr_exp > now else now
        new_exp = base_time + timedelta(days=eklenecek_gun)
    else:
        new_exp = now + timedelta(days=eklenecek_gun)

    new_exp_str = new_exp.strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE users SET expires_at = ? WHERE discord_id = ?", (new_exp_str, clean_id))
    conn.commit()

    await interaction.response.send_message(f"✅ <@{clean_id}> süresi uzatıldı! Yeni Bitiş: `{new_exp_str} UTC`")

@bot.tree.command(name="wh_sifirla", description="Kullanıcının HWID kilidini kaldırır.")
@app_commands.describe(kullanici="Sıfırlanacak kullanıcı (@etiket veya Discord ID)")
async def slash_wh_sifirla(interaction: discord.Interaction, kullanici: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Yetkiniz yok!", ephemeral=True)
        return

    clean_id = kullanici.replace("<@", "").replace(">", "").replace("!", "").strip()
    cursor.execute("UPDATE users SET hwid = NULL, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (clean_id,))
    conn.commit()
    await interaction.response.send_message(f"🔄 <@{clean_id}> kullanıcısının HWID kilidi sıfırlandı.")

@bot.tree.command(name="wh_sil", description="Kullanıcının lisansını tamamen siler.")
@app_commands.describe(kullanici="Silinecek kullanıcı (@etiket veya Discord ID)")
async def slash_wh_sil(interaction: discord.Interaction, kullanici: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Yetkiniz yok!", ephemeral=True)
        return

    clean_id = kullanici.replace("<@", "").replace(">", "").replace("!", "").strip()
    cursor.execute("DELETE FROM users WHERE discord_id = ?", (clean_id,))
    conn.commit()
    await interaction.response.send_message(f"🗑️ <@{clean_id}> lisansı tamamen silindi.")

@bot.tree.command(name="spotibe_durum", description="Hedef kullanıcının Spotibe'sinin açık olup olmadığını kontrol eder.")
@app_commands.describe(kullanici="Durumu sorgulanacak kullanıcı (@etiket veya Discord ID)")
async def slash_spotibe_durum(interaction: discord.Interaction, kullanici: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Bu komutu sadece yetkililer kullanabilir.", ephemeral=True)
        return

    clean_id = kullanici.replace("<@", "").replace(">", "").replace("!", "").strip()
    cursor.execute("SELECT last_seen_at, hwid FROM users WHERE discord_id = ?", (clean_id,))
    row = cursor.fetchone()
    if not row:
        await interaction.response.send_message(f"❌ <@{clean_id}> veritabanında kayıtlı değil!", ephemeral=True)
        return

    last_seen, hwid = row[0], row[1]
    is_online, status_text = get_user_spotibe_status(last_seen)

    color = 0x2ECC71 if is_online else 0xE74C3C
    embed = discord.Embed(
        title="🎧 Spotibe Canlı Durum Sorgusu",
        description=f"👤 **Kullanıcı:** <@{clean_id}> (`{clean_id}`)\n"
                    f"🖥️ **Spotibe Durumu:** {status_text}\n"
                    f"🔒 **HWID Kilit:** `{'Kilitli' if hwid else 'Serbest / Boş'}`\n\n"
                    + ("⚡ *Kullanıcı şu an Spotibe'yi kullanıyor. Jumpscare veya anlık eylemler anında iletilir.*" if is_online else "⚠️ *Spotibe şu an kapalı. Açıldığı anda bekleyen bildirimler tetiklenir.*"),
        color=color
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="guncelleme_yukle", description="Spotibe / hile icin guncel DLL yukler.")
@app_commands.describe(
    dosya="Yuklenecek DLL dosyasi (orn: bcrypt.dll)",
    versiyon="Surum numarasi (orn: 1.0.1, 1.0.2)"
)
async def slash_guncelleme_yukle(interaction: discord.Interaction, dosya: discord.Attachment, versiyon: str = "latest"):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Yetkiniz yok!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    file_bytes = await dosya.read()
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    file_name = dosya.filename or "bcrypt.dll"

    target_path = os.path.join(UPDATES_DIR, "bcrypt.dll")
    with open(target_path, "wb") as f:
        f.write(file_bytes)

    cursor.execute("""
    INSERT OR REPLACE INTO updates (id, version, sha256, filename, file_size, updated_at)
    VALUES (1, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    """, (versiyon, file_hash, file_name, len(file_bytes)))
    conn.commit()

    embed = discord.Embed(
        title="🚀 Yeni Guncelleme Yayina Alindi!",
        description=f"📦 **Dosya:** `{file_name}`\n"
                    f"🏷️ **Surum:** `{versiyon}`\n"
                    f"📊 **Boyut:** `{len(file_bytes):,} bytes`\n"
                    f"🔒 **SHA-256:** `{file_hash}`\n\n"
                    f"Istemciler bir sonraki acilista bu guncellemeyi otomatik olarak cekecektir.",
        color=0x00FF88
    )
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="guncelleme_durum", description="Su an yayinda olan DLL guncellemesini gosterir.")
async def slash_guncelleme_durum(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Yetkiniz yok!", ephemeral=True)
        return

    cursor.execute("SELECT version, sha256, filename, file_size, updated_at FROM updates WHERE id = 1")
    row = cursor.fetchone()
    if not row:
        await interaction.response.send_message("ℹ️ Henuz yayinda bir guncelleme dosyasi yok.", ephemeral=True)
        return

    version, server_hash, filename, file_size, updated_at = row
    embed = discord.Embed(
        title="ℹ️ Mevcut Guncelleme Durumu",
        description=f"📦 **Dosya:** `{filename}`\n"
                    f"🏷️ **Surum:** `{version}`\n"
                    f"📊 **Boyut:** `{file_size:,} bytes`\n"
                    f"🔒 **SHA-256:** `{server_hash}`\n"
                    f"📅 **Yuklenme Tarihi:** `{updated_at} UTC`",
        color=0x3498DB
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="jumpscare", description="Kullaniciya anlik tam ekran jumpscare overlay ve ses bildirimi tetikler.")
@app_commands.describe(
    kullanici="Hedef kullanici (@etiket veya Discord ID)",
    medya="Tam ekran gosterilecek video (.mp4) veya resim (.png, .jpg) - 10MB alti",
    link="Veya video/resim URL linki (Discord 10MB dosya limitini asmak icin)",
    ses="Calinacak ses dosyasi (.mp3, .wav) - MP4 video sectiyseniz bos birakabilirsiniz",
    sure="Ekranda kalma suresi (saniye cinsinden, varsayilan 4)"
)
async def slash_jumpscare(
    interaction: discord.Interaction,
    kullanici: str,
    medya: Optional[discord.Attachment] = None,
    link: Optional[str] = None,
    ses: Optional[discord.Attachment] = None,
    sure: Optional[int] = 4
):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Bu komutu sadece yoneticiler kullanabilir!", ephemeral=True)
        return

    if not medya and not link:
        await interaction.response.send_message("❌ Lutfen bir `medya` dosyasi yukleyin veya bir `link` belirtin!", ephemeral=True)
        return

    clean_id = kullanici.replace("<@", "").replace(">", "").replace("!", "").strip()
    cursor.execute("SELECT discord_id FROM users WHERE discord_id = ?", (clean_id,))
    if not cursor.fetchone():
        await interaction.response.send_message(f"❌ <@{clean_id}> kullanicisi veritabaninda kayitli degil!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    clean_sure = max(1, min(60, sure or 4))
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "https://mardin-auth.onrender.com").rstrip("/")

    try:
        if medya:
            med_ext = os.path.splitext(medya.filename)[1].lower() or ".mp4"
            med_filename = f"jump_med_{clean_id}{med_ext}"
            med_path = os.path.join(JUMPSCARE_DIR, med_filename)
            med_bytes = await medya.read()
            if not med_bytes:
                await interaction.followup.send("❌ Medya dosyasi bos veya okunamadi!", ephemeral=True)
                return
            with open(med_path, "wb") as f:
                f.write(med_bytes)
            med_url = f"{base_url}/static/jumpscare/{med_filename}"
        else:
            # Link ile yukleme (Discord 10MB sınırını aşmak için)
            clean_link = link.strip().strip("<>\"'")
            parsed_ext = os.path.splitext(clean_link.split("?")[0])[1].lower() or ".mp4"
            med_ext = parsed_ext
            med_filename = f"jump_med_{clean_id}{med_ext}"
            med_path = os.path.join(JUMPSCARE_DIR, med_filename)

            async with aiohttp.ClientSession() as session:
                async with session.get(clean_link, timeout=aiohttp.ClientTimeout(total=45)) as resp:
                    if resp.status != 200:
                        await interaction.followup.send(f"❌ Belirtilen linkten dosya indirilemedi! (HTTP {resp.status})", ephemeral=True)
                        return
                    med_bytes = await resp.read()
                    with open(med_path, "wb") as f:
                        f.write(med_bytes)
            med_url = f"{base_url}/static/jumpscare/{med_filename}"

        aud_url = None
        if ses:
            aud_ext = os.path.splitext(ses.filename)[1].lower() if ses else ".mp3"
            aud_filename = f"jump_audio_{clean_id}{aud_ext or '.mp3'}"
            aud_path = os.path.join(JUMPSCARE_DIR, aud_filename)
            aud_bytes = await ses.read()
            with open(aud_path, "wb") as f:
                f.write(aud_bytes)
            aud_url = f"{base_url}/static/jumpscare/{aud_filename}"

        now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            UPDATE users 
            SET jumpscare_image_url = ?, 
                jumpscare_audio_url = ?, 
                jumpscare_duration = ?,
                pending_jumpscare = 1,
                last_triggered_at = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE discord_id = ?
        """, (med_url, aud_url, clean_sure, now_iso, clean_id))
        conn.commit()

        aud_desc = f"[Dinle]({aud_url})" if aud_url else "*Video ic ses kullaniliyor*"
        embed = discord.Embed(
            title="🎯 Canlı Jumpscare / Overlay Tetiklendi",
            description=f"**Hedef:** <@{clean_id}> (`{clean_id}`)\n\n"
                        f"🎬 **Medya:** [Önizle]({med_url}) (`{med_ext}`)\n"
                        f"🔊 **Ses:** {aud_desc}\n"
                        f"⏱️ **Süre:** `{clean_sure} saniye`\n\n"
                        f"⚡ **Canlı Tetikleme:** Spotibe açıksa istemci ~1-2 saniye içinde otomatik patlayacaktır.",
            color=0x2ECC71
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        print(f"[+] Canli Jumpscare kuruldu: target={clean_id}, med={med_url}, aud={aud_url}, sure={clean_sure}s")
    except Exception as e:
        await interaction.followup.send(f"❌ Hata olustu: {str(e)}", ephemeral=True)

# --- HTTP AUTH ENDPOINT ---
async def handle_verify(request):
    hwid = request.query.get("hwid", "").strip()
    discord_id = request.query.get("discord_id", "").strip()

    if not discord_id:
        return web.json_response({
            "status": "denied",
            "authorized": False,
            "message": "Baglanti hatasi! Lutfen uygulamayi tekrar baslatin."
        }, status=403)

    if not hwid:
        return web.json_response({"status": "error", "authorized": False, "message": "HWID eksik"}, status=400)

    cursor.execute("SELECT hwid, expires_at, pending_jumpscare, jumpscare_image_url, jumpscare_audio_url FROM users WHERE discord_id = ?", (discord_id,))
    row = cursor.fetchone()

    if not row:
        return web.json_response({
            "status": "denied",
            "authorized": False,
            "message": "Lisans bulunamadi! Yetkili tarafindan eklenmemis."
        }, status=403)

    saved_hwid = row[0]
    expires_at_str = row[1]
    pending_jump = bool(row[2]) if len(row) > 2 and row[2] else False
    jump_img = row[3] if len(row) > 3 and row[3] else None
    jump_aud = row[4] if len(row) > 4 and row[4] else None

    # SÜRE KONTROLÜ
    days_left = -1
    is_lifetime = True
    if expires_at_str:
        try:
            exp_time = datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M:%S")
            now = datetime.utcnow()
            if now > exp_time:
                return web.json_response({
                    "status": "expired",
                    "authorized": False,
                    "message": "Uyelik sureniz doldu! Lutfen yetkili ile iletisime gecin."
                }, status=403)
            diff = exp_time - now
            days_left = max(0, diff.days + (1 if diff.seconds > 0 else 0))
            is_lifetime = False
        except Exception as e:
            print(f"[-] Date parse error: {e}")

    # Kullanıcı profil bilgilerini Discord API'sinden çek
    username = "User"
    avatar_url = ""
    try:
        user_id_int = int(discord_id)
        user_obj = bot.get_user(user_id_int)
        if not user_obj:
            user_obj = await bot.fetch_user(user_id_int)
        if user_obj:
            username = user_obj.display_name or user_obj.name
            if user_obj.display_avatar:
                avatar_url = str(user_obj.display_avatar.with_format("png").with_size(64).url)
    except Exception as e:
        print(f"[-] Discord user fetch error: {e}")

    # HWID EŞLEŞTİRME & Canli Takip
    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE users SET last_seen_at = ? WHERE discord_id = ?", (now_iso, discord_id))
    conn.commit()

    if not saved_hwid:
        cursor.execute("UPDATE users SET hwid = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (hwid, discord_id))
        conn.commit()
        print(f"[+] Ilk giris: Discord={discord_id} kullanicisi HWID={hwid} makinesine basariyla kilitlendi!")
        return web.json_response({
            "status": "success",
            "authorized": True,
            "days_left": days_left,
            "is_lifetime": is_lifetime,
            "username": username,
            "avatar_url": avatar_url,
            "jumpscare": pending_jump,
            "jumpscare_image_url": jump_img if pending_jump else None,
            "jumpscare_audio_url": jump_aud if pending_jump else None,
            "message": "Ilk giris onaylandi, HWID kilitlendi."
        })
    elif saved_hwid == hwid:
        return web.json_response({
            "status": "success",
            "authorized": True,
            "days_left": days_left,
            "is_lifetime": is_lifetime,
            "username": username,
            "avatar_url": avatar_url,
            "jumpscare": pending_jump,
            "jumpscare_image_url": jump_img if pending_jump else None,
            "jumpscare_audio_url": jump_aud if pending_jump else None
        })
    else:
        return web.json_response({
            "status": "denied",
            "authorized": False,
            "message": "Farkli makine tespit edildi! Baska bir bilgisayara kilitli."
        }, status=403)

async def handle_root(request):
    return web.json_response({
        "status": "online",
        "service": "Mardin Auth System 24/7",
        "bot": bot.user.name if bot.user else "connecting"
    })

async def handle_ping(request):
    return web.json_response({"status": "online", "bot": bot.user.name if bot.user else "connecting"})

async def keep_alive_task():
    await bot.wait_until_ready()
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "https://mardin-auth.onrender.com")
    ping_url = f"{render_url}/api/ping"
    print(f"[+] Keep-alive aktif edildi: {ping_url}")
    while not bot.is_closed():
        await asyncio.sleep(300)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(ping_url, timeout=15) as resp:
                    print(f"[KeepAlive] Self ping status: {resp.status}")
        except Exception as e:
            print(f"[KeepAlive] Self ping error: {e}")


async def handle_check_update(request):
    client_hash = request.query.get("hash", "").strip().lower()
    cursor.execute("SELECT version, sha256, filename, file_size FROM updates WHERE id = 1")
    row = cursor.fetchone()
    if not row:
        return web.json_response({
            "status": "success",
            "has_update": False,
            "message": "Henuz guncelleme yayinlanmadi."
        })

    version, server_hash, filename, file_size = row
    server_hash = server_hash.lower()

    has_update = (client_hash != server_hash) if client_hash else True
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    dl_url = f"{base_url}/api/download_update" if base_url else "/api/download_update"

    return web.json_response({
        "status": "success",
        "has_update": has_update,
        "version": version,
        "sha256": server_hash,
        "file_size": file_size,
        "filename": filename,
        "download_url": dl_url
    })

async def handle_download_update(request):
    target_path = os.path.join(UPDATES_DIR, "bcrypt.dll")
    if not os.path.exists(target_path):
        return web.Response(text="Guncelleme dosyasi bulunamadi", status=404)

    return web.FileResponse(
        path=target_path,
        headers={
            "Content-Disposition": 'attachment; filename="bcrypt.dll"',
            "Content-Type": "application/octet-stream"
        }
    )

async def handle_poll_events(request):
    """
    Istemcinin 1-2 saniyede bir yokladigi ultra-hafif canli event endpoint'i.
    pending_jumpscare == 1 ise tek seferlik veriyi doner ve aninda sifirlar (Atomic).
    """
    hwid = request.query.get("hwid", "").strip()
    discord_id = request.query.get("discord_id", "").strip()

    if not hwid and not discord_id:
        return web.json_response({"event": "none"})

    # Spotibe canli kalp atisi (Heartbeat): last_seen_at guncelle
    now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        UPDATE users 
        SET last_seen_at = ? 
        WHERE (hwid = ? AND ? != '') OR (discord_id = ? AND ? != '')
    """, (now_iso, hwid, hwid, discord_id, discord_id))
    conn.commit()

    cursor.execute("""
        SELECT pending_jumpscare, jumpscare_image_url, jumpscare_audio_url, jumpscare_duration, discord_id 
        FROM users 
        WHERE (hwid = ? AND ? != '') OR (discord_id = ? AND ? != '')
    """, (hwid, hwid, discord_id, discord_id))
    row = cursor.fetchone()

    if not row or not row[0]:
        return web.json_response({"event": "none"})

    pending, img_url, aud_url, duration, target_dc_id = row
    duration = duration or 4

    # Atomic clear: Tekrarlayan patlamalari onlemek icin tek seferde resetle
    cursor.execute("""
        UPDATE users 
        SET pending_jumpscare = 0, jumpscare_image_url = NULL, jumpscare_audio_url = NULL 
        WHERE discord_id = ?
    """, (target_dc_id,))
    conn.commit()

    print(f"[+] Poll Event tetiklendi: target={target_dc_id}, sure={duration}s")
    return web.json_response({
        "event": "trigger_overlay",
        "image_url": img_url,
        "audio_url": aud_url,
        "duration": duration
    })

async def handle_acknowledge_jumpscare(request):
    discord_id = request.query.get("discord_id", "").strip()
    hwid = request.query.get("hwid", "").strip()

    if not discord_id and not hwid:
        return web.json_response({"status": "error", "message": "discord_id veya hwid eksik"}, status=400)

    cursor.execute("""
        UPDATE users 
        SET pending_jumpscare = 0, jumpscare_image_url = NULL, jumpscare_audio_url = NULL 
        WHERE (discord_id = ? AND ? != '') OR (hwid = ? AND ? != '')
    """, (discord_id, discord_id, hwid, hwid))
    conn.commit()

    print(f"[+] Jumpscare acknowledge edildi: discord_id={discord_id}, hwid={hwid}")
    return web.json_response({"status": "success", "message": "Jumpscare resetlendi"})

async def start_server():
    app = web.Application()
    app.router.add_static("/static", path=STATIC_DIR, name="static")
    app.router.add_get("/", handle_root)
    app.router.add_get("/api/verify", handle_verify)
    app.router.add_get("/api/ping", handle_ping)
    app.router.add_get("/api/poll_events", handle_poll_events)
    app.router.add_get("/api/check_update", handle_check_update)
    app.router.add_get("/api/download_update", handle_download_update)
    app.router.add_get("/api/acknowledge_jumpscare", handle_acknowledge_jumpscare)
    app.router.add_post("/api/acknowledge_jumpscare", handle_acknowledge_jumpscare)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, API_HOST, API_PORT)
    await site.start()
    print(f"[+] HTTP Auth API dinleniyor: {API_HOST}:{API_PORT}")

async def main():
    await start_server()
    asyncio.create_task(keep_alive_task())
    async with bot:
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[!] Kapatiliyor...")
