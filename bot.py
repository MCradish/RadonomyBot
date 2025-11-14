import discord
from discord.ext import commands, tasks
import sqlite3
import os
import io
import random
import time
import asyncio
from datetime import datetime
import matplotlib.pyplot as plt
import pandas as pd

# ============ ОБЩИЕ НАСТРОЙКИ ============

DB_FILE = "radonomy.db"
DEFAULT_PREFIX = "!"
DEFAULT_MONEY_LABEL = "coins"  # можно поменять через radsettings money_label

MIN_PRICE = 10.0
MAX_PRICE = 10000.0

RANDOM_EVENT_MAX_PERCENT = 5.0
DEFAULT_RANDOM_EVENTS_ENABLED = True
DEFAULT_RANDOM_EVENT_INTERVAL_MIN = 60.0  # минут
BOOST_PRICE_ALPHA = 0.2  # сглаживание бустер-курса

CASE_BASE_VALUE = 1000.0

# Настройки экономики (аналог UnbelievaBoat)
ECON_DEFAULTS = {
    "work_cd": 300.0,       # 5 минут
    "work_min": 50.0,
    "work_max": 150.0,
    "rob_cd": 600.0,        # 10 минут
    "rob_min": 100.0,
    "rob_max": 400.0,
    "rob_success": 0.5,
    "slut_cd": 600.0,
    "slut_min": 100.0,
    "slut_max": 400.0,
    "slut_success": 0.5,
    "roulette_max_bet": 5000.0,
    "income_cd": 3600.0,    # 1 час
    "income_rate": 0.01,    # 1% от банка
    "blackjack_max_bet": 10000.0,
}

# !!! ВСТАВЬ СЮДА СВОЙ ТОКЕН !!!
import os
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


# ============ SQLITE ============

def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS market (
        id INTEGER PRIMARY KEY CHECK(id=1),
        price REAL,
        liquidity REAL,
        k REAL,
        boost_price REAL
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT,
        price REAL
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        money REAL,
        radcoin REAL,
        bank REAL,
        last_boost_trade TEXT,
        last_case_ts REAL,
        last_work_ts REAL,
        last_daily_ts REAL,
        last_weekly_ts REAL,
        last_rob_ts REAL,
        last_slut_ts REAL,
        last_income_ts REAL,
        last_roulette_ts REAL,
        last_blackjack_ts REAL
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS guild_settings (
        guild_id INTEGER PRIMARY KEY,
        prefix TEXT,
        random_events_enabled INTEGER,
        random_event_interval REAL,
        banker_role TEXT,
        booster_role TEXT,
        premium_role TEXT,
        admin_role TEXT,
        channel_id INTEGER
    )""")

    # на всякий случай добавляем недостающие колонки
    c.execute("PRAGMA table_info(guild_settings)")
    cols = [row[1] for row in c.fetchall()]
    extra_cols = {
        "prefix": "TEXT",
        "random_events_enabled": "INTEGER",
        "random_event_interval": "REAL",
        "banker_role": "TEXT",
        "booster_role": "TEXT",
        "premium_role": "TEXT",
        "admin_role": "TEXT",
        "channel_id": "INTEGER",
    }
    for col, ddl in extra_cols.items():
        if col not in cols:
            try:
                c.execute(f"ALTER TABLE guild_settings ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass

    conn.commit()
    conn.close()


# ============ SETTINGS (KEY/VALUE) ============

def get_setting(key, default):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    if row is None:
        c.execute("INSERT INTO settings(key, value) VALUES (?, ?)", (key, str(default)))
        conn.commit()
        conn.close()
        return str(default)
    conn.close()
    return row["value"]


def set_setting(key, value):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO settings(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
    """, (key, str(value)))
    conn.commit()
    conn.close()


def is_enabled():
    return get_setting("bot_enabled", "1") == "1"


def set_enabled(enabled: bool):
    set_setting("bot_enabled", "1" if enabled else "0")


def get_money_label():
    return get_setting("money_label", DEFAULT_MONEY_LABEL)


def get_econ_setting(name: str) -> float:
    key = f"econ_{name}"
    default = ECON_DEFAULTS.get(name, 0.0)
    val = get_setting(key, str(default))
    try:
        return float(val)
    except ValueError:
        return float(default)


# ============ GUILD SETTINGS ============

def get_guild_settings(guild_id: int):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
    row = c.fetchone()
    if row is None:
        c.execute("""
            INSERT INTO guild_settings(
                guild_id, prefix, random_events_enabled, random_event_interval,
                banker_role, booster_role, premium_role, admin_role, channel_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            guild_id,
            DEFAULT_PREFIX,
            1 if DEFAULT_RANDOM_EVENTS_ENABLED else 0,
            DEFAULT_RANDOM_EVENT_INTERVAL_MIN,
            None, None, None, None, None
        ))
        conn.commit()
        c.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
        row = c.fetchone()
    conn.close()
    return row


def set_guild_prefix(guild_id: int, prefix: str):
    row = get_guild_settings(guild_id)
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO guild_settings(
            guild_id, prefix, random_events_enabled, random_event_interval,
            banker_role, booster_role, premium_role, admin_role, channel_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET prefix = excluded.prefix
    """, (
        guild_id, prefix,
        row["random_events_enabled"], row["random_event_interval"],
        row["banker_role"], row["booster_role"], row["premium_role"],
        row["admin_role"], row["channel_id"]
    ))
    conn.commit()
    conn.close()


def set_guild_role(guild_id: int, column: str, role_name: str):
    row = get_guild_settings(guild_id)
    conn = get_db()
    c = conn.cursor()
    data = {
        "guild_id": guild_id,
        "prefix": row["prefix"],
        "random_events_enabled": row["random_events_enabled"],
        "random_event_interval": row["random_event_interval"],
        "banker_role": row["banker_role"],
        "booster_role": row["booster_role"],
        "premium_role": row["premium_role"],
        "admin_role": row["admin_role"],
        "channel_id": row["channel_id"],
    }
    data[column] = role_name
    c.execute("""
        INSERT INTO guild_settings(
            guild_id, prefix, random_events_enabled, random_event_interval,
            banker_role, booster_role, premium_role, admin_role, channel_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET
            prefix = excluded.prefix,
            random_events_enabled = excluded.random_events_enabled,
            random_event_interval = excluded.random_event_interval,
            banker_role = excluded.banker_role,
            booster_role = excluded.booster_role,
            premium_role = excluded.premium_role,
            admin_role = excluded.admin_role,
            channel_id = excluded.channel_id
    """, (
        guild_id,
        data["prefix"], data["random_events_enabled"], data["random_event_interval"],
        data["banker_role"], data["booster_role"], data["premium_role"],
        data["admin_role"], data["channel_id"]
    ))
    conn.commit()
    conn.close()


