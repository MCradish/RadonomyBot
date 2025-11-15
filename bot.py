# ============================================
#  RadonomyBot – Radcoin + Slash-экономика
# ============================================

import os
import sqlite3
import datetime as dt
import random
from typing import Optional, List, Tuple

import discord
from discord.ext import commands, tasks
from discord import app_commands

DB_PATH = "radonomy.sqlite3"
DEFAULT_PREFIX = "/"
DEFAULT_PRICE = 100.0

# ================== БАЗА ДАННЫХ ===================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id            INTEGER PRIMARY KEY,
            prefix              TEXT    NOT NULL DEFAULT '/',
            economy_channel_id  INTEGER,
            price               REAL    NOT NULL DEFAULT 100,
            random_events       INTEGER NOT NULL DEFAULT 1,
            event_interval_min  INTEGER NOT NULL DEFAULT 60,
            last_event_ts       TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS balances (
            guild_id    INTEGER NOT NULL,
            user_id     INTEGER NOT NULL,
            wallet      REAL    NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS price_history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id  INTEGER NOT NULL,
            ts_utc    TEXT    NOT NULL,
            price     REAL    NOT NULL
        )
        """
    )

    # доходы по ролям для /collect-income
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS income_roles (
            guild_id  INTEGER NOT NULL,
            role_id   INTEGER NOT NULL,
            amount    REAL    NOT NULL,
            PRIMARY KEY (guild_id, role_id)
        )
        """
    )

    # кулдауны для work / rob / crime / slut / collect-income
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_timers (
            guild_id  INTEGER NOT NULL,
            user_id   INTEGER NOT NULL,
            name      TEXT    NOT NULL,
            last_ts   TEXT    NOT NULL,
            PRIMARY KEY (guild_id, user_id, name)
        )
        """
    )

    conn.commit()
    conn.close()


def ensure_guild_row(guild_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT guild_id FROM guild_settings WHERE guild_id = ?", (guild_id,))
    if cur.fetchone() is None:
        cur.execute(
            "INSERT INTO guild_settings (guild_id, prefix, price) VALUES (?, ?, ?)",
            (guild_id, DEFAULT_PREFIX, DEFAULT_PRICE),
        )
        conn.commit()
    conn.close()


def get_prefix_for_guild(guild_id: Optional[int]) -> str:
    if guild_id is None:
        return DEFAULT_PREFIX
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT prefix FROM guild_settings WHERE guild_id = ?", (guild_id,))
    row = cur.fetchone()
    conn.close()
    return row["prefix"] if row else DEFAULT_PREFIX


def set_prefix_for_guild(guild_id: int, prefix: str):
    ensure_guild_row(guild_id)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE guild_settings SET prefix = ? WHERE guild_id = ?",
        (prefix, guild_id),
    )
    conn.commit()
    conn.close()


def get_price(guild_id: int) -> float:
    ensure_guild_row(guild_id)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT price FROM guild_settings WHERE guild_id = ?", (guild_id,))
    row = cur.fetchone()
    conn.close()
    return float(row["price"])


def set_price(guild_id: int, new_price: float):
    ensure_guild_row(guild_id)
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE guild_settings SET price = ? WHERE guild_id = ?",
        (new_price, guild_id),
    )
    cur.execute(
        "INSERT INTO price_history (guild_id, ts_utc, price) VALUES (?, ?, ?)",
        (guild_id, dt.datetime.utcnow().isoformat(), new_price),
    )
    conn.commit()
    conn.close()


def change_price(guild_id: int, delta: float) -> float:
    price = get_price(guild_id)
    new_price = max(1.0, price + delta)
    set_price(guild_id, new_price)
    return new_price


def get_balance(guild_id: int, user_id: int) -> float:
    """Баланс на руках (cash)."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT wallet FROM balances WHERE guild_id = ? AND user_id = ?",
        (guild_id, user_id),
    )
    row = cur.fetchone()
    if row is None:
        wallet = 0.0
        cur.execute(
            "INSERT INTO balances (guild_id, user_id, wallet) VALUES (?, ?, ?)",
            (guild_id, user_id, wallet),
        )
        conn.commit()
    else:
        wallet = float(row["wallet"])
    conn.close()
    return wallet


