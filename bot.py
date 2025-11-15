# ============================================
#  RadonomyBot – базовая версия
#  - SQLite
#  - настраиваемый префикс (по умолчанию "/")
#  - команды: price, balance, buy, sell, radhelp, radsettings
# ============================================

import os
import sqlite3
import datetime as dt
import random
from typing import Optional, List

import discord
from discord.ext import commands, tasks

# ================== CONFIG ===================

DB_PATH = "radonomy.sqlite3"
DEFAULT_PREFIX = "/"          # стартовый префикс
DEFAULT_PRICE = 100.0         # базовый курс Radcoin

# ================== БАЗА ДАННЫХ ==============

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # настройки сервера
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

    # балансы игроков
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

    # история цен для графика/аналитики
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

    conn.commit()
    conn.close()


def ensure_guild_row(guild_id: int):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT guild_id FROM guild_settings WHERE guild_id = ?", (guild_id,))
    row = cur.fetchone()
    if row is None:
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
    cur.execute(
        "SELECT prefix FROM guild_settings WHERE guild_id = ?", (guild_id,)
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return DEFAULT_PREFIX
    return row["prefix"]


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
    # вносим в историю
    cur.execute(
        "INSERT INTO price_history (guild_id, ts_utc, price) VALUES (?, ?, ?)",
        (guild_id, dt.datetime.utcnow().isoformat(), new_price),
    )
    conn.commit()
    conn.close()


def change_price(guild_id: int, delta: float) -> float:
    price = get_price(guild_id)
    new_price = max(1.0, price + delta)  # не даём уйти в 0 или минус
    set_price(guild_id, new_price)
    return new_price


def get_balance(guild_id: int, user_id: int) -> float:
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


# ============= РАНДОМНЫЕ СОБЫТИЯ ==============

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
    # выбираем случайное событие и случайный % из его диапазона
    text, p_min, p_max = random.choice(RANDOM_EVENTS)
    percent = random.uniform(p_min, p_max)
    price = get_price(guild_id)
    delta = price * (percent / 100.0)
    new_price = change_price(guild_id, delta)
    sign = "📈" if delta > 0 else "📉"
    return f"{sign} {text}. Изменение: {percent:+.1f}% | Новый курс: {new_price:.2f} RC"


# ================== DISCORD BOT ===============

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


async def prefix_callable(bot: commands.Bot, message: discord.Message):
    # возвращаем несколько вариантов префикса:
    # - текущий из базы
    # - обращение по упоминанию бота
    guild_id = message.guild.id if message.guild else None
    prefix = get_prefix_for_guild(guild_id)
    prefixes: List[str] = [prefix]
    if bot.user:
        prefixes.append(f"<@{bot.user.id}> ")
        prefixes.append(f"<@!{bot.user.id}> ")
    return prefixes


bot = commands.Bot(command_prefix=prefix_callable, intents=intents)


# ============= ВСПОМОГАТЕЛЬНЫЕ ШТУКИ ==========

def in_guild_only():
    async def predicate(ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("Эта команда работает только на сервере, а не в ЛС.")
            return False
        return True
    return commands.check(predicate)


def admin_only():
    async def predicate(ctx: commands.Context):
        if ctx.guild is None:
            return False
        if ctx.author.guild_permissions.administrator:
            return True
        await ctx.send("Требуются права администратора сервера.")
        return False
    return commands.check(predicate)


# ============== СЛУЖЕБНЫЕ СОБЫТИЯ =============

@bot.event
async def on_ready():
    print(f"RadonomyBot запущен как {bot.user} (ID: {bot.user.id})")
    for guild in bot.guilds:
        ensure_guild_row(guild.id)
    random_events_loop.start()


@bot.event
async def on_guild_join(guild: discord.Guild):
    ensure_guild_row(guild.id)


# ============== КОМАНДЫ ЭКОНОМИКИ =============

@bot.command(name="price")
@in_guild_only()
async def cmd_price(ctx: commands.Context):
    """Показать текущий курс Radcoin."""
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
@in_guild_only()
async def cmd_balance(ctx: commands.Context, member: Optional[discord.Member] = None):
    """Показать баланс Radcoin."""
    member = member or ctx.author
    bal = get_balance(ctx.guild.id, member.id)
    await ctx.send(f"💰 Баланс {member.mention}: **{bal:.2f} RC**")


@bot.command(name="buy")
@in_guild_only()
async def cmd_buy(ctx: commands.Context, amount: float):
    """
    Купить Radcoin по текущему курсу.
    Для простоты считаем, что у игрока всегда хватает внешних денег,
    а мы просто выдаём Radcoin и двигаем курс.
    """
    if amount <= 0:
        await ctx.send("Сумма должна быть больше нуля.")
        return

    guild_id = ctx.guild.id
    user_id = ctx.author.id

    price = get_price(guild_id)
    bal = get_balance(guild_id, user_id)
    new_bal = bal + amount
    set_balance(guild_id, user_id, new_bal)

    # немного двигаем курс вверх (спрос)
    delta = price * 0.01 * (amount / 100)  # мягкое изменение
    new_price = change_price(guild_id, delta)

    await ctx.send(
        f"✅ {ctx.author.mention} купил **{amount:.2f} RC**.\n"
        f"Новый баланс: **{new_bal:.2f} RC**\n"
        f"Курс слегка вырос до **{new_price:.2f} RC**"
    )


@bot.command(name="sell")
@in_guild_only()
async def cmd_sell(ctx: commands.Context, amount: float):
    """Продать Radcoin по текущему курсу."""
    if amount <= 0:
        await ctx.send("Сумма должна быть больше нуля.")
        return

    guild_id = ctx.guild.id
    user_id = ctx.author.id

    bal = get_balance(guild_id, user_id)
    if amount > bal:
        await ctx.send("У тебя нет столько Radcoin для продажи.")
        return

    price = get_price(guild_id)
    new_bal = bal - amount
    set_balance(guild_id, user_id, new_bal)

    # двигаем курс вниз (предложение)
    delta = -price * 0.01 * (amount / 100)
    new_price = change_price(guild_id, delta)

    await ctx.send(
        f"✅ {ctx.author.mention} продал **{amount:.2f} RC**.\n"
        f"Новый баланс: **{new_bal:.2f} RC**\n"
        f"Курс немного упал до **{new_price:.2f} RC**"
    )


# ================ RADHELP =====================

@bot.command(name="radhelp")
@in_guild_only()
async def cmd_radhelp(ctx: commands.Context):
    """Показать список основных команд бота."""
    prefix = get_prefix_for_guild(ctx.guild.id)
    embed = discord.Embed(
        title="📘 Radonomy / Radcoin — помощь",
        description=f"Текущий префикс: `{prefix}`",
        colour=discord.Colour.blurple(),
    )

    embed.add_field(
        name="Основные команды",
        value=(
            f"`{prefix}price` — показать курс Radcoin\n"
            f"`{prefix}balance [@user]` — показать баланс\n"
            f"`{prefix}buy <кол-во>` — купить Radcoin\n"
            f"`{prefix}sell <кол-во>` — продать Radcoin\n"
        ),
        inline=False,
    )

    embed.add_field(
        name="Админ-команды",
        value=(
            f"`{prefix}radsettings prefix <символ>` — изменить префикс\n"
            f"`{prefix}radsettings price <число>` — вручную задать курс\n"
            f"`{prefix}radsettings events on/off` — включить/выключить рандомные события\n"
            f"`{prefix}radsettings interval <минуты>` — период случайных событий\n"
        ),
        inline=False,
    )

    await ctx.send(embed=embed)


# ================ RADSETTINGS =================

@bot.group(name="radsettings", invoke_without_command=True)
@admin_only()
@in_guild_only()
async def radsettings(ctx: commands.Context):
    """Группа команд настройки бота на сервере."""
    prefix = get_prefix_for_guild(ctx.guild.id)
    await ctx.send(
        f"⚙ Настройки бота. Используй `{prefix}radsettings prefix ...`, "
        f"`{prefix}radsettings price ...`, `{prefix}radsettings events ...` и т.п.\n"
        f"Подробно: `{prefix}radhelp`"
    )


@radsettings.command(name="prefix")
@admin_only()
@in_guild_only()
async def radsettings_prefix(ctx: commands.Context, new_prefix: str):
    """Изменить текстовый префикс бота на сервере."""
    if len(new_prefix) > 5:
        await ctx.send("Префикс слишком длинный (максимум 5 символов).")
        return
    set_prefix_for_guild(ctx.guild.id, new_prefix)
    await ctx.send(f"✅ Префикс изменён на `{new_prefix}`. Теперь команды: `{new_prefix}price` и т.д.")


@radsettings.command(name="price")
@admin_only()
@in_guild_only()
async def radsettings_price(ctx: commands.Context, new_price: float):
    """Жёстко установить курс Radcoin."""
    if new_price <= 0:
        await ctx.send("Курс должен быть больше нуля.")
        return
    set_price(ctx.guild.id, new_price)
    await ctx.send(f"⚠ Курс принудительно установлен на **{new_price:.2f} RC**. Экономика может пострадать!")


@radsettings.command(name="events")
@admin_only()
@in_guild_only()
async def radsettings_events(ctx: commands.Context, mode: str):
    """Включить или выключить случайные событийные изменения курса."""
    mode = mode.lower()
    if mode not in ("on", "off"):
        await ctx.send("Используй: `on` или `off`.")
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE guild_settings SET random_events = ? WHERE guild_id = ?",
        (1 if mode == "on" else 0, ctx.guild.id),
    )
    conn.commit()
    conn.close()
    await ctx.send(f"✅ Рандомные события теперь: **{ 'включены' if mode == 'on' else 'выключены' }**.")


@radsettings.command(name="interval")
@admin_only()
@in_guild_only()
async def radsettings_interval(ctx: commands.Context, minutes: int):
    """Изменить период случайных событий (в минутах)."""
    if minutes < 5:
        await ctx.send("Минимальный интервал — 5 минут.")
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE guild_settings SET event_interval_min = ? WHERE guild_id = ?",
        (minutes, ctx.guild.id),
    )
    conn.commit()
    conn.close()
    await ctx.send(f"✅ Интервал случайных событий установлен на **{minutes} минут**.")


# ============== ФОНЫЕ СОБЫТИЯ ================

@tasks.loop(minutes=5)
async def random_events_loop():
    # Каждые 5 минут пробегаемся по серверам и при необходимости триггерим событие
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
                continue  # ещё рано

        # применяем событие
        msg_text = apply_random_event(gid)

        # сохраняем время
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE guild_settings SET last_event_ts = ? WHERE guild_id = ?",
            (now.isoformat(), gid),
        )
        conn.commit()
        conn.close()

        # пытаемся найти любой текстовый канал на сервере, чтобы отправить инфу
        guild = bot.get_guild(gid)
        if not guild:
            continue
        # берём первый доступный текстовый канал
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
    TOKEN = os.getenv("TOKEN")
    if not TOKEN:
        raise RuntimeError("Переменная окружения TOKEN не задана!")

    bot.run(TOKEN)


if __name__ == "__main__":
    main()
