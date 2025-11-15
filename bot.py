# ============================================
#  RadonomyBot – slash + prefix версии
# ============================================

import os
import sqlite3
import datetime as dt
import random
from typing import Optional, List

import discord
from discord.ext import commands, tasks
from discord import app_commands

# ================== CONFIG ===================

DB_PATH = "radonomy.sqlite3"
DEFAULT_PREFIX = "/"          # стартовый текстовый префикс
DEFAULT_PRICE = 100.0         # базовый курс Radcoin

# ================== БАЗА ДАННЫХ ==============

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
    cur.execute("SELECT prefix FROM guild_settings WHERE guild_id = ?", (guild_id,))
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
    guild_id = message.guild.id if message.guild else None
    prefix = get_prefix_for_guild(guild_id)
    prefixes: List[str] = [prefix]
    if bot.user:
        prefixes.append(f"<@{bot.user.id}> ")
        prefixes.append(f"<@!{bot.user.id}> ")
    return prefixes


class RadonomyBot(commands.Bot):
    async def setup_hook(self):
        # slash-команды будут синкаться тут
        await self.tree.sync()
        print("Slash-команды синхронизированы.")


bot = RadonomyBot(command_prefix=prefix_callable, intents=intents)


# ============= ВСПОМОГАТЕЛЬНЫЕ ШТУКИ ==========

def is_guild_admin(interaction: discord.Interaction) -> bool:
    return (
        interaction.guild is not None
        and isinstance(interaction.user, discord.Member)
        and interaction.user.guild_permissions.administrator
    )


def in_guild_only_prefix():
    async def predicate(ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("Эта команда работает только на сервере, а не в ЛС.")
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


# ============== ПРЕФИКС-КОМАНДЫ ===============

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
async def cmd_balance(ctx: commands.Context, member: Optional[discord.Member] = None):
    member = member or ctx.author
    bal = get_balance(ctx.guild.id, member.id)
    await ctx.send(f"💰 Баланс {member.mention}: **{bal:.2f} RC**")


@bot.command(name="buy")
@in_guild_only_prefix()
async def cmd_buy(ctx: commands.Context, amount: float):
    if amount <= 0:
        await ctx.send("Сумма должна быть больше нуля.")
        return

    guild_id = ctx.guild.id
    user_id = ctx.author.id

    price = get_price(guild_id)
    bal = get_balance(guild_id, user_id)
    new_bal = bal + amount
    set_balance(guild_id, user_id, new_bal)

    delta = price * 0.01 * (amount / 100)
    new_price = change_price(guild_id, delta)

    await ctx.send(
        f"✅ {ctx.author.mention} купил **{amount:.2f} RC**.\n"
        f"Новый баланс: **{new_bal:.2f} RC**\n"
        f"Курс слегка вырос до **{new_price:.2f} RC**"
    )


@bot.command(name="sell")
@in_guild_only_prefix()
async def cmd_sell(ctx: commands.Context, amount: float):
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

    delta = -price * 0.01 * (amount / 100)
    new_price = change_price(guild_id, delta)

    await ctx.send(
        f"✅ {ctx.author.mention} продал **{amount:.2f} RC**.\n"
        f"Новый баланс: **{new_bal:.2f} RC**\n"
        f"Курс немного упал до **{new_price:.2f} RC**"
    )


@bot.command(name="radhelp")
@in_guild_only_prefix()
async def cmd_radhelp(ctx: commands.Context):
    prefix = get_prefix_for_guild(ctx.guild.id)
    embed = discord.Embed(
        title="📘 Radonomy / Radcoin — помощь",
        description=f"Текущий префикс: `{prefix}`",
        colour=discord.Colour.blurple(),
    )
    embed.add_field(
        name="Основные команды (префикс)",
        value=(
            f"`{prefix}price` — показать курс\n"
            f"`{prefix}balance` — баланс\n"
            f"`{prefix}buy <кол-во>` — купить\n"
            f"`{prefix}sell <кол-во>` — продать\n"
        ),
        inline=False,
    )
    embed.add_field(
        name="Slash-команды",
        value=(
            "`/price`, `/balance`, `/buy`, `/sell`, `/radhelp`, `/radsettings ...`\n"
            "Они появляются в меню слэш-команд Discord."
        ),
        inline=False,
    )
    await ctx.send(embed=embed)


# ============== SLASH-КОМАНДЫ =================

# /price
@bot.tree.command(name="price", description="Показать текущий курс Radcoin")
async def slash_price(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Эта команда работает только на сервере.", ephemeral=True
        )
        return
    price = get_price(interaction.guild.id)
    embed = discord.Embed(
        title="📊 Курс Radcoin",
        description=f"Текущий курс: **{price:.2f} RC**",
        colour=discord.Colour.gold(),
    )
    await interaction.response.send_message(embed=embed, ephemeral=False)


# /balance
@bot.tree.command(name="balance", description="Показать баланс Radcoin")
@app_commands.describe(member="Чей баланс показать (если не указать – ваш)")
async def slash_balance(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Эта команда работает только на сервере.", ephemeral=True
        )
        return
    member = member or interaction.user
    bal = get_balance(interaction.guild.id, member.id)
    await interaction.response.send_message(
        f"💰 Баланс {member.mention}: **{bal:.2f} RC**",
        ephemeral=(member.id == interaction.user.id),
    )


# /buy
@bot.tree.command(name="buy", description="Купить Radcoin по текущему курсу")
@app_commands.describe(amount="Количество Radcoin для покупки")
async def slash_buy(interaction: discord.Interaction, amount: float):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Эта команда работает только на сервере.", ephemeral=True
        )
        return
    if amount <= 0:
        await interaction.response.send_message(
            "Сумма должна быть больше нуля.", ephemeral=True
        )
        return

    guild_id = interaction.guild.id
    user_id = interaction.user.id

    price = get_price(guild_id)
    bal = get_balance(guild_id, user_id)
    new_bal = bal + amount
    set_balance(guild_id, user_id, new_bal)

    delta = price * 0.01 * (amount / 100)
    new_price = change_price(guild_id, delta)

    await interaction.response.send_message(
        f"✅ Ты купил **{amount:.2f} RC**.\n"
        f"Новый баланс: **{new_bal:.2f} RC**\n"
        f"Курс слегка вырос до **{new_price:.2f} RC**",
        ephemeral=True,
    )