def set_balance(guild_id: int, user_id: int, amount: float):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO balances (guild_id, user_id, wallet)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id, user_id) DO UPDATE SET wallet = excluded.wallet
        """,
        (guild_id, user_id, amount),
    )
    conn.commit()
    conn.close()


# ---------- доходы по ролям ----------

def set_income_role(guild_id: int, role_id: int, amount: float):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO income_roles (guild_id, role_id, amount)
        VALUES (?, ?, ?)
        ON CONFLICT(guild_id, role_id) DO UPDATE SET amount = excluded.amount
        """,
        (guild_id, role_id, amount),
    )
    conn.commit()
    conn.close()


def get_income_for_member(guild_id: int, member: discord.Member) -> float:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT role_id, amount FROM income_roles WHERE guild_id = ?", (guild_id,))
    rows = cur.fetchall()
    conn.close()
    role_ids = {r.id for r in member.roles}
    income = 0.0
    for row in rows:
        if row["role_id"] in role_ids:
            income += float(row["amount"])
    return income


# ---------- кулдауны ----------

def get_last_timer(guild_id: int, user_id: int, name: str) -> Optional[dt.datetime]:
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT last_ts FROM user_timers WHERE guild_id = ? AND user_id = ? AND name = ?",
        (guild_id, user_id, name),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    try:
        return dt.datetime.fromisoformat(row["last_ts"])
    except Exception:
        return None