def get_guild_role_name(guild_id: int, column: str):
    row = get_guild_settings(guild_id)
    return row[column]


def set_guild_channel_id(guild_id: int, channel_id: int | None):
    row = get_guild_settings(guild_id)
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO guild_settings(
            guild_id, prefix, random_events_enabled, random_event_interval,
            banker_role, booster_role, premium_role, admin_role, channel_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id
    """, (
        guild_id,
        row["prefix"], row["random_events_enabled"], row["random_event_interval"],
        row["banker_role"], row["booster_role"], row["premium_role"],
        row["admin_role"], channel_id
    ))
    conn.commit()
    conn.close()


def get_guild_channel_id(guild_id: int) -> int | None:
    row = get_guild_settings(guild_id)
    return row["channel_id"]


async def get_prefix(bot, message):
    if message.guild is None:
        return DEFAULT_PREFIX
    row = get_guild_settings(message.guild.id)
    return row["prefix"] if row and row["prefix"] else DEFAULT_PREFIX


# ============ РЫНОК RADCOIN ============

def clamp_price(value: float) -> float:
    return max(MIN_PRICE, min(MAX_PRICE, value))


def get_market():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM market WHERE id = 1")
    row = c.fetchone()
    if row is None:
        price = 100.0
        liquidity = 1000.0
        k = 0.5
        boost_price = price
        c.execute("""
            INSERT INTO market(id, price, liquidity, k, boost_price)
            VALUES (1, ?, ?, ?, ?)
        """, (price, liquidity, k, boost_price))
        conn.commit()
        conn.close()
        return {
            "price": price,
            "liquidity": liquidity,
            "k": k,
            "boost_price": boost_price,
        }
    conn.close()
    return {
        "price": row["price"],
        "liquidity": row["liquidity"],
        "k": row["k"],
        "boost_price": row["boost_price"],
    }


def save_market(market: dict):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO market(id, price, liquidity, k, boost_price)
        VALUES (1, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            price = excluded.price,
            liquidity = excluded.liquidity,
            k = excluded.k,
            boost_price = excluded.boost_price
    """, (
        market["price"], market["liquidity"],
        market["k"], market["boost_price"]
    ))
    conn.commit()
    conn.close()


def add_price_history(price: float):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO price_history(time, price) VALUES (?, ?)",
              (datetime.utcnow().isoformat(), price))
    c.execute("""
        DELETE FROM price_history WHERE id NOT IN (
            SELECT id FROM price_history ORDER BY id DESC LIMIT 500
        )
    """)
    conn.commit()
    conn.close()


def _update_boost_price(market: dict, new_main_price: float) -> float:
    bp = market.get("boost_price", new_main_price)
    bp = bp + (new_main_price - bp) * BOOST_PRICE_ALPHA
    bp = clamp_price(bp)
    market["boost_price"] = bp
    return bp


def update_price_from_trade(buy_amount: float, sell_amount: float) -> float:
    market = get_market()
    P = market["price"]
    k = market["k"]
    liquidity = market["liquidity"]

    delta = (buy_amount - sell_amount) / max(liquidity, 1.0)
    new_price = P * (1 + k * delta)
    new_price = clamp_price(new_price)

    market["price"] = new_price
    _update_boost_price(market, new_price)
    save_market(market)
    add_price_history(new_price)
    return new_price


def apply_event(percent_change: float) -> float:
    market = get_market()
    P = market["price"]
    factor = 1 + (percent_change / 100.0)
    new_price = clamp_price(P * factor)
    market["price"] = new_price
    _update_boost_price(market, new_price)
    save_market(market)
    add_price_history(new_price)
    return new_price


def get_boost_price() -> float:
    return get_market()["boost_price"]


def generate_chart():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT price FROM price_history ORDER BY id ASC")
    rows = c.fetchall()
    conn.close()
    if not rows:
        return None
    prices = [r["price"] for r in rows]
    plt.figure(figsize=(8, 4))
    plt.plot(prices)
    plt.xlabel("Точки по времени")
    plt.ylabel("Курс Radcoin")
    plt.title("История курса Radcoin")
    plt.grid(True)
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)
    return buf


# ============ USERS / BALANCES ============

def get_user_balance(user_id: int) -> dict:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if row is None:
        money = 1000.0
        radcoin = 0.0
        bank = 0.0
        last_boost_trade = None
        last_case_ts = None
        last_work_ts = None
        last_daily_ts = None
        last_weekly_ts = None
        last_rob_ts = None
        last_slut_ts = None
        last_income_ts = None
        last_roulette_ts = None
        last_blackjack_ts = None
        c.execute("""
            INSERT INTO users(
                user_id, money, radcoin, bank,
                last_boost_trade, last_case_ts,
                last_work_ts, last_daily_ts, last_weekly_ts,
                last_rob_ts, last_slut_ts, last_income_ts,
                last_roulette_ts, last_blackjack_ts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, money, radcoin, bank,
            last_boost_trade, last_case_ts,
            last_work_ts, last_daily_ts, last_weekly_ts,
            last_rob_ts, last_slut_ts, last_income_ts,
            last_roulette_ts, last_blackjack_ts
        ))
        conn.commit()
        conn.close()
        return {
            "user_id": user_id,
            "money": money,
            "radcoin": radcoin,
            "bank": bank,
            "last_boost_trade": last_boost_trade,
            "last_case_ts": last_case_ts,
            "last_work_ts": last_work_ts,
            "last_daily_ts": last_daily_ts,
            "last_weekly_ts": last_weekly_ts,
            "last_rob_ts": last_rob_ts,
            "last_slut_ts": last_slut_ts,
            "last_income_ts": last_income_ts,
            "last_roulette_ts": last_roulette_ts,
            "last_blackjack_ts": last_blackjack_ts,
        }
    conn.close()
    return dict(row)


def set_user_balance(bal: dict):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO users(
            user_id, money, radcoin, bank,
            last_boost_trade, last_case_ts,
            last_work_ts, last_daily_ts, last_weekly_ts,
            last_rob_ts, last_slut_ts, last_income_ts,
            last_roulette_ts, last_blackjack_ts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            money = excluded.money,
            radcoin = excluded.radcoin,
            bank = excluded.bank,
            last_boost_trade = excluded.last_boost_trade,
            last_case_ts = excluded.last_case_ts,
            last_work_ts = excluded.last_work_ts,
            last_daily_ts = excluded.last_daily_ts,
            last_weekly_ts = excluded.last_weekly_ts,
            last_rob_ts = excluded.last_rob_ts,
            last_slut_ts = excluded.last_slut_ts,
            last_income_ts = excluded.last_income_ts,
            last_roulette_ts = excluded.last_roulette_ts,
            last_blackjack_ts = excluded.last_blackjack_ts
    """, (
        bal["user_id"], bal["money"], bal["radcoin"], bal["bank"],
        bal.get("last_boost_trade"),
        bal.get("last_case_ts"),
        bal.get("last_work_ts"),
        bal.get("last_daily_ts"),
        bal.get("last_weekly_ts"),
        bal.get("last_rob_ts"),
        bal.get("last_slut_ts"),
        bal.get("last_income_ts"),
        bal.get("last_roulette_ts"),
        bal.get("last_blackjack_ts"),
    ))
    conn.commit()
    conn.close()