# /sell
@bot.tree.command(name="sell", description="Продать Radcoin по текущему курсу")
@app_commands.describe(amount="Количество Radcoin для продажи")
async def slash_sell(interaction: discord.Interaction, amount: float):
    if interaction.guild is None:
        await interaction.response.send_message(
            "Эта команда работает только на сервере.", ephemeral=True
        )
        return
    if amount <= 0:
        await interaction.response.send_message(
            "Сумма должна быть больше нуля.", ephemeral=True
        )
        return

    guild_id = interaction.guild.id
    user_id = interaction.user.id

    bal = get_balance(guild_id, user_id)
    if amount > bal:
        await interaction.response.send_message(
            "У тебя нет столько Radcoin для продажи.", ephemeral=True
        )
        return

    price = get_price(guild_id)
    new_bal = bal - amount
    set_balance(guild_id, user_id, new_bal)

    delta = -price * 0.01 * (amount / 100)
    new_price = change_price(guild_id, delta)

    await interaction.response.send_message(
        f"✅ Ты продал **{amount:.2f} RC**.\n"
        f"Новый баланс: **{new_bal:.2f} RC**\n"
        f"Курс немного упал до **{new_price:.2f} RC**",
        ephemeral=True,
    )


# /radhelp
@bot.tree.command(name="radhelp", description="Список команд RadonomyBot")
async def slash_radhelp(interaction: discord.Interaction):
    if interaction.guild is None:
        prefix = DEFAULT_PREFIX
    else:
        prefix = get_prefix_for_guild(interaction.guild.id)

    embed = discord.Embed(
        title="📘 Radonomy / Radcoin — помощь",
        description="Текущие команды бота.",
        colour=discord.Colour.blurple(),
    )
    embed.add_field(
        name="Slash-команды",
        value=(
            "`/price` — курс Radcoin\n"
            "`/balance [участник]` — баланс\n"
            "`/buy <кол-во>` — купить\n"
            "`/sell <кол-во>` — продать\n"
            "`/radsettings ...` — настройки\n"
        ),
        inline=False,
    )
    embed.add_field(
        name="Префикс-команды",
        value=(
            f"`{prefix}price`, `{prefix}balance`, `{prefix}buy`, `{prefix}sell`, "
            f"`{prefix}radhelp`"
        ),
        inline=False,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ============ SLASH ГРУППА /radsettings =======

class RadSettings(app_commands.Group):
    """Slash-настройки бота на сервере."""

    @app_commands.command(name="prefix", description="Изменить префикс текстовых команд")
    @app_commands.describe(new_prefix="Новый префикс (до 5 символов)")
    async def prefix(self, interaction: discord.Interaction, new_prefix: str):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Эта команда работает только на сервере.", ephemeral=True
            )
            return
        if not is_guild_admin(interaction):
            await interaction.response.send_message(
                "Нужны права администратора сервера.", ephemeral=True
            )
            return
        if len(new_prefix) > 5:
            await interaction.response.send_message(
                "Префикс слишком длинный (максимум 5 символов).",
                ephemeral=True,
            )
            return
        set_prefix_for_guild(interaction.guild.id, new_prefix)
        await interaction.response.send_message(
            f"✅ Префикс изменён на `{new_prefix}`. "
            f"Теперь команды: `{new_prefix}price`, `{new_prefix}buy` и т.д.",
            ephemeral=True,
        )

    @app_commands.command(name="price", description="Жёстко установить курс Radcoin")
    @app_commands.describe(new_price="Новый курс (> 0)")
    async def price(self, interaction: discord.Interaction, new_price: float):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Эта команда работает только на сервере.", ephemeral=True
            )
            return
        if not is_guild_admin(interaction):
            await interaction.response.send_message(
                "Нужны права администратора сервера.", ephemeral=True
            )
            return
        if new_price <= 0:
            await interaction.response.send_message(
                "Курс должен быть больше нуля.", ephemeral=True
            )
            return
        set_price(interaction.guild.id, new_price)
        await interaction.response.send_message(
            f"⚠ Курс принудительно установлен на **{new_price:.2f} RC**. "
            f"Экономика может пострадать!",
            ephemeral=True,
        )

    @app_commands.command(name="events", description="Включить или выключить рандомные события")
    @app_commands.describe(mode="on / off")
    async def events(self, interaction: discord.Interaction, mode: str):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Эта команда работает только на сервере.", ephemeral=True
            )
            return
        if not is_guild_admin(interaction):
            await interaction.response.send_message(
                "Нужны права администратора сервера.", ephemeral=True
            )
            return
        mode = mode.lower()
        if mode not in ("on", "off"):
            await interaction.response.send_message(
                "Используй `on` или `off`.", ephemeral=True
            )
            return
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE guild_settings SET random_events = ? WHERE guild_id = ?",
            (1 if mode == "on" else 0, interaction.guild.id),
        )
        conn.commit()
        conn.close()
        await interaction.response.send_message(
            f"✅ Рандомные события теперь: **{'включены' if mode == 'on' else 'выключены'}**.",
            ephemeral=True,
        )

    @app_commands.command(name="interval", description="Изменить период рандомных событий")
    @app_commands.describe(minutes="Интервал в минутах (минимум 5)")
    async def interval(self, interaction: discord.Interaction, minutes: int):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Эта команда работает только на сервере.", ephemeral=True
            )
            return
        if not is_guild_admin(interaction):
            await interaction.response.send_message(
                "Нужны права администратора сервера.", ephemeral=True
            )
            return
        if minutes < 5:
            await interaction.response.send_message(
                "Минимальный интервал — 5 минут.", ephemeral=True
            )
            return
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE guild_settings SET event_interval_min = ? WHERE guild_id = ?",
            (minutes, interaction.guild.id),
        )
        conn.commit()
        conn.close()
        await interaction.response.send_message(
            f"✅ Интервал случайных событий установлен на **{minutes} минут**.",
            ephemeral=True,
        )


bot.tree.add_command(RadSettings(name="radsettings", description="Настройки RadonomyBot"))


# ============== ФОНОВЫЕ СОБЫТИЯ ==============

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
