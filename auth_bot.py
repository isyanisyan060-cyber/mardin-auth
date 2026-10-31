import sqlite3
import discord
from discord import app_commands
from discord.ext import commands
from aiohttp import web
import asyncio
import os
import sys
from datetime import datetime, timedelta

# --- AYARLAR ---
BOT_TOKEN = os.environ.get("DISCORD_TOKEN", "")
API_HOST = "0.0.0.0"
API_PORT = int(os.environ.get("PORT", 47820))

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

# Tablolar
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    discord_id TEXT PRIMARY KEY,
    hwid TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    is_killed INTEGER DEFAULT 0
)
""")
conn.commit()

# Eski tablolarda kolonlar eksikse otomatik ekle
for col_def in ["expires_at TIMESTAMP", "is_killed INTEGER DEFAULT 0"]:
    try:
        cursor.execute(f"ALTER TABLE users ADD COLUMN {col_def}")
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
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Mardin 7/24 Canli Kill-Switch"))
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
            INSERT OR REPLACE INTO users (discord_id, hwid, updated_at, expires_at, is_killed)
            VALUES (?, NULL, CURRENT_TIMESTAMP, ?, 0)
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

class KillSwitchModal(discord.ui.Modal, title="Hileyi Canlı Sonlandır (Kill)"):
    discord_id_input = discord.ui.TextInput(
        label="Kullanıcı Discord ID",
        placeholder="Örn: 1188473961139425341",
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            clean_id = self.discord_id_input.value.replace("<@", "").replace(">", "").replace("!", "").strip()
            cursor.execute("UPDATE users SET is_killed = 1 WHERE discord_id = ?", (clean_id,))
            conn.commit()
            await interaction.response.send_message(
                f"🛑 **KILL EMRİ VERİLDİ!**\n<@{clean_id}> kullanıcısının hilesi saniyeler içinde anında kapatılacak ve kendini temizleyecektir.",
                ephemeral=False
            )
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
            cursor.execute("UPDATE users SET hwid = NULL, is_killed = 0, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (clean_id,))
            conn.commit()
            await interaction.response.send_message(
                f"🔄 <@{clean_id}> kullanıcısının HWID kilidi sıfırlandı ve kill durumu kaldırıldı!",
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
            await interaction.response.send_message(f"🗑️ <@{clean_id}> lisansı tamamen silindi. Oyundaysa hilesi otomatik kapanacaktır.", ephemeral=False)
        except Exception as e:
            await interaction.response.send_message(f"❌ Hata: `{str(e)}`", ephemeral=True)

class AuthControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Yeni Lisans Ekle", style=discord.ButtonStyle.green, custom_id="btn_add_lic")
    async def btn_add_lic(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ Sadece yetkililer kullanabilir.", ephemeral=True)
            return
        await interaction.response.send_modal(AddLicenseWithDurationModal())

    @discord.ui.button(label="🛑 Hileyi Kapat (Kill-Switch)", style=discord.ButtonStyle.danger, custom_id="btn_kill_cheat")
    async def btn_kill_cheat(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ Sadece yetkililer kullanabilir.", ephemeral=True)
            return
        await interaction.response.send_modal(KillSwitchModal())

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

        cursor.execute("SELECT discord_id, hwid, expires_at, is_killed FROM users")
        rows = cursor.fetchall()

        if not rows:
            await interaction.response.send_message("Kayıtlı lisans bulunmuyor.", ephemeral=True)
            return

        now = datetime.utcnow()
        embed = discord.Embed(title="📋 Kayıtlı Lisans Listesi", color=0x00FF00)
        desc = ""
        for r in rows:
            d_id, hw, exp_str, killed = r[0], r[1], r[2], r[3]
            hw_status = "✅ Kilitli" if hw else "⏳ F5 Bekliyor"
            state = "🛑 [KAPATILDI]" if killed else "🟢 [AKTİF]"

            if exp_str:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d %H:%M:%S")
                if now > exp_date:
                    dur_info = "❌ **SÜRESİ BİTTİ**"
                else:
                    kalan = exp_date - now
                    dur_info = f"⏳ `{kalan.days}g {kalan.seconds // 3600}sa`"
            else:
                dur_info = "♾️ Süresiz"

            desc += f"• <@{d_id}> (`{d_id}`) | {state} | {hw_status} | {dur_info}\n"

        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🗑️ Lisans Sil", style=discord.ButtonStyle.gray, custom_id="btn_del_license")
    async def btn_del_license(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_admin(interaction):
            await interaction.response.send_message("❌ Sadece yetkililer kullanabilir.", ephemeral=True)
            return
        await interaction.response.send_modal(DeleteLicenseModal())

# --- SLASH KOMUTLARI ---

@bot.tree.command(name="wh", description="Kill-Switch Destekli HWID Auth Panelini açar.")
async def slash_wh(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Bu komutu sadece yetkililer kullanabilir.", ephemeral=True)
        return

    embed = discord.Embed(
        title="🛡️ Mardin Auth Kontrol Paneli (Canlı Kill Destekli)",
        description="**Yönetim Seçenekleri:**\n\n"
                    "• **➕ Yeni Lisans Ekle**: Süreli veya süresiz yeni üyelik açar.\n"
                    "• **🛑 Hileyi Kapat (Kill-Switch)**: Kullanıcı oyundayken bile anında hilesini sonlandırır!\n"
                    "• **🔄 HWID Sıfırla**: Kullanıcının HWID kilidini kaldırır, kill durumunu açar.\n"
                    "• **📜 Kayıtlı Lisanslar**: Kalan süreleri ve aktif/kapalı durumları döker.",
        color=0xED4245
    )
    embed.set_footer(text="Mardin Private Auth • 7/24 Kesintisiz Canlı Koruma")
    await interaction.response.send_message(embed=embed, view=AuthControlView())

@bot.tree.command(name="wh_kill", description="Oyundaki bir kullanıcının hilesini/enjeksiyonunu anında kapatır.")
@app_commands.describe(kullanici="Hilesi kapatılacak kullanıcı (@etiket veya ID)")
async def slash_wh_kill(interaction: discord.Interaction, kullanici: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Yetkiniz yok!", ephemeral=True)
        return

    clean_id = kullanici.replace("<@", "").replace(">", "").replace("!", "").strip()
    cursor.execute("UPDATE users SET is_killed = 1 WHERE discord_id = ?", (clean_id,))
    conn.commit()

    await interaction.response.send_message(
        f"🛑 **KILL EMRİ VERİLDİ!**\n<@{clean_id}> kullanıcısının hilesi saniyeler içinde oyundan düşürülecek ve overlay kapatılacaktır."
    )

@bot.tree.command(name="wh_unkill", description="Kullanıcının kill cezasını kaldırır, hileyi tekrar açmasına izin verir.")
@app_commands.describe(kullanici="Kullanıcı (@etiket veya ID)")
async def slash_wh_unkill(interaction: discord.Interaction, kullanici: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Yetkiniz yok!", ephemeral=True)
        return

    clean_id = kullanici.replace("<@", "").replace(">", "").replace("!", "").strip()
    cursor.execute("UPDATE users SET is_killed = 0 WHERE discord_id = ?", (clean_id,))
    conn.commit()

    await interaction.response.send_message(f"✅ <@{clean_id}> kullanıcısının kill durumu kaldırıldı, tekrar giriş yapabilir.")

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
    INSERT OR REPLACE INTO users (discord_id, hwid, updated_at, expires_at, is_killed)
    VALUES (?, NULL, CURRENT_TIMESTAMP, ?, 0)
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
    cursor.execute("UPDATE users SET hwid = NULL, is_killed = 0, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (clean_id,))
    conn.commit()
    await interaction.response.send_message(f"🔄 <@{clean_id}> kullanıcısının HWID kilidi ve kill durumu sıfırlandı.")

@bot.tree.command(name="wh_sil", description="Kullanıcının lisansını tamamen siler (Oyundaysa otomatik kapatır).")
@app_commands.describe(kullanici="Silinecek kullanıcı (@etiket veya Discord ID)")
async def slash_wh_sil(interaction: discord.Interaction, kullanici: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Yetkiniz yok!", ephemeral=True)
        return

    clean_id = kullanici.replace("<@", "").replace(">", "").replace("!", "").strip()
    cursor.execute("DELETE FROM users WHERE discord_id = ?", (clean_id,))
    conn.commit()
    await interaction.response.send_message(f"🗑️ <@{clean_id}> lisansı tamamen silindi.")

# --- HTTP AUTH & CANLI HEARTBEAT ENDPOINT ---
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

    cursor.execute("SELECT hwid, expires_at, is_killed FROM users WHERE discord_id = ?", (discord_id,))
    row = cursor.fetchone()

    if not row:
        return web.json_response({
            "status": "denied",
            "authorized": False,
            "message": "Lisans bulunamadi veya yetkili tarafindan silindi!"
        }, status=403)

    saved_hwid = row[0]
    expires_at_str = row[1]
    is_killed = row[2]

    # 1. KILL-SWITCH KONTROLÜ (Bot üzerinden kapatıldı mı?)
    if is_killed:
        return web.json_response({
            "status": "killed",
            "authorized": False,
            "message": "Yetkili tarafindan enjeksiyon sonlandirildi (Kill-Switch)!"
        }, status=403)

    # 2. SÜRE KONTROLÜ
    if expires_at_str:
        try:
            exp_time = datetime.strptime(expires_at_str, "%Y-%m-%d %H:%M:%S")
            if datetime.utcnow() > exp_time:
                return web.json_response({
                    "status": "expired",
                    "authorized": False,
                    "message": "Uyelik sureniz doldu! Lutfen yetkili ile iletisime gecin."
                }, status=403)
        except Exception as e:
            print(f"[-] Date parse error: {e}")

    # 3. HWID EŞLEŞTİRME
    if not saved_hwid:
        cursor.execute("UPDATE users SET hwid = ?, updated_at = CURRENT_TIMESTAMP WHERE discord_id = ?", (hwid, discord_id))
        conn.commit()
        print(f"[+] Ilk giris: Discord={discord_id} kullanicisi HWID={hwid} makinesine basariyla kilitlendi!")
        return web.json_response({
            "status": "success",
            "authorized": True,
            "message": "Ilk giris onaylandi, HWID kilitlendi."
        })
    elif saved_hwid == hwid:
        return web.json_response({"status": "success", "authorized": True})
    else:
        return web.json_response({
            "status": "denied",
            "authorized": False,
            "message": "Farkli makine tespit edildi! Baska bir bilgisayara kilitli."
        }, status=403)

async def handle_ping(request):
    return web.json_response({"status": "online", "bot": bot.user.name if bot.user else "connecting"})

async def start_server():
    app = web.Application()
    app.router.add_get("/api/verify", handle_verify)
    app.router.add_get("/api/ping", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, API_HOST, API_PORT)
    await site.start()
    print(f"[+] HTTP Auth API dinleniyor: {API_HOST}:{API_PORT}")

async def main():
    await start_server()
    async with bot:
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[!] Kapatiliyor...")