# ============ ПРАВА / РОЛИ ============

def is_booster(member: discord.Member) -> bool:
    guild = member.guild
    if guild is not None:
        role_name = get_guild_role_name(guild.id, "booster_role")
        if role_name:
            return any(r.name.lower() == role_name.lower() for r in member.roles)
    return getattr(member, "premium_since", None) is not None


def is_premium(member: discord.Member) -> bool:
    guild = member.guild
    if guild is not None:
        role_name = get_guild_role_name(guild.id, "premium_role")
        if role_name:
            return any(r.name.lower() == role_name.lower() for r in member.roles)
    names = [r.name.lower() for r in member.roles]
    return ("premium" in names) or ("премиум" in names)


async def has_econ_admin(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        return False
    guild = ctx.guild
    admin_role = get_guild_role_name(guild.id, "admin_role")
    if admin_role and any(r.name.lower() == admin_role.lower() for r in ctx.author.roles):
        return True
    if ctx.author.guild_permissions.administrator:
        return True
    if await ctx.bot.is_owner(ctx.author):
        return True
    return False


def has_banker_permission(ctx: commands.Context) -> bool:
    if ctx.guild is None:
        return False
    guild = ctx.guild
    banker = get_guild_role_name(guild.id, "banker_role")
    admin_role = get_guild_role_name(guild.id, "admin_role")
    if banker and any(r.name.lower() == banker.lower() for r in ctx.author.roles):
        return True
    if admin_role and any(r.name.lower() == admin_role.lower() for r in ctx.author.roles):
        return True
    if ctx.author.guild_permissions.administrator:
        return True
    return False


def can_do_boost_trade(bal: dict) -> bool:
    today = datetime.utcnow().date().isoformat()
    return bal.get("last_boost_trade") != today


def mark_boost_trade_done(bal: dict):
    bal["last_boost_trade"] = datetime.utcnow().date().isoformat()


def can_open_case(bal: dict):
    now_ts = time.time()
    last = bal.get("last_case_ts")
    if last is None:
        return True, 0.0
    diff = now_ts - last
    if diff >= 24 * 3600:
        return True, 0.0
    return False, 24 * 3600 - diff


def mark_case_opened(bal: dict):
    bal["last_case_ts"] = time.time()


# ============ BOT И CHECK ============

init_db()
bot = commands.Bot(command_prefix=get_prefix, intents=intents)


@bot.check
async def global_enable_check(ctx: commands.Context):
    if ctx.command and ctx.command.name in ("enablebot", "disablebot", "shutdown"):
        return True

    if not is_enabled() and not await bot.is_owner(ctx.author):
        await ctx.send("⚠️ Radonomy временно отключён владельцем.")
        return False

    if ctx.guild and ctx.command:
        allowed = ("radsettings", "radhelp", "enablebot", "disablebot", "shutdown")
        if ctx.command.name not in allowed:
            ch_id = get_guild_channel_id(ctx.guild.id)
            if ch_id is not None and ctx.channel.id != ch_id:
                return False
    return True


# ============ РАНДОМНЫЕ СОБЫТИЯ ============

EVENT_DESCRIPTIONS = [
    "Рыцари вернулись из похода с сундуками золота",
    "Маги Гильдии провели удачный ритуал обогащения",
    "Дракон уснул на своей сокровищнице, и торговцы успокоились",
    "Гильдия воров разворовала купеческие караваны",
    "Король объявил снижение налогов на торговлю",
    "Чёрный рынок Radcoin оживился после слухов о войне",
    "Алхимики открыли способ превращать свинец в золото",
    "Дварфы нашли новую жилу магической руды",
    "Эльфийский лес открыл свои границы для торговцев",
    "Карательный отряд сжёг контрабандные склады",
    "Огромный караван с зерном прибыл в столицу",
    "Морские пираты захватили корабль с драгоценностями",
    "Королевская казна заказала партию магических артефактов",
    "Магический шторм разрушил несколько торговых путей",
    "Слухи о проклятии на монетах Radcoin напугали крестьян",
    "Древний Лич обложил торговлю своей данью",
    "Таинственный покровитель выкупил часть монет у населения",
    "Орки предлагают мир в обмен на золото",
    "В городе открылась новая арена гладиаторских боёв",
    "Сектанты скупают странные артефакты за Radcoin",
    "Монастырь начал принимать пожертвования только в Radcoin",
    "Оракул предрёк рост стоимости магических ресурсов",
    "Купцы объединяются в гильдию и контролируют цены",
    "Порталы в другие миры открылись и принесли новые товары",
    "Некроманты торгуют душами в обход официального рынка",
    "В замке организован великий турнир с крупными ставками",
    "Дворянство массово скупает Radcoin для поддержания статуса",
    "Появился новый маг, способный дублировать предметы",
    "Столица была осаждена, и торговля временно остановилась",
    "На ярмарку прибыл караван из далёких пустынь",
]


@tasks.loop(seconds=60)
async def random_market_event_loop():
    if not is_enabled():
        return

    enabled = get_setting("random_events_enabled_global", "1") == "1"
    if not enabled:
        return

    interval_min = float(get_setting("random_event_interval_global_min",
                                     str(DEFAULT_RANDOM_EVENT_INTERVAL_MIN)))
    last_ts = float(get_setting("last_random_event_ts", "0"))
    now_ts = time.time()
    if now_ts - last_ts < interval_min * 60:
        return

    percent = random.uniform(-RANDOM_EVENT_MAX_PERCENT, RANDOM_EVENT_MAX_PERCENT)
    desc = random.choice(EVENT_DESCRIPTIONS)
    new_price = apply_event(percent)
    set_setting("last_random_event_ts", str(now_ts))

    sign = "+" if percent > 0 else ""
    text = (
        f"🌀 Случайное рыночное событие: **{desc}**\n"
        f"Изменение курса: **{sign}{percent:.2f}%**\n"
        f"Новый курс Radcoin: **{new_price:.2f}**"
    )

    for guild in bot.guilds:
        ch = guild.system_channel
        if ch:
            try:
                await ch.send(text)
            except Exception:
                continue


@bot.event
async def on_ready():
    print(f"Radonomy запущен как {bot.user}")

    # синхронизация slash-команд
    try:
        synced = await bot.tree.sync()
        print(f"Синхронизировано {len(synced)} slash-команд.")
    except Exception as e:
        print(f"Ошибка sync slash-команд: {e}")

    market = get_market()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) AS cnt FROM price_history")
    if c.fetchone()["cnt"] == 0:
        add_price_history(market["price"])
    conn.close()

    if not random_market_event_loop.is_running():
        random_market_event_loop.start()


