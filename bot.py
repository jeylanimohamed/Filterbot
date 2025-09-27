import os, unicodedata, re, asyncio
import regex as rx
import discord
from discord.ext import commands
from rapidfuzz import fuzz

# ---------------------- CONFIG ----------------------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")  # set this env var
MOD_LOG_CHANNEL_NAME = "mod-log"        # change if needed

# Channels or roles that bypass the filter
BYPASS_CHANNEL_IDS = set()     # e.g., {123456789012345678}
BYPASS_ROLE_IDS = set()        # e.g., {987654321098765432}

# Keep this list private and curated. Include base forms only (lowercase, no accents).
# TIP: Split into categories; keep the absolute worst terms here to avoid false positives.
BANNED_WORDS = {"fuck", "shit", "bitch", "bastard", "asshole", "dick", "pussy",
    "cock", "cunt", "slut", "whore", "adih", "coochie", "vagina", "clit", "effing", "nigga", "🥷", "neeger", "kneeger"
    # examples (do not include here in public code): "word1", "word2", ...
}

# Words/phrases that would otherwise trip substring matches (e.g., place names).
ALLOW_LIST ={
    # A
    "able", "accept", "accomplish", "active", "admire", "advance", "affection", "agree",
    "amazing", "angel", "appreciate", "art", "assist", "athlete",
    # B
    "balance", "balloon", "beautiful", "believe", "benefit", "best", "bless", "brave",
    "brilliant", "buddy",
    # C
    "calm", "care", "celebrate", "charm", "cheer", "clarity", "class", "clean",
    "comfort", "compassion", "confident", "courage", "create", "crystal",
    # D
    "dance", "dazzle", "delight", "devoted", "diamond", "dream", "driven",
    # E
    "earnest", "easy", "educate", "efficient", "effort", "embrace", "enjoy",
    "enlighten", "enthusiasm", "excellent", "explore",
    # F
    "fair", "faith", "fame", "fantastic", "fashion", "fearless", "fine", "flourish",
    "flower", "focus", "freedom", "friend", "fun", "future",
    # G
    "gain", "generous", "genius", "gift", "glad", "glow", "goal", "good", "grace",
    "great", "growth", "guardian",
    # H
    "harmony", "happy", "heal", "heart", "hero", "hope", "hug", "humble", "humor",
    # I
    "idea", "ideal", "imagine", "improve", "independent", "inspire", "intelligent",
    "invent", "invincible", "joy",
    # J
    "jewel", "jolly", "journey", "joyful", "justice",
    # K
    "keen", "kind", "kiss", "knowledge",
    # L
    "laugh", "learn", "legend", "light", "live", "love", "loyal", "lucky",
    # M
    "magic", "magnificent", "marvel", "master", "meaning", "merit", "miracle",
    "motivate", "music",
    # N
    "noble", "nice", "nurture", "nutrition",
    # O
    "okay", "open", "optimistic", "opportunity", "original", "outstanding",
    # P
    "paradise", "passion", "peace", "perfect", "phenomenal", "pleasure", "positive",
    "power", "praise", "precious", "pride", "progress", "pure",
    # Q
    "quality", "queen", "quest", "quick", "quiet",
    # R
    "radiant", "rare", "real", "refresh", "rejoice", "relax", "respect", "reward",
    "right", "rose",
    # S
    "safe", "satisfy", "school", "score", "secure", "serene", "shine", "simple",
    "skill", "smart", "smile", "soul", "spark", "special", "spirit", "star",
    "strength", "success", "sun", "support", "sweet",
    # T
    "talent", "team", "thankful", "thrill", "together", "tranquil", "treasure",
    "true", "trust",
    # U
    "ultimate", "unique", "unity", "unite", "uplift", "useful",
    # V
    "value", "victory", "virtue", "vision", "vital", "vivacious",
    # W
    "warm", "wealth", "welcome", "well", "whole", "win", "wisdom", "wonder",
    # X
    "xenial", "x-factor" ,  # (friendly/positive)
    # Y
    "yearn", "yes", "youth", "yummy",
    # Z
    "zeal", "zen", "zest", "zillion"
    # e.g., "scunthorpe", "assistant"
}

# How many repeats to collapse (cooool → cool, coooooool → cool)
MAX_REPEAT = 2
WARN_DM = (
    "Your message was removed for violating the server’s language policy. "
    "Obfuscated or symbol-replaced profanity is also blocked. If you believe this "
    "was a mistake, please contact the moderators."
)

# ----------------- NORMALIZATION PIPELINE -----------------
ZERO_WIDTH_PATTERN = rx.compile(r"[\u200B-\u200F\u202A-\u202E\u2060\u2066-\u2069\uFEFF]")
COMBINING_MARKS = rx.compile(r"\p{M}+")