def update_timer(guild_id: int, user_id: int, name: str):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_timers (guild_id, user_id, name, last_ts)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(guild_id, user_id, name) DO UPDATE SET last_ts = excluded.last_ts
        """,
        (guild_id, user_id, name, dt.datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def check_cooldown(
    guild_id: int, user_id: int, name: str, cooldown_seconds: int
) -> Tuple[bool, int]:
    last = get_last_timer(guild_id, user_id, name)
    if last is None:
        return True, 0
    now = dt.datetime.utcnow()
    diff = (now - last).total_seconds()
    if diff >= cooldown_seconds:
        return True, 0
    return False, int(cooldown_seconds - diff)


# ============= РАНДОМНЫЕ СОБЫТИЯ КУРСА =============

RANDOM_EVENTS = [
    ("На рынок завезли редкие артефакты", +8, 15),
    ("Караван был ограблен бандитами", -8, -15),
    ("Маги стабилизировали экономику", -3, +3),
    ("Слухи о войне подняли спрос", +5, +12),
    ("Нашли огромный клад Radcoin", -10, -20),
    ("Торговая ярмарка прошла успешно", +2, +6),
    ("Урожай провалился, люди продают активы", -6, -12),
    ("Королевский указ об укреплении валюты", +4, +9),
]


def apply_random_event(guild_id: int) -> str:
    text, p_min, p_max = random.choice(RANDOM_EVENTS)
    percent = random.uniform(p_min, p_max)
    price = get_price(guild_id)
    delta = price * (percent / 100.0)
    new_price = change_price(guild_id, delta)
    sign = "📈" if delta > 0 else "📉"
    return f"{sign} {text}. Изменение: {percent:+.1f}% | Новый курс: {new_price:.2f} RC"


# ================= Discord BOT =====================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


async def prefix_callable(bot: commands.Bot, message: discord.Message):
    guild_id = message.guild.id if message.guild else None
    prefix = get_prefix_for_guild(guild_id)
    prefixes: List[str] = [prefix]
    if bot.user:
        prefixes.append(f"<@{bot.user.id}> ")
        prefixes.append(f"<@!{bot.user.id}> ")
    return prefixes


class RadonomyBot(commands.Bot):
    async def setup_hook(self):
        await self.tree.sync()
        print("Slash-команды синхронизированы.")


bot = RadonomyBot(command_prefix=prefix_callable, intents=intents)


def is_guild_admin(inter: discord.Interaction) -> bool:
    return (
        inter.guild is not None
        and isinstance(inter.user, discord.Member)
        and inter.user.guild_permissions.administrator
    )


def in_guild_only_prefix():
    async def predicate(ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("Эта команда работает только на сервере.")
            return False
        return True
    return commands.check(predicate)


def admin_only_prefix():
    async def predicate(ctx: commands.Context):
        if ctx.guild is None:
            return False
        if ctx.author.guild_permissions.administrator:
            return True
        await ctx.send("Требуются права администратора сервера.")
        return False
    return commands.check(predicate)


# ============== СОБЫТИЯ ===================

@bot.event
async def on_ready():
    print(f"RadonomyBot запущен как {bot.user} (ID: {bot.user.id})")
    for guild in bot.guilds:
        ensure_guild_row(guild.id)
    random_events_loop.start()


@bot.event
async def on_guild_join(guild: discord.Guild):
    ensure_guild_row(guild.id)


# ============== ПРЕФИКС КОМАНДЫ (Radcoin) ==============

@bot.command(name="price")
@in_guild_only_prefix()
async def cmd_price(ctx: commands.Context):
    price = get_price(ctx.guild.id)
    prefix = get_prefix_for_guild(ctx.guild.id)
    embed = discord.Embed(
        title="📊 Курс Radcoin",
        description=f"Текущий курс: **{price:.2f} RC**",
        colour=discord.Colour.gold(),
    )
    embed.set_footer(text=f"Используйте {prefix}buy / {prefix}sell для торговли.")
    await ctx.send(embed=embed)


@bot.command(name="balance")
@in_guild_only_prefix()
async def cmd_balance_prefix(ctx: commands.Context, member: Optional[discord.Member] = None):
    member = member or ctx.author
    bal = get_balance(ctx.guild.id, member.id)
    await ctx.send(f"💰 Баланс {member.mention}: **{bal:.2f} RC**")


@bot.command(name="buy")
@in_guild_only_prefix()
async def cmd_buy_prefix(ctx: commands.Context, amount: float):
    if amount <= 0:
        await ctx.send("Сумма должна быть больше нуля.")
        return
    gid = ctx.guild.id
    uid = ctx.author.id
    price = get_price(gid)
    bal = get_balance(gid, uid)
    new_bal = bal + amount
    set_balance(gid, uid, new_bal)
    delta = price * 0.01 * (amount / 100)
    new_price = change_price(gid, delta)
    await ctx.send(
        f"✅ {ctx.author.mention} купил **{amount:.2f} RC**.\n"
        f"Новый баланс: **{new_bal:.2f} RC**\n"
        f"Курс вырос до **{new_price:.2f} RC**"
    )


@bot.command(name="sell")
@in_guild_only_prefix()
async def cmd_sell_prefix(ctx: commands.Context, amount: float):
    if amount <= 0:
        await ctx.send("Сумма должна быть больше нуля.")
        return
    gid = ctx.guild.id
    uid = ctx.author.id
    bal = get_balance(gid, uid)
    if amount > bal:
        await ctx.send("У тебя нет столько Radcoin.")
        return
    price = get_price(gid)
    new_bal = bal - amount
    set_balance(gid, uid, new_bal)
    delta = -price * 0.01 * (amount / 100)
    new_price = change_price(gid, delta)
    await ctx.send(
        f"✅ {ctx.author.mention} продал **{amount:.2f} RC**.\n"
        f"Новый баланс: **{new_bal:.2f} RC**\n"
        f"Курс упал до **{new_price:.2f} RC**"
    )


@bot.command(name="radhelp")
@in_guild_only_prefix()
async def cmd_radhelp_prefix(ctx: commands.Context):
    prefix = get_prefix_for_guild(ctx.guild.id)
    embed = discord.Embed(
        title="📘 Radonomy / Radcoin — помощь",
        description=f"Текущий префикс: `{prefix}`",
        colour=discord.Colour.blurple(),
    )
    embed.add_field(
        name="Префикс-команды",
        value=(
            f"`{prefix}price`, `{prefix}balance`, `{prefix}buy`, `{prefix}sell`"
        ),
        inline=False,
    )
    embed.add_field(
        name="Slash-команды",
        value="`/price`, `/balance`, `/buy`, `/sell`, `/work`, `/rob`, `/crime`, `/slut`, `/collect-income`, `/top-cash`, `/radsettings ...`",
        inline=False,
    )
    await ctx.send(embed=embed)


# ============== SLASH-КОМАНДЫ Radcoin ==============

@bot.tree.command(name="price", description="Показать текущий курс Radcoin")
async def slash_price(inter: discord.Interaction):
    if inter.guild is None:
        await inter.response.send_message("Только на сервере.", ephemeral=True)
        return
    price = get_price(inter.guild.id)
    embed = discord.Embed(
        title="📊 Курс Radcoin",
        description=f"Текущий курс: **{price:.2f} RC**",
        colour=discord.Colour.gold(),
    )
    await inter.response.send_message(embed=embed)


@bot.tree.command(name="balance", description="Показать баланс Radcoin")
@app_commands.describe(member="Чей баланс показать (если не указать – ваш)")
async def slash_balance(inter: discord.Interaction, member: Optional[discord.Member] = None):
    if inter.guild is None:
        await inter.response.send_message("Только на сервере.", ephemeral=True)
        return
    member = member or inter.user
    bal = get_balance(inter.guild.id, member.id)
    await inter.response.send_message(
        f"💰 Баланс {member.mention}: **{bal:.2f} RC**",
        ephemeral=(member.id == inter.user.id),
    )


@bot.tree.command(name="buy", description="Купить Radcoin")
@app_commands.describe(amount="Количество Radcoin")
async def slash_buy(inter: discord.Interaction, amount: float):
    if inter.guild is None:
        await inter.response.send_message("Только на сервере.", ephemeral=True)
        return
    if amount <= 0:
        await inter.response.send_message("Сумма должна быть > 0.", ephemeral=True)
        return
    gid = inter.guild.id
    uid = inter.user.id
    price = get_price(gid)
    bal = get_balance(gid, uid)
    new_bal = bal + amount
    set_balance(gid, uid, new_bal)
    delta = price * 0.01 * (amount / 100)
    new_price = change_price(gid, delta)
    await inter.response.send_message(
        f"✅ Куплено **{amount:.2f} RC**.\nБаланс: **{new_bal:.2f} RC**\nКурс: **{new_price:.2f} RC**",
        ephemeral=True,
    )


@bot.tree.command(name="sell", description="Продать Radcoin")
@app_commands.describe(amount="Количество Radcoin")
async def slash_sell(inter: discord.Interaction, amount: float):
    if inter.guild is None:
        await inter.response.send_message("Только на сервере.", ephemeral=True)
        return
    if amount <= 0:
        await inter.response.send_message("Сумма должна быть > 0.", ephemeral=True)
        return
    gid = inter.guild.id
    uid = inter.user.id
    bal = get_balance(gid, uid)
    if amount > bal:
        await inter.response.send_message("У тебя нет столько Radcoin.", ephemeral=True)
        return
    price = get_price(gid)
    new_bal = bal - amount
    set_balance(gid, uid, new_bal)
    delta = -price * 0.01 * (amount / 100)
    new_price = change_price(gid, delta)
    await inter.response.send_message(
        f"✅ Продано **{amount:.2f} RC**.\nБаланс: **{new_bal:.2f} RC**\nКурс: **{new_price:.2f} RC**",
        ephemeral=True,
    )


@bot.tree.command(name="radhelp", description="Список команд RadonomyBot")
async def slash_radhelp(inter: discord.Interaction):
    prefix = DEFAULT_PREFIX if inter.guild is None else get_prefix_for_guild(inter.guild.id)
    embed = discord.Embed(
        title="📘 Radonomy / Radcoin — помощь",
        colour=discord.Colour.blurple(),
    )
    embed.add_field(
        name="Slash-команды (экономика)",
        value=(
            "`/price`, `/balance`, `/buy`, `/sell`, `/work`, `/rob`, `/crime`, "
            "`/slut`, `/collect-income`, `/top-cash`, `/radsettings ...`"
        ),
        inline=False,
    )
    embed.add_field(
        name="Префикс-команды",
        value=f"`{prefix}price`, `{prefix}balance`, `{prefix}buy`, `{prefix}sell`, `{prefix}radhelp`",
        inline=False,
    )
    await inter.response.send_message(embed=embed, ephemeral=True)


# ============ SLASH ГРУППА /radsettings ============

class RadSettings(app_commands.Group):
    @app_commands.command(name="prefix", description="Изменить префикс текстовых команд")
    @app_commands.describe(new_prefix="Новый префикс (до 5 символов)")
    async def prefix(self, inter: discord.Interaction, new_prefix: str):
        if inter.guild is None:
            await inter.response.send_message("Только на сервере.", ephemeral=True)
            return
        if not is_guild_admin(inter):
            await inter.response.send_message("Нужны права администратора.", ephemeral=True)
            return
        if len(new_prefix) > 5:
            await inter.response.send_message("Префикс максимум 5 символов.", ephemeral=True)
            return
        set_prefix_for_guild(inter.guild.id, new_prefix)
        await inter.response.send_message(
            f"✅ Префикс изменён на `{new_prefix}`.", ephemeral=True
        )

    @app_commands.command(name="price", description="Жёстко установить курс Radcoin")
    @app_commands.describe(new_price="Новый курс (> 0)")
    async def price(self, inter: discord.Interaction, new_price: float):
        if inter.guild is None:
            await inter.response.send_message("Только на сервере.", ephemeral=True)
            return
        if not is_guild_admin(inter):
            await inter.response.send_message("Нужны права администратора.", ephemeral=True)
            return
        if new_price <= 0:
            await inter.response.send_message("Курс должен быть > 0.", ephemeral=True)
            return
        set_price(inter.guild.id, new_price)
        await inter.response.send_message(
            f"⚠ Курс установлен на **{new_price:.2f} RC**.", ephemeral=True
        )

    @app_commands.command(name="events", description="Вкл/выкл рандомные события курса")
    @app_commands.describe(mode="on / off")
    async def events(self, inter: discord.Interaction, mode: str):
        if inter.guild is None:
            await inter.response.send_message("Только на сервере.", ephemeral=True)
            return
        if not is_guild_admin(inter):
            await inter.response.send_message("Нужны права администратора.", ephemeral=True)
            return
        mode = mode.lower()
        if mode not in ("on", "off"):
            await inter.response.send_message("Используй `on` или `off`.", ephemeral=True)
            return
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE guild_settings SET random_events = ? WHERE guild_id = ?",
            (1 if mode == "on" else 0, inter.guild.id),
        )
        conn.commit()
        conn.close()
        await inter.response.send_message(
            f"✅ Рандомные события теперь **{'включены' if mode == 'on' else 'выключены'}**.",
            ephemeral=True,
        )

    @app_commands.command(name="interval", description="Интервал рандомных событий курса")
    @app_commands.describe(minutes="Минуты (минимум 5)")
    async def interval(self, inter: discord.Interaction, minutes: int):
        if inter.guild is None:
            await inter.response.send_message("Только на сервере.", ephemeral=True)
            return
        if not is_guild_admin(inter):
            await inter.response.send_message("Нужны права администратора.", ephemeral=True)
            return
        if minutes < 5:
            await inter.response.send_message("Минимум 5 минут.", ephemeral=True)
            return
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE guild_settings SET event_interval_min = ? WHERE guild_id = ?",
            (minutes, inter.guild.id),
        )
        conn.commit()
        conn.close()
        await inter.response.send_message(
            f"✅ Интервал установлен на **{minutes} минут**.", ephemeral=True
        )


bot.tree.add_command(RadSettings(name="radsettings", description="Настройки RadonomyBot"))


# ============ SLASH-ЭКОНОМИКА: work / rob / crime / slut ============

WORK_CD = 60 * 5      # 5 мин
CRIME_CD = 60 * 7     # 7 мин
SLUT_CD = 60 * 7      # 7 мин
ROB_CD = 60 * 10      # 10 мин
INCOME_CD = 60 * 30   # 30 мин для collect-income


def format_cd(sec: int) -> str:
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}ч {m}м"
    if m:
        return f"{m}м {s}с"
    return f"{s}с"


@bot.tree.command(name="work", description="Пойти поработать и заработать немного RC")
async def slash_work(inter: discord.Interaction):
    if inter.guild is None:
        await inter.response.send_message("Только на сервере.", ephemeral=True)
        return
    gid, uid = inter.guild.id, inter.user.id
    ok, left = check_cooldown(gid, uid, "work", WORK_CD)
    if not ok:
        await inter.response.send_message(
            f"⏳ Ты уже работал, подожди ещё **{format_cd(left)}**.", ephemeral=True
        )
        return
    reward = random.randint(30, 120)
    bal = get_balance(gid, uid)
    set_balance(gid, uid, bal + reward)
    update_timer(gid, uid, "work")
    await inter.response.send_message(
        f"💼 Ты поработал и получил **{reward} RC**. Теперь у тебя **{bal + reward:.2f} RC**.",
        ephemeral=True,
    )


@bot.tree.command(name="crime", description="Рискованное дело: можно много заработать или потерять")
async def slash_crime(inter: discord.Interaction):
    if inter.guild is None:
        await inter.response.send_message("Только на сервере.", ephemeral=True)
        return
    gid, uid = inter.guild.id, inter.user.id
    ok, left = check_cooldown(gid, uid, "crime", CRIME_CD)
    if not ok:
        await inter.response.send_message(
            f"⏳ Команда /crime ещё на кд: **{format_cd(left)}**.", ephemeral=True
        )
        return
    bal = get_balance(gid, uid)
    success = random.random() < 0.55  # 55% успеха
    if success:
        reward = random.randint(80, 260)
        set_balance(gid, uid, bal + reward)
        text = f"🧨 Преступление удалось! Ты сорвал куш **{reward} RC**.\nБаланс: **{bal + reward:.2f} RC**"
    else:
        loss = min(bal, random.randint(40, 140))
        set_balance(gid, uid, bal - loss)
        text = f"🚔 Тебя поймали! Штраф **{loss} RC**.\nБаланс: **{bal - loss:.2f} RC**"
    update_timer(gid, uid, "crime")
    await inter.response.send_message(text, ephemeral=True)


@bot.tree.command(name="slut", description="Грязные делишки за RC (высокий риск, средняя награда)")
async def slash_slut(inter: discord.Interaction):
    if inter.guild is None:
        await inter.response.send_message("Только на сервере.", ephemeral=True)
        return
    gid, uid = inter.guild.id, inter.user.id
    ok, left = check_cooldown(gid, uid, "slut", SLUT_CD)
    if not ok:
        await inter.response.send_message(
            f"⏳ Команда /slut ещё на кд: **{format_cd(left)}**.", ephemeral=True
        )
        return
    bal = get_balance(gid, uid)
    success = random.random() < 0.6
    if success:
        reward = random.randint(50, 200)
        set_balance(gid, uid, bal + reward)
        text = f"💋 Ты очаровал клиента и получил **{reward} RC**.\nБаланс: **{bal + reward:.2f} RC**"
    else:
        loss = min(bal, random.randint(20, 100))
        set_balance(gid, uid, bal - loss)
        text = f"💀 Всё пошло не по плану, ты потерял **{loss} RC**.\nБаланс: **{bal - loss:.2f} RC**"
    update_timer(gid, uid, "slut")
    await inter.response.send_message(text, ephemeral=True)


@bot.tree.command(name="rob", description="Попробовать ограбить другого игрока")
@app_commands.describe(target="Кого ограбить")
async def slash_rob(inter: discord.Interaction, target: discord.Member):
    if inter.guild is None:
        await inter.response.send_message("Только на сервере.", ephemeral=True)
        return
    if target.bot or target.id == inter.user.id:
        await inter.response.send_message("Нельзя ограбить этого пользователя.", ephemeral=True)
        return
    gid = inter.guild.id
    uid = inter.user.id
    ok, left = check_cooldown(gid, uid, "rob", ROB_CD)
    if not ok:
        await inter.response.send_message(
            f"⏳ /rob ещё на кд: **{format_cd(left)}**.", ephemeral=True
        )
        return

    bal_robber = get_balance(gid, uid)
    bal_target = get_balance(gid, target.id)

    if bal_target < 50:
        await inter.response.send_message(
            "У цели почти нет денег, грабить нечего.", ephemeral=True
        )
        return

    success = random.random() < 0.5
    if success:
        stolen = int(bal_target * random.uniform(0.15, 0.35))
        stolen = max(20, stolen)
        stolen = min(stolen, bal_target)
        set_balance(gid, target.id, bal_target - stolen)
        set_balance(gid, uid, bal_robber + stolen)
        text = (
            f"🔫 Ты успешно ограбил {target.mention} и забрал **{stolen} RC**!\n"
            f"Твой баланс: **{bal_robber + stolen:.2f} RC**\n"
            f"Баланс жертвы: **{bal_target - stolen:.2f} RC**"
        )
    else:
        fine = min(bal_robber, int(bal_robber * random.uniform(0.1, 0.3)))
        set_balance(gid, uid, bal_robber - fine)
        text = (
            f"🚓 Попытка провалилась, тебя задержали. Штраф **{fine} RC**.\n"
            f"Твой баланс: **{bal_robber - fine:.2f} RC**"
        )
    update_timer(gid, uid, "rob")
    await inter.response.send_message(text)


# ============ /collect-income и /addcollect-income ============

@bot.tree.command(name="collect-income", description="Собрать доход по своим ролям")
async def slash_collect_income(inter: discord.Interaction):
    if inter.guild is None:
        await inter.response.send_message("Только на сервере.", ephemeral=True)
        return
    gid, uid = inter.guild.id, inter.user.id
    ok, left = check_cooldown(gid, uid, "collect_income", INCOME_CD)
    if not ok:
        await inter.response.send_message(
            f"⏳ Ты уже собирал доход, подожди ещё **{format_cd(left)}**.",
            ephemeral=True,
        )
        return
    member = inter.user if isinstance(inter.user, discord.Member) else inter.guild.get_member(uid)
    if member is None:
        await inter.response.send_message("Не удалось определить твои роли.", ephemeral=True)
        return
    income = get_income_for_member(gid, member)
    if income <= 0:
        await inter.response.send_message(
            "Твоим ролям не назначен доход. Попроси админа использовать `/addcollect-income`.",
            ephemeral=True,
        )
        return
    bal = get_balance(gid, uid)
    set_balance(gid, uid, bal + income)
    update_timer(gid, uid, "collect_income")
    await inter.response.send_message(
        f"💸 Ты собрал доход по ролям: **{income} RC**.\nБаланс: **{bal + income:.2f} RC**.",
        ephemeral=True,
    )


@bot.tree.command(name="addcollect-income", description="Назначить доход для роли (только админы)")
@app_commands.describe(role="Роль, которая будет получать доход", amount="Сколько RC при сборе")
async def slash_addcollect_income(inter: discord.Interaction, role: discord.Role, amount: float):
    if inter.guild is None:
        await inter.response.send_message("Только на сервере.", ephemeral=True)
        return
    if not is_guild_admin(inter):
        await inter.response.send_message("Нужны права администратора.", ephemeral=True)
        return
    if amount <= 0:
        await inter.response.send_message("Сумма должна быть > 0.", ephemeral=True)
        return
    set_income_role(inter.guild.id, role.id, amount)
    await inter.response.send_message(
        f"✅ Для роли {role.mention} установлен доход **{amount} RC** за `/collect-income`.",
        ephemeral=True,
    )


# ============ /top-cash ============

@bot.tree.command(name="top-cash", description="Топ игроков по наличным деньгам")
@app_commands.describe(limit="Сколько игроков показать (по умолчанию 10)")
async def slash_top_cash(inter: discord.Interaction, limit: int = 10):
    if inter.guild is None:
        await inter.response.send_message("Только на сервере.", ephemeral=True)
        return
    limit = max(1, min(limit, 25))
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT user_id, wallet FROM balances
        WHERE guild_id = ? AND wallet > 0
        ORDER BY wallet DESC
        LIMIT ?
        """,
        (inter.guild.id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    if not rows:
        await inter.response.send_message("Пока ни у кого нет денег.", ephemeral=True)
        return
    lines = []
    for i, row in enumerate(rows, start=1):
        user = inter.guild.get_member(row["user_id"])
        name = user.mention if user else f"`ID {row['user_id']}`"
        lines.append(f"**{i}.** {name} — **{row['wallet']:.2f} RC**")
    embed = discord.Embed(
        title="🏆 Топ по наличным (cash)",
        description="\n".join(lines),
        colour=discord.Colour.gold(),
    )
    await inter.response.send_message(embed=embed)


# ============== ФОНОВЫЙ ЛУП КУРСА ==============

@tasks.loop(minutes=5)
async def random_events_loop():
    now = dt.datetime.utcnow()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM guild_settings")
    rows = cur.fetchall()
    conn.close()

    for row in rows:
        gid = row["guild_id"]
        if not row["random_events"]:
            continue
        interval = row["event_interval_min"]
        last_ts_raw = row["last_event_ts"]
        if last_ts_raw:
            last_ts = dt.datetime.fromisoformat(last_ts_raw)
            if (now - last_ts).total_seconds() < interval * 60:
                continue
        msg_text = apply_random_event(gid)
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE guild_settings SET last_event_ts = ? WHERE guild_id = ?",
            (now.isoformat(), gid),
        )
        conn.commit()
        conn.close()
        guild = bot.get_guild(gid)
        if not guild:
            continue
        channel: Optional[discord.TextChannel] = None
        for ch in guild.text_channels:
            if ch.permissions_for(guild.me).send_messages:
                channel = ch
                break
        if channel:
            try:
                await channel.send(msg_text)
            except Exception:
                pass


# ================== ЗАПУСК ====================

def main():
    init_db()
    token = os.getenv("TOKEN")
    if not token:
        raise RuntimeError("Переменная окружения TOKEN не задана!")
    bot.run(token)


if __name__ == "__main__":
    main()