# ============ RADCOIN КОМАНДЫ (HYBRID) ============

@commands.hybrid_command(name="price", description="Показать курс Radcoin")
async def price_cmd(ctx: commands.Context):
    market = get_market()
    boost_price = get_boost_price()
    await ctx.send(
        f"💱 Основной курс Radcoin: **{market['price']:.2f}** за 1.\n"
        f"✨ Бустер-курс: **{boost_price:.2f}** за 1."
    )


@commands.hybrid_command(name="balance", description="Показать баланс кошелька, банка и Radcoin")
async def balance_cmd(ctx: commands.Context):
    bal = get_user_balance(ctx.author.id)
    label = get_money_label()
    await ctx.send(
        f"💳 Баланс {ctx.author.mention}:\n"
        f"- {label.capitalize()} (кошелёк): **{bal['money']:.2f}**\n"
        f"- Банк: **{bal['bank']:.2f}**\n"
        f"- Radcoin: **{bal['radcoin']:.2f}**"
    )


@commands.hybrid_command(name="buy", description="Купить Radcoin по обычному курсу")
async def buy_cmd(ctx: commands.Context, amount: float):
    if amount <= 0:
        await ctx.send("Количество должно быть больше 0.")
        return
    market = get_market()
    price = market["price"]
    bal = get_user_balance(ctx.author.id)
    cost = price * amount
    if bal["money"] < cost:
        await ctx.send(f"Недостаточно {get_money_label()} для покупки.")
        return
    bal["money"] -= cost
    bal["radcoin"] += amount
    set_user_balance(bal)
    new_price = update_price_from_trade(buy_amount=amount, sell_amount=0)
    await ctx.send(
        f"✅ {ctx.author.mention} купил **{amount:.2f}** Radcoin за **{cost:.2f}** по цене **{price:.2f}**.\n"
        f"Новый курс Radcoin: **{new_price:.2f}**"
    )


@commands.hybrid_command(name="sell", description="Продать Radcoin по обычному курсу")
async def sell_cmd(ctx: commands.Context, amount: float):
    if amount <= 0:
        await ctx.send("Количество должно быть больше 0.")
        return
    market = get_market()
    price = market["price"]
    bal = get_user_balance(ctx.author.id)
    if bal["radcoin"] < amount:
        await ctx.send("У тебя нет столько Radcoin.")
        return
    gain = price * amount
    bal["radcoin"] -= amount
    bal["money"] += gain
    set_user_balance(bal)
    new_price = update_price_from_trade(buy_amount=0, sell_amount=amount)
    await ctx.send(
        f"✅ {ctx.author.mention} продал **{amount:.2f}** Radcoin и получил **{gain:.2f}** по цене **{price:.2f}**.\n"
        f"Новый курс Radcoin: **{new_price:.2f}**"
    )


@commands.hybrid_command(name="chart", description="График курса Radcoin")
async def chart_cmd(ctx: commands.Context):
    buf = generate_chart()
    if buf is None:
        await ctx.send("История курса Radcoin пока пуста.")
        return
    file = discord.File(buf, filename="radcoin_chart.png")
    await ctx.send("📈 История курса Radcoin:", file=file)


@commands.hybrid_command(name="radcase", description="Открыть премиум-кейс (роль премиум)")
async def radcase_cmd(ctx: commands.Context):
    if ctx.guild is None:
        await ctx.send("Только на сервере.")
        return
    member = ctx.author
    if not is_premium(member):
        await ctx.send("Команда только для роли Premium/Премиум.")
        return
    bal = get_user_balance(member.id)
    can_open, wait_sec = can_open_case(bal)
    if not can_open:
        hours = wait_sec / 3600
        await ctx.send(f"Кейс уже открыт. Подожди ещё **{hours:.1f}** ч.")
        return
    market = get_market()
    price = market["price"] or MIN_PRICE
    base_amount = CASE_BASE_VALUE / price
    amount = base_amount * random.uniform(0.8, 1.2)
    amount = max(1.0, amount)
    bal["radcoin"] += amount
    mark_case_opened(bal)
    set_user_balance(bal)
    await ctx.send(
        f"🎁 {member.mention} открыл премиум-кейс и получил **{amount:.2f}** Radcoin!\n"
        f"(Курс: **{price:.2f}**)"
    )


# ============ БУСТЕР-СДЕЛКИ ============