LEET_MAP = {
    "4": "a", "@": "a", "Á":"a","Ä":"a","À":"a","Â":"a","Ã":"a","Å":"a",
    "1": "i", "!": "i", "|": "i", "í":"i","ï":"i","ì":"i","î":"i",
    "3": "e", "€":"e","é":"e","ë":"e","è":"e","ê":"e",
    "0": "o", "°":"o","ó":"o","ö":"o","ò":"o","ô":"o","õ":"o",
    "$": "s", "5":"s", "§":"s",
    "7": "t", "+":"t",
     "£": "l", "¡": "i", "ï": "i", "ł": "l",
    "¢": "c", "ç": "c",
    "§": "s", "š": "s",
    "µ": "m",
    "Ð": "d",
    "þ": "p",
    "¥": "y",
    "κ": "k", "к": "k", "Κ": "k",  # Greek/cyrillic homoglyphs
    "ρ": "p", "р": "r", "Р": "r",
    "а": "a", "А": "a"  # Cyrillic a looks like Latin a
}

NON_LETTER = rx.compile(r"[^a-z]")

def normalize_token(token: str) -> str:
    # 1) Unicode normalize & remove zero-width
    s = unicodedata.normalize("NFKC", token)
    s = ZERO_WIDTH_PATTERN.sub("", s)

    # 2) Lowercase early
    s = s.lower()

    # 3) Replace common leet/homoglyphs
    s = "".join(LEET_MAP.get(ch, ch) for ch in s)

    # 4) Remove diacritics
    s = unicodedata.normalize("NFD", s)
    s = COMBINING_MARKS.sub("", s)

    # 5) Collapse long repeats (e.g., f*** → f** ; yooooo → yoo)
    s = rx.sub(r"(.)\1{%d,}" % (MAX_REPEAT), r"\1"*MAX_REPEAT, s)

    # 6) Remove all non-letters
    s = NON_LETTER.sub("", s)
    return s

def message_fingerprint(content: str) -> list[str]:
    # Split on whitespace-ish, normalize each token
    raw_tokens = rx.split(r"\s+", content)
    norm_tokens = [normalize_token(t) for t in raw_tokens if t.strip()]
    # Also create a joined version to catch spacing tricks across tokens
    joined = normalize_token(content)
    return norm_tokens + ([joined] if joined else [])

def is_bypassed(member: discord.Member, channel: discord.abc.GuildChannel) -> bool:
    if channel.id in BYPASS_CHANNEL_IDS:
        return True
    member_role_ids = {r.id for r in getattr(member, "roles", [])}
    return bool(BYPASS_ROLE_IDS & member_role_ids)

def is_allowed(norm: str) -> bool:
    return norm in ALLOW_LIST


def is_banned(norm: str) -> bool:
  # Exact match first (fast)
  if norm in BANNED_WORDS:
    return True

  # Fuzzy match against each banned word
  for w in BANNED_WORDS:
    # Check similarity (0–100)
    score = fuzz.ratio(norm, w)
    if score >= 65:  # tweak threshold: 80–90 works well
      return True
  return False


# ---------------------- BOT SETUP ----------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")

def first_mod_log_channel(guild: discord.Guild):
    for ch in guild.text_channels:
        if ch.name == MOD_LOG_CHANNEL_NAME:
            return ch
    return None

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    if is_bypassed(message.author, message.channel):
        return

    # Build fingerprints and test
    fps = message_fingerprint(message.content)
    flagged = False
    for fp in fps:
        if not fp:
            continue
        if is_allowed(fp):
            continue
        if is_banned(fp):
            flagged = True
            break

    if flagged:
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        except discord.HTTPException:
            pass

        # DM the user (best-effort)
        try:
            await message.author.send(WARN_DM)
        except Exception:
            pass

        # Log to mods
        ch = first_mod_log_channel(message.guild)
        if ch:
            embed = discord.Embed(
                title="Profanity Filter Triggered",
                description=f"**User:** {message.author.mention}\n**Channel:** {message.channel.mention}",
                color=0xE74C3C,
            )
            embed.add_field(name="Original Message", value=message.content[:1000] or "[empty]", inline=False)
            await ch.send(embed=embed)

    else:
        await bot.process_commands(message)

# Simple admin command to test normalization (restricted to admins)
@bot.command(name="norm")
@commands.has_permissions(administrator=True)
async def norm(ctx: commands.Context, *, text: str):
    fps = message_fingerprint(text)
    await ctx.reply(f"Normalized tokens:\n```{fps}```")

bot.run(TOKEN)