@commands.hybrid_command(name="boostbuy", description="Бустер-покупка Radcoin (до 10% объёма, -10% к цене)")
async def boost_buy_cmd(ctx: commands.Context, amount: float):
    if ctx.guild is None:
        await ctx.send("Только на сервере.")
        return
    member = ctx.author
    if not is_booster(member):
        await ctx.send("Только для роли бустера или Nitro-boost.")
        return
    if amount <= 0:
        await ctx.send("Количество должно быть больше 0.")
        return
    bal = get_user_balance(member.id)
    if not can_do_boost_trade(bal):
        await ctx.send("Бустер-сделка уже использована сегодня.")
        return
    boost_price = get_boost_price()
    effective = boost_price * 0.9
    max_possible = bal["money"] / effective if effective > 0 else 0
    max_allowed = max_possible * 0.10
    if amount > max_allowed:
        await ctx.send(f"Можно купить максимум **{max_allowed:.2f}** Radcoin (10% от доступного объёма).")
        return
    cost = effective * amount
    if bal["money"] < cost:
        await ctx.send(f"Недостаточно {get_money_label()} для бустер-покупки.")
        return
    bal["money"] -= cost
    bal["radcoin"] += amount
    mark_boost_trade_done(bal)
    set_user_balance(bal)
    new_price = update_price_from_trade(buy_amount=amount, sell_amount=0)
    await ctx.send(
        f"✨ Бустер-сделка! {member.mention} купил **{amount:.2f}** Radcoin по **{effective:.2f}**.\n"
        f"Потрачено: **{cost:.2f}**.\n"
        f"Новый курс: **{new_price:.2f}**"
    )


@commands.hybrid_command(name="boostsell", description="Бустер-продажа Radcoin (до 10% баланса, +10% к цене)")
async def boost_sell_cmd(ctx: commands.Context, amount: float):
    if ctx.guild is None:
        await ctx.send("Только на сервере.")
        return
    member = ctx.author
    if not is_booster(member):
        await ctx.send("Только для роли бустера или Nitro-boost.")
        return
    if amount <= 0:
        await ctx.send("Количество должно быть больше 0.")
        return
    bal = get_user_balance(member.id)
    if not can_do_boost_trade(bal):
        await ctx.send("Бустер-сделка уже использована сегодня.")
        return
    if bal["radcoin"] <= 0:
        await ctx.send("У тебя нет Radcoin.")
        return
    max_allowed = bal["radcoin"] * 0.10
    if amount > max_allowed:
        await ctx.send(f"Можно продать максимум **{max_allowed:.2f}** Radcoin (10% от баланса).")
        return
    boost_price = get_boost_price()
    effective = boost_price * 1.1
    gain = effective * amount
    bal["radcoin"] -= amount
    bal["money"] += gain
    mark_boost_trade_done(bal)
    set_user_balance(bal)
    new_price = update_price_from_trade(buy_amount=0, sell_amount=amount)
    await ctx.send(
        f"✨ Бустер-сделка! {member.mention} продал **{amount:.2f}** Radcoin по **{effective:.2f}**.\n"
        f"Получено: **{gain:.2f}**.\n"
        f"Новый курс: **{new_price:.2f}**"
    )


# ============ АДМИН: СОБЫТИЯ И РУЧНОЙ КУРС ============

@commands.hybrid_command(name="event", description="Ручное событие, меняющее курс Radcoin")
@commands.has_permissions(administrator=True)
async def event_cmd(ctx: commands.Context, percent: float, *, description: str = ""):
    new_price = apply_event(percent)
    sign = "+" if percent > 0 else ""
    await ctx.send(
        f"📢 Событие: **{description or 'без описания'}**\n"
        f"Изменение курса: **{sign}{percent:.2f}%**\n"
        f"Новый курс Radcoin: **{new_price:.2f}**"
    )


@commands.hybrid_command(name="radsetprice", description="Жёстко установить курс Radcoin (опасно)")
async def radsetprice_cmd(ctx: commands.Context, new_price: float):
    if not await has_econ_admin(ctx):
        await ctx.send("❌ У тебя нет прав для radsetprice.")
        return
    clamped = clamp_price(new_price)
    await ctx.send(
        f"⚠️ Ты собираешься вручную установить курс Radcoin на **{clamped:.2f}**.\n"
        f"Это может сломать экономику.\n"
        f"Напиши `да` или `yes` в течение 30 секунд для подтверждения."
    )

    def check(m: discord.Message):
        return m.author == ctx.author and m.channel == ctx.channel

    try:
        reply = await bot.wait_for("message", timeout=30.0, check=check)
    except asyncio.TimeoutError:
        await ctx.send("⏱ Время вышло. Операция отменена.")
        return

    if reply.content.lower() not in ("да", "yes", "y", "д"):
        await ctx.send("❎ Операция отменена.")
        return

    market = get_market()
    market["price"] = clamped
    _update_boost_price(market, clamped)
    save_market(market)
    add_price_history(clamped)

    await ctx.send(f"✅ Курс Radcoin установлен на **{clamped:.2f}**.")


@commands.hybrid_command(name="radgrant",
                         description="Выдать игроку Radcoin и списать с него деньги")
async def radgrant_cmd(ctx: commands.Context,
                       member: discord.Member,
                       rad_amount: float,
                       money_cost: float):
    if ctx.guild is None:
        await ctx.send("Только на сервере.")
        return
    if not has_banker_permission(ctx):
        await ctx.send("Нет прав для radgrant.")
        return
    if rad_amount <= 0 or money_cost < 0:
        await ctx.send("Radcoin > 0, стоимость >= 0.")
        return
    bal = get_user_balance(member.id)
    if bal["money"] < money_cost:
        await ctx.send("У игрока недостаточно средств.")
        return
    bal["money"] -= money_cost
    bal["radcoin"] += rad_amount
    set_user_balance(bal)
    await ctx.send(
        f"🏦 {member.mention} получил **{rad_amount:.2f}** Radcoin, "
        f"списано **{money_cost:.2f}** {get_money_label()}."
    )


# ============ ECON (WORK, DEP, WITH, ROULETTE, ROB, SLUT, INCOME, BLACKJACK) ============

def format_cd(seconds: float) -> str:
    if seconds <= 0:
        return "0с"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    parts = []
    if h:
        parts.append(f"{h}ч")
    if m:
        parts.append(f"{m}м")
    if s and not h:
        parts.append(f"{s}с")
    return " ".join(parts)


@commands.hybrid_command(name="work", description="Поработать и получить деньги")
async def work_cmd(ctx: commands.Context):
    bal = get_user_balance(ctx.author.id)
    now = time.time()
    cd = get_econ_setting("work_cd")
    last = bal.get("last_work_ts") or 0
    remaining = cd - (now - last)
    if remaining > 0:
        await ctx.send(f"⏱ Ты уже работал. Попробуй через **{format_cd(remaining)}**.")
        return
    mn = get_econ_setting("work_min")
    mx = get_econ_setting("work_max")
    reward = random.uniform(mn, mx)
    bal["money"] += reward
    bal["last_work_ts"] = now
    set_user_balance(bal)
    await ctx.send(
        f"🛠 {ctx.author.mention} поработал и получил **{reward:.2f}** {get_money_label()}."
    )


@commands.hybrid_command(name="dep", description="Положить деньги в банк (можно 'all')")
async def dep_cmd(ctx: commands.Context, amount: str):
    bal = get_user_balance(ctx.author.id)
    label = get_money_label()
    if amount.lower() == "all":
        amt = bal["money"]
    else:
        try:
            amt = float(amount)
        except ValueError:
            await ctx.send("Введите число или `all`.")
            return
    if amt <= 0:
        await ctx.send("Сумма должна быть больше 0.")
        return
    if bal["money"] < amt:
        await ctx.send(f"Недостаточно {label} в кошельке.")
        return
    bal["money"] -= amt
    bal["bank"] += amt
    set_user_balance(bal)
    await ctx.send(
        f"🏦 {ctx.author.mention} положил в банк **{amt:.2f}** {label}."
    )


@commands.hybrid_command(name="with", description="Снять деньги из банка (можно 'all')")
async def with_cmd(ctx: commands.Context, amount: str):
    bal = get_user_balance(ctx.author.id)
    label = get_money_label()
    if amount.lower() == "all":
        amt = bal["bank"]
    else:
        try:
            amt = float(amount)
        except ValueError:
            await ctx.send("Введите число или `all`.")
            return
    if amt <= 0:
        await ctx.send("Сумма должна быть больше 0.")
        return
    if bal["bank"] < amt:
        await ctx.send("Недостаточно средств в банке.")
        return
    bal["bank"] -= amt
    bal["money"] += amt
    set_user_balance(bal)
    await ctx.send(
        f"🏧 {ctx.author.mention} снял из банка **{amt:.2f}** {label}."
    )


@commands.hybrid_command(name="roulette", description="Рулетка Radonomy")
async def roulette_cmd(ctx: commands.Context, amount: float):
    if amount <= 0:
        await ctx.send("Ставка должна быть > 0.")
        return
    max_bet = get_econ_setting("roulette_max_bet")
    if amount > max_bet:
        await ctx.send(f"Максимальная ставка рулетки: **{max_bet:.2f}**.")
        return
    bal = get_user_balance(ctx.author.id)
    if bal["money"] < amount:
        await ctx.send(f"Недостаточно {get_money_label()} для ставки.")
        return
    bal["money"] -= amount
    if random.random() < 0.47:  # ~47% выигрыш 2x
        win = amount * 2
        bal["money"] += win
        result = f"🎰 Ты выиграл! Получено **{win:.2f}**."
    else:
        result = f"🎰 Проигрыш. Потеряно **{amount:.2f}**."
    bal["last_roulette_ts"] = time.time()
    set_user_balance(bal)
    await ctx.send(f"{ctx.author.mention} {result}")


@commands.hybrid_command(name="rob", description="Попытаться ограбить игрока")
async def rob_cmd(ctx: commands.Context, target: discord.Member):
    if target.bot:
        await ctx.send("Нельзя грабить ботов.")
        return
    if target.id == ctx.author.id:
        await ctx.send("Нельзя грабить самого себя.")
        return
    robber = get_user_balance(ctx.author.id)
    victim = get_user_balance(target.id)
    now = time.time()
    cd = get_econ_setting("rob_cd")
    last = robber.get("last_rob_ts") or 0
    remaining = cd - (now - last)
    if remaining > 0:
        await ctx.send(f"⏱ Грабёж на КД. Подожди **{format_cd(remaining)}**.")
        return
    if victim["money"] < 100:
        await ctx.send("У жертвы слишком мало денег, невыгодно.")
        return
    rob_min = get_econ_setting("rob_min")
    rob_max = get_econ_setting("rob_max")
    success_chance = get_econ_setting("rob_success")
    if random.random() < success_chance:
        stolen = random.uniform(rob_min, min(rob_max, victim["money"] * 0.5))
        victim["money"] -= stolen
        robber["money"] += stolen
        text = f"🦹‍♂️ Успешный грабёж! Ты украл у {target.mention} **{stolen:.2f}** {get_money_label()}."
    else:
        fine = random.uniform(rob_min / 2, rob_max / 2)
        fine = min(fine, robber["money"])
        robber["money"] -= fine
        victim["money"] += fine
        text = f"🚓 Неудача! Стража поймала тебя, и ты заплатил **{fine:.2f}** штрафа {target.mention}."
    robber["last_rob_ts"] = now
    set_user_balance(robber)
    set_user_balance(victim)
    await ctx.send(f"{ctx.author.mention} {text}")


@commands.hybrid_command(name="slut", description="Риск/награда (как у UnbelievaBoat)")
async def slut_cmd(ctx: commands.Context):
    bal = get_user_balance(ctx.author.id)
    now = time.time()
    cd = get_econ_setting("slut_cd")
    last = bal.get("last_slut_ts") or 0
    remaining = cd - (now - last)
    if remaining > 0:
        await ctx.send(f"⏱ Подожди ещё **{format_cd(remaining)}**.")
        return
    mn = get_econ_setting("slut_min")
    mx = get_econ_setting("slut_max")
    success = get_econ_setting("slut_success")
    if random.random() < success:
        reward = random.uniform(mn, mx)
        bal["money"] += reward
        text = f"🔥 Рисковал — и повезло! +**{reward:.2f}** {get_money_label()}."
    else:
        loss = random.uniform(mn / 2, mx / 2)
        loss = min(loss, bal["money"])
        bal["money"] -= loss
        text = f"💀 Всё пошло не по плану. -**{loss:.2f}** {get_money_label()}."
    bal["last_slut_ts"] = now
    set_user_balance(bal)
    await ctx.send(f"{ctx.author.mention} {text}")


@commands.hybrid_command(name="collect-income", description="Забрать пассивный доход с банка")
async def collect_income_cmd(ctx: commands.Context):
    bal = get_user_balance(ctx.author.id)
    now = time.time()
    cd = get_econ_setting("income_cd")
    last = bal.get("last_income_ts") or 0
    remaining = cd - (now - last)
    if remaining > 0:
        await ctx.send(f"⏱ До следующего дохода: **{format_cd(remaining)}**.")
        return
    if bal["bank"] <= 0:
        await ctx.send("У тебя нет денег в банке для пассивного дохода.")
        return
    rate = get_econ_setting("income_rate")
    income = bal["bank"] * rate
    bal["money"] += income
    bal["last_income_ts"] = now
    set_user_balance(bal)
    await ctx.send(
        f"💹 {ctx.author.mention} получил пассивный доход **{income:.2f}** {get_money_label()} "
        f"(ставка {rate * 100:.2f}% от банка)."
    )


def draw_card():
    ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
    rank = random.choice(ranks)
    if rank in ("J", "Q", "K"):
        value = 10
    elif rank == "A":
        value = 11
    else:
        value = int(rank)
    return rank, value


def hand_value(cards):
    total = sum(v for _, v in cards)
    aces = sum(1 for r, _ in cards if r == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


@commands.hybrid_command(name="blackjack", aliases=["bj"], description="Сыграть в blackjack против дилера")
async def blackjack_cmd(ctx: commands.Context, bet: float):
    if bet <= 0:
        await ctx.send("Ставка должна быть > 0.")
        return
    max_bet = get_econ_setting("blackjack_max_bet")
    if bet > max_bet:
        await ctx.send(f"Максимальная ставка в blackjack: **{max_bet:.2f}**.")
        return
    bal = get_user_balance(ctx.author.id)
    if bal["money"] < bet:
        await ctx.send(f"Недостаточно {get_money_label()} для ставки.")
        return
    bal["money"] -= bet

    player = [draw_card(), draw_card()]
    dealer = [draw_card(), draw_card()]

    pv = hand_value(player)
    dv = hand_value(dealer)

    while pv < 17:
        player.append(draw_card())
        pv = hand_value(player)
        if pv > 21:
            break

    if pv <= 21:
        while dv < 17:
            dealer.append(draw_card())
            dv = hand_value(dealer)

    result = ""
    payout = 0.0
    if pv > 21:
        result = "Ты перебрал (больше 21). Проигрыш."
    elif dv > 21:
        result = "Дилер перебрал! Ты выиграл."
        payout = bet * 2
    elif pv > dv:
        result = "Ты выиграл!"
        payout = bet * 2
    elif pv < dv:
        result = "Ты проиграл."
    else:
        result = "Ничья. Ставка возвращена."
        payout = bet

    bal["money"] += payout
    bal["last_blackjack_ts"] = time.time()
    set_user_balance(bal)

    def fmt(cards):
        return " ".join(r for r, _ in cards)

    await ctx.send(
        f"🃏 **Blackjack** для {ctx.author.mention}\n"
        f"Твои карты: `{fmt(player)}` (очков: {pv})\n"
        f"Карты дилера: `{fmt(dealer)}` (очков: {dv})\n"
        f"Результат: {result}\n"
        f"Изменение баланса: **{payout - bet:.2f}** {get_money_label()}."
    )


# ============ RADHELP ============

@commands.hybrid_command(name="radhelp", description="Показать помощь по Radonomy")
async def radhelp_cmd(ctx: commands.Context):
    prefix = ctx.prefix
    await ctx.send(
        f"📚 **Radonomy / Radcoin помощь**\n"
        f"Текущий префикс: `{prefix}`\n\n"
        f"**Экономика (как UnbelievaBoat):**\n"
        f"`/balance` — баланс кошелька / банка / Radcoin\n"
        f"`/work` — поработать и получить {get_money_label()}\n"
        f"`/dep <сумма|all>` — положить в банк\n"
        f"`/with <сумма|all>` — снять из банка\n"
        f"`/roulette <ставка>` — рулетка\n"
        f"`/rob @игрок` — ограбить\n"
        f"`/slut` — риск / награда\n"
        f"`/collect-income` — пассивный доход с банка\n"
        f"`/blackjack <ставка>` — blackjack\n\n"
        f"**Radcoin рынок:**\n"
        f"`/price`, `/buy`, `/sell`, `/boostbuy`, `/boostsell`, `/radcase`, `/chart`\n\n"
        f"**Админ/банкир:**\n"
        f"`/radgrant`, `/radsetprice`, `/event`, `radsettings ...`\n"
        f"`radexport`, `radlive` — пока только по префиксу.\n"
    )


# ============ RADSETTINGS ============

def format_role_name(role_name: str | None, guild: discord.Guild) -> str:
    if not role_name:
        return "не настроена"
    role = discord.utils.get(guild.roles, name=role_name)
    if role:
        return role.mention
    return f"`{role_name}` (не найдена)"


@bot.command(name="radsettings")
@commands.has_permissions(administrator=True)
async def radsettings_cmd(ctx: commands.Context, action: str | None = None, *args):
    guild = ctx.guild
    if guild is None:
        await ctx.send("Настройки доступны только на сервере.")
        return
    gs = get_guild_settings(guild.id)

    if action is None or action.lower() == "show":
        channel_id = gs["channel_id"]
        ch = guild.get_channel(channel_id) if channel_id else None
        channel_text = ch.mention if ch else "не настроен"
        glob_enabled = get_setting("random_events_enabled_global", "1") == "1"
        glob_interval = float(get_setting("random_event_interval_global_min",
                                          str(DEFAULT_RANDOM_EVENT_INTERVAL_MIN)))
        await ctx.send(
            f"⚙ **Radsettings для {guild.name}:**\n"
            f"- Префикс: `{gs['prefix']}`\n"
            f"- Канал для команд: {channel_text}\n"
            f"- Роль банкира: {format_role_name(gs['banker_role'], guild)}\n"
            f"- Роль бустера: {format_role_name(gs['booster_role'], guild)}\n"
            f"- Роль премиум: {format_role_name(gs['premium_role'], guild)}\n"
            f"- Роль админа экономики: {format_role_name(gs['admin_role'], guild)}\n"
            f"- Рандом-события (глобально): {'включены' if glob_enabled else 'выключены'}\n"
            f"- Интервал рандом-событий: **{glob_interval:.1f}** мин\n"
            f"- Название валюты: **{get_money_label()}**\n\n"
            f"Примеры:\n"
            f"`{ctx.prefix}radsettings prefix ?`\n"
            f"`{ctx.prefix}radsettings channel #канал` или `radsettings channel off`\n"
            f"`{ctx.prefix}radsettings banker_role Казначей`\n"
            f"`{ctx.prefix}radsettings booster_role Бустер`\n"
            f"`{ctx.prefix}radsettings premium_role Премиум`\n"
            f"`{ctx.prefix}radsettings admin_role Админ экономики`\n"
            f"`{ctx.prefix}radsettings events on/off`\n"
            f"`{ctx.prefix}radsettings events_interval 30`\n"
            f"`{ctx.prefix}radsettings money_label UnbelievaBoat coins`\n"
            f"`{ctx.prefix}radsettings econ show`"
        )
        return

    action = action.lower()

    if action == "prefix":
        if not args:
            await ctx.send("Укажи новый префикс. Пример: `radsettings prefix ?`")
            return
        new_prefix = args[0]
        set_guild_prefix(guild.id, new_prefix)
        await ctx.send(f"Префикс изменён на `{new_prefix}`.")
        return

    if action == "channel":
        if args and args[0].lower() in ("off", "none", "disable"):
            set_guild_channel_id(guild.id, None)
            await ctx.send("🔇 Ограничение по каналу отключено.")
            return
        channel = None
        if ctx.message.channel_mentions:
            channel = ctx.message.channel_mentions[0]
        elif args:
            try:
                ch_id = int(args[0])
                channel = guild.get_channel(ch_id)
            except ValueError:
                channel = None
        if channel is None:
            channel = ctx.channel
        set_guild_channel_id(guild.id, channel.id)
        await ctx.send(f"✅ Теперь команды Radonomy работают только в канале {channel.mention}.")
        return

    if action == "events":
        if not args:
            await ctx.send("Укажи `on` или `off`.")
            return
        mode = args[0].lower()
        if mode == "on":
            set_setting("random_events_enabled_global", "1")
            await ctx.send("Рандом-события включены.")
        elif mode == "off":
            set_setting("random_events_enabled_global", "0")
            await ctx.send("Рандом-события выключены.")
        else:
            await ctx.send("Используй `on` или `off`.")
        return

    if action == "events_interval":
        if not args:
            await ctx.send("Укажи интервал в минутах.")
            return
        try:
            minutes = float(args[0])
        except ValueError:
            await ctx.send("Интервал должен быть числом.")
            return
        minutes = max(1.0, minutes)
        set_setting("random_event_interval_global_min", str(minutes))
        await ctx.send(f"Интервал рандом-событий: **{minutes:.1f}** мин.")
        return

    if action in ("banker_role", "booster_role", "premium_role", "admin_role"):
        if not args:
            await ctx.send("Укажи имя роли.")
            return
        role_name = " ".join(args)
        set_guild_role(guild.id, action, role_name)
        await ctx.send(f"{action} установлена как `{role_name}`.")
        return

    if action == "money_label":
        if not args:
            await ctx.send("Укажи название валюты. Пример: `radsettings money_label UnbelievaBoat coins`.")
            return
        label = " ".join(args)
        set_setting("money_label", label)
        await ctx.send(f"Название валюты изменено на **{label}**.")
        return

    if action == "econ":
        if not args or args[0].lower() == "show":
            lines = []
            for key, default in ECON_DEFAULTS.items():
                val = get_econ_setting(key)
                lines.append(f"- {key}: **{val}** (по умолч. {default})")
            await ctx.send(
                "⚙ **Настройки экономики Radonomy:**\n" +
                "\n".join(lines) + "\n\n" +
                f"Менять: `{ctx.prefix}radsettings econ <параметр> <значение>`\n"
                f"Например: `{ctx.prefix}radsettings econ work_cd 600`"
            )
            return
        name = args[0].lower()
        if name not in ECON_DEFAULTS:
            await ctx.send(
                "Неизвестный параметр. Используй `radsettings econ show`, чтобы увидеть список."
            )
            return
        if len(args) < 2:
            await ctx.send("Укажи значение. Пример: `radsettings econ work_cd 600`.")
            return
        try:
            val = float(args[1])
        except ValueError:
            await ctx.send("Значение должно быть числом.")
            return
        set_setting(f"econ_{name}", str(val))
        await ctx.send(f"Параметр **{name}** установлен на **{val}**.")
        return

    await ctx.send("Неизвестное действие. Используй `radsettings show`.")


# ============ RADLIVE & EXPORT ============

@bot.command(name="radlive")
async def radlive_cmd(ctx: commands.Context, duration: int = 60):
    duration = max(10, min(duration, 300))
    interval = 5
    cycles = duration // interval
    market = get_market()
    msg = await ctx.send(
        f"📡 Live Radcoin ({duration} сек)\n"
        f"Курс: **{market['price']:.2f}** | Бустер: **{market['boost_price']:.2f}**"
    )
    remaining = duration
    for _ in range(cycles):
        await asyncio.sleep(interval)
        remaining -= interval
        market = get_market()
        try:
            await msg.edit(
                content=(
                    f"📡 Live Radcoin (осталось ~{remaining} сек)\n"
                    f"Курс: **{market['price']:.2f}** | Бустер: **{market['boost_price']:.2f}**"
                )
            )
        except discord.HTTPException:
            break


@bot.command(name="radexport")
@commands.has_permissions(administrator=True)
async def radexport_cmd(ctx: commands.Context):
    conn = get_db()
    users_df = pd.read_sql_query("SELECT * FROM users", conn)
    hist_df = pd.read_sql_query("SELECT * FROM price_history ORDER BY id ASC", conn)
    market_df = pd.read_sql_query("SELECT * FROM market", conn)
    conn.close()
    filename = f"radonomy_export_{int(time.time())}.xlsx"
    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        users_df.to_excel(writer, sheet_name="Users", index=False)
        hist_df.to_excel(writer, sheet_name="PriceHistory", index=False)
        market_df.to_excel(writer, sheet_name="Market", index=False)
    file = discord.File(filename, filename=os.path.basename(filename))
    await ctx.send("📤 Экспорт экономики Radonomy:", file=file)
    try:
        os.remove(filename)
    except OSError:
        pass


# ============ ГЛОБАЛЬНОЕ ВКЛ/ВЫКЛ И SHUTDOWN ============

@bot.command(name="disablebot")
@commands.is_owner()
async def disable_bot_cmd(ctx: commands.Context):
    set_enabled(False)
    await ctx.send("🔴 Radonomy отключён глобально.")


@bot.command(name="enablebot")
@commands.is_owner()
async def enable_bot_cmd(ctx: commands.Context):
    set_enabled(True)
    await ctx.send("🟢 Radonomy снова включён.")


@bot.command(name="shutdown")
@commands.is_owner()
async def shutdown_cmd(ctx: commands.Context):
    await ctx.send("🛑 Radonomy выключается...")
    await bot.close()


# ============ ЗАПУСК ============

if __name__ == "__main__":
    bot.run(TOKEN)
