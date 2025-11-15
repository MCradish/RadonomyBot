import os
import random
import sqlite3
import datetime
from typing import Optional, List, Dict

import discord
from discord import app_commands
from discord.ext import commands, tasks

# ===================== НАСТРОЙКА ТОКЕНА =====================

TOKEN = os.getenv("TOKEN")  # На Render в переменных окружения

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

DB_NAME = "economy.db"

# ===================== БАЗА ДАННЫХ =========================

def db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def setup_db():
    conn = db()
    c = conn.cursor()

    # Таблица пользователей
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            coins INTEGER DEFAULT 0,
            radcoin INTEGER DEFAULT 0,
            last_work TEXT,
            last_crime TEXT,
            last_slut TEXT,
            last_income TEXT,
            last_rob TEXT,
            last_roulette TEXT,
            last_blackjack TEXT
        )
    """)

    # На случай старых версий — добавляем недостающие колонки
    c.execute("PRAGMA table_info(users)")
    cols = [row["name"] for row in c.fetchall()]
    needed = [
        "coins", "radcoin",
        "last_work", "last_crime", "last_slut",
        "last_income", "last_rob",
        "last_roulette", "last_blackjack"
    ]
    for col in needed:
        if col not in cols:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")

    # Таблица настроек экономики
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Таблица дохода по ролям для /collect-income
    c.execute("""
        CREATE TABLE IF NOT EXISTS collect_roles (
            role_id INTEGER PRIMARY KEY,
            amount INTEGER NOT NULL
        )
    """)

    conn.commit()
    conn.close()


setup_db()

# ===================== НАСТРОЙКИ ЭКОНОМИКИ ==================

DEFAULT_SETTINGS = {
    # work
    "work_cd_hours": 1,
    "work_min": 40,
    "work_max": 90,

    # crime
    "crime_cd_hours": 1,
    "crime_gain_min": 120,
    "crime_gain_max": 260,
    "crime_loss_min": 80,
    "crime_loss_max": 180,
    "crime_success": 0.6,       # 60% успеха

    # slut
    "slut_cd_hours": 1,
    "slut_gain_min": 100,
    "slut_gain_max": 220,
    "slut_loss_min": 60,
    "slut_loss_max": 160,
    "slut_success": 0.7,        # 70% успеха

    # rob
    "rob_cd_hours": 1,
    "rob_success": 0.25,        # 25% успеха
    "rob_gain_min_percent": 5,  # % от монет цели
    "rob_gain_max_percent": 20,
    "rob_penalty_min": 80,
    "rob_penalty_max": 150,

    # collect-income
    "income_cd_hours": 24,

    # roulette
    "roulette_cd_minutes": 1,
    "roulette_min_bet": 10,
    "roulette_max_bet": 1000,
    "roulette_payout_red_black": 2.0,
    "roulette_payout_green": 14.0,

    # blackjack
    "blackjack_cd_minutes": 1,
    "blackjack_min_bet": 10,
    "blackjack_max_bet": 1000,
    "blackjack_blackjack_payout": 1.5,  # 3:2
    "blackjack_dealer_hits_soft17": 1,

    # общий шанс бонусного radcoin
    "radcoin_bonus_chance": 0.05,
}


def get_setting(key: str) -> float:
    conn = db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    if row is None:
        default = DEFAULT_SETTINGS.get(key, 0)
        c.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)",
            (key, str(default)),
        )
        conn.commit()
        conn.close()
        return float(default)
    conn.close()
    return float(row["value"])


def set_setting(key: str, value: float):
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


# ===================== ДОХОД ПО РОЛЯМ ДЛЯ COLLECT ====================

def get_collect_roles() -> Dict[int, int]:
    conn = db()
    c = conn.cursor()
    c.execute("SELECT role_id, amount FROM collect_roles")
    rows = c.fetchall()
    conn.close()
    return {row["role_id"]: row["amount"] for row in rows}


def set_collect_role_db(role_id: int, amount: int):
    conn = db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO collect_roles (role_id, amount) VALUES (?, ?) "
        "ON CONFLICT(role_id) DO UPDATE SET amount = excluded.amount",
        (role_id, amount),
    )
    conn.commit()
    conn.close()


# ===================== ТЕКСТЫ СОБЫТИЙ =======================

WORK_EVENTS = [
    "Ты честно отработал смену на складе и получил премию.",
    "Ты помог коллеге закрыть отчёты вовремя — начальство довольно.",
    "Ты вышел подменить заболевшего сотрудника.",
    "Ты задержался после смены и разобрал завалившиеся заявки.",
    "Ты разрулил конфликт с клиентом лучше всех в отделе.",
    "Ты придумал мелкое улучшение на работе, и его сразу внедрили.",
    "Ты помог новенькому быстро влиться в коллектив.",
    "Ты вовремя заметил ошибку в документах и спас компанию от штрафа.",
    "Ты вышел в выходной и закрыл срочный заказ.",
    "Ты спокойно отдежурил ночь, без происшествий.",
    "Ты принёс всем кофе и поднял команде настроение.",
    "Ты правильно распределил задачи и все всё успели.",
    "Ты нашёл способ сэкономить ресурсы компании.",
    "Ты собрался и идеально закрыл важное задание.",
    "Ты взял на себя сложную задачу, и у тебя всё получилось.",
    "Ты помог коллегам и получил благодарность от руководства.",
    "Ты принял сложное решение, и оно оказалось верным.",
    "Ты навёл порядок там, где все давно махнули рукой.",
    "Ты проявил инициативу и это заметили.",
    "Ты просто честно отработал свой день. Спокойно и без лишнего шума.",
]

CRIME_SUCCESS_EVENTS = [
    "Ты удачно ограбил старушку на рынке и тихо растворился в толпе.",
    "Ты вскрыл оставленный без присмотра сейф в заброшенном офисе.",
    "Ты провернул аферу с поддельными лотерейными билетами.",
    "Ты обчистил карманы в переполненном трамвае.",
    "Ты продал ворованный смартфон на чёрном рынке.",
    "Ты перехватил чужую доставку с деньгами.",
    "Ты ограбил небольшой ларёк поздно ночью.",
    "Ты провернул мошенничество с переводами и тебя не отследили.",
    "Ты подрезал кошелёк у зазевавшегося туриста.",
    "Ты удачно «позаимствовал» выручку из кассы.",
    "Ты провернул схему с фальшивыми купонами.",
    "Ты стянул пачку денег из незапертого сейфа.",
    "Ты взломал старый банкомат и забрал наличку.",
    "Ты нашёл чемодан с деньгами и никому не рассказал.",
    "Ты провернул рискованное ограбление, но всё прошло гладко.",
    "Ты подставил другого и ушёл с наградой.",
    "Ты провернул тёмную сделку во дворе.",
    "Ты обокрал богатого, который этого даже не заметит.",
    "Ты успешно перепродал украденные вещи.",
    "Ты сыграл грязно — но результат того стоил.",
]

CRIME_FAIL_EVENTS = [
    "Тебя поймали на месте преступления и выписали штраф.",
    "Камеры наблюдения засняли тебя — пришлось платить откуп.",
    "Твой напарник оказался стукачом, и ты отделался только штрафом.",
    "Ты споткнулся на бегу и тебя поймали.",
    "Жертва оказалась сильнее, чем выглядела, и заставила платить за наглость.",
    "Полиция устроила засаду именно там, где ты решил промышлять.",
    "Ты попался на фальшивых купюрах и вынужден был заплатить сверху.",
    "Ты неудачно спрятался и тебя быстро нашли.",
    "Ты забыл выключить геолокацию и тебя вычислили.",
    "Ты решил сбежать через двор с собаками — плохая идея.",
    "Тебя опознали свидетели и ты заплатил, чтобы замять дело.",
    "Ты оставил отпечатки пальцев и пришлось откупаться.",
    "Ты перепутал «жертву» и нарвался на уголовного авторитета.",
    "Ты забыл надеть маску и тебя узнали.",
    "Ты слишком громко хвастался добычей и тебя сдали.",
    "Ты попался на горячем прямо при попытке взлома.",
    "Ты потерял украденное и ещё и заплатил штраф.",
    "Ты нарвался на рейд полиции.",
    "Ты решил вернуться на место преступления и пожалел об этом.",
    "Ты поверил сомнительному плану и был наказан монетами.",
]

SLUT_SUCCESS_EVENTS = [
    "Ты провёл тёплый вечер с состоятельным клиентом.",
    "Ты получил щедрые чаевые за необычный подход.",
    "Ты весь вечер развлекал VIP-гостей закрытой вечеринки.",
    "Ты очаровал клиента с первого взгляда.",
    "Ты встретил щедрого завсегдатая и он не поскупился.",
    "Ты получил оплату вперёд и ещё сверху бонус.",
    "Ты попал на корпоратив, где всем было очень весело.",
    "Ты очаровал группу туристов и они решили щедро отблагодарить.",
    "Ты устроил незабываемый вечер и получил соответствующую оплату.",
    "Ты нашёл богатого клиента, который любит тратить деньги.",
    "Ты получил гонорар за особые услуги по особому тарифу.",
    "Ты провёл ночь в дорогом отеле за чужой счёт.",
    "Ты получил крупный перевод от анонимного поклонника.",
    "Ты понравился компании и тебя осыпали деньгами.",
    "Ты устроил огненное шоу и сорвал куш.",
    "Ты получил заказ по рекомендации — и явно не прогадал.",
    "Ты убедил клиента оформить «VIP-пакет».",
    "Ты справился с заказом, от которого все остальные отказались.",
    "Ты получил бонус за «пунктуальность и гибкость».",
    "Ты провёл смену без простоев и всё время был при деле.",
]

SLUT_FAIL_EVENTS = [
    "Клиент оказался жадным и захотел вернуть часть денег.",
    "Клиент пропал, не заплатив по счёту.",
    "Тебя кинули с переводом и ты остался в минусе.",
    "Клиент отменил встречу в последний момент и потребовал компенсацию.",
    "Тебя обманули с фальшивой купюрой.",
    "Ты поругался с клиентом и пришлось вернуть деньги.",
    "Тебе попался токсичный клиент, который выбил из тебя компенсацию.",
    "Клиент написал жалобу и с тебя удержали штраф.",
    "Тебя обманули с курсом валют и ты потерял часть заработка.",
    "Ты нечаянно разбил что-то дорогое и оплатил ущерб.",
    "Клиент оказался знакомым начальника и всё обошлось минусом.",
    "Клиент ушёл, не заплатив за дополнительный сервис.",
    "Твой агент забрал слишком большую комиссию.",
    "Ты попал под проверку и часть денег забрали.",
    "Тебя подвели с транспортом и ты оплатил такси сам.",
    "Ты случайно оскорбил клиента и тот заставил вернуть деньги.",
    "Ты потратился на костюм к встрече и это не окупилось.",
    "Тебе пришлось сделать скидку, чтобы избежать проблем.",
    "Клиент оказался мошенником и оформил возврат.",
    "Ты переоценил свои силы и остался в убытке.",
]

ROB_SUCCESS_EVENTS = [
    "Ты незаметно стянул кошелёк у цели.",
    "Ты подкараулил жертву в переулке и забрал часть налички.",
    "Ты ловко выдернул кошелёк, пока жертва отвлеклась.",
    "Ты провернул карманную кражу в толпе.",
    "Ты обчистил задний карман, и жертва ничего не почувствовала.",
]

ROB_FAIL_EVENTS = [
    "Цель заметила попытку ограбления и вызвала охрану.",
    "Тебя поймали за руку и заставили заплатить штраф.",
    "Жертва оказалась сильнее, чем ты думал — пришлось расплачиваться.",
    "Рядом был патруль, и тебе выписали крупный штраф.",
    "Тебя скрутили очевидцы и ты еле отделался штрафом.",
]

# ===================== УТИЛИТЫ ==============================

def get_user(user_id: int) -> sqlite3.Row:
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    if not user:
        c.execute(
            "INSERT INTO users (user_id, coins, radcoin) VALUES (?, 0, 0)",
            (user_id,),
        )
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
    conn.close()
    return user


def update_field(user_id: int, field: str, value):
    conn = db()
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()


def format_time(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}ч {m}м {s}с"


def progress_bar(passed: int, total: int):
    bar_len = 20
    percent = passed / total if total > 0 else 0
    filled = int(bar_len * percent)
    empty = bar_len - filled
    return "▰" * filled + "▱" * empty, int(percent * 100)


async def cooldown_check(
    interaction: discord.Interaction,
    last_time_str: Optional[str],
    cooldown_hours: float,
    title: str,
) -> bool:
    if last_time_str:
        last_time = datetime.datetime.fromisoformat(last_time_str)
        now = datetime.datetime.utcnow()
        delta = now - last_time
        delta_hours = delta.total_seconds() / 3600

        if delta_hours < cooldown_hours:
            total_seconds = int(cooldown_hours * 3600)
            passed_seconds = int(delta.total_seconds())
            remaining_seconds = max(0, total_seconds - passed_seconds)

            bar, percent = progress_bar(passed_seconds, total_seconds)

            embed = discord.Embed(
                title=f"⏳ {title} уже использована!",
                description=(
                    "Команда будет доступна через:\n"
                    f"**{format_time(remaining_seconds)}**\n\n"
                    f"Прогресс: `{bar}` **{percent}%**"
                ),
                color=0xFFCC00,
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
    return True


# ===================== /balance =============================

@bot.tree.command(
    name="balance",
    description="Показать твой баланс Coins и Radcoin.",
)
async def balance(interaction: discord.Interaction):
    user = get_user(interaction.user.id)
    embed = discord.Embed(
        title="💳 Баланс",
        description=(
            f"**Coins на руках:** `{user['coins']}`\n"
            f"**Radcoin:** `{user['radcoin']}`"
        ),
        color=0xF1C40F,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ===================== /work ================================

@bot.tree.command(
    name="work",
    description="Стабильная работа: всегда плюс, но не очень много.",
)
async def work(interaction: discord.Interaction):
    user = get_user(interaction.user.id)

    cd_hours = get_setting("work_cd_hours")
    if not await cooldown_check(interaction, user["last_work"], cd_hours, "Работа"):
        return

    work_min = int(get_setting("work_min"))
    work_max = int(get_setting("work_max"))
    amount = random.randint(work_min, work_max)

    event_text = random.choice(WORK_EVENTS)

    coins = user["coins"] + amount
    update_field(interaction.user.id, "coins", coins)
    update_field(
        interaction.user.id, "last_work", datetime.datetime.utcnow().isoformat()
    )

    bonus = ""
    if random.random() <= get_setting("radcoin_bonus_chance"):
        update_field(interaction.user.id, "radcoin", user["radcoin"] + 1)
        bonus = "\n🎉 Сегодня на работе тебе выдали **премию: +1 Radcoin!**"

    embed = discord.Embed(
        title="💼 Рабочая смена",
        description=f"{event_text}\n\nТы заработал **{amount}💰**.{bonus}",
        color=0x00FF99,
    )
    await interaction.response.send_message(embed=embed)


# ===================== /crime ===============================

@bot.tree.command(
    name="crime",
    description="Рискованное дело: можно поднять много, а можно улететь в минус.",
)
async def crime(interaction: discord.Interaction):
    user = get_user(interaction.user.id)

    cd_hours = get_setting("crime_cd_hours")
    if not await cooldown_check(interaction, user["last_crime"], cd_hours, "Crime"):
        return

    success_chance = get_setting("crime_success")
    success = random.random() < success_chance

    if success:
        gain_min = int(get_setting("crime_gain_min"))
        gain_max = int(get_setting("crime_gain_max"))
        amount = random.randint(gain_min, gain_max)
        event_text = random.choice(CRIME_SUCCESS_EVENTS)
        coins = user["coins"] + amount
        update_field(interaction.user.id, "coins", coins)

        bonus = ""
        if random.random() <= get_setting("radcoin_bonus_chance"):
            update_field(interaction.user.id, "radcoin", user["radcoin"] + 1)
            bonus = "\n🪙 В добыче затесался **1 Radcoin!**"

        color = 0x22CC22
        desc = f"{event_text}\n\nДобыча: **+{amount}💰**.{bonus}"
    else:
        loss_min = int(get_setting("crime_loss_min"))
        loss_max = int(get_setting("crime_loss_max"))
        amount = random.randint(loss_min, loss_max)
        event_text = random.choice(CRIME_FAIL_EVENTS)
        coins = max(0, user["coins"] - amount)
        update_field(interaction.user.id, "coins", coins)

        color = 0xCC2222
        desc = f"{event_text}\n\nШтраф: **-{amount}💰**."

    update_field(
        interaction.user.id, "last_crime", datetime.datetime.utcnow().isoformat()
    )

    embed = discord.Embed(
        title="🕵 Преступный промысел", description=desc, color=color
    )
    await interaction.response.send_message(embed=embed)


# ===================== /slut ================================

@bot.tree.command(
    name="slut",
    description="Грязный, но прибыльный заработок. Много денег, но бывают провалы.",
)
async def slut(interaction: discord.Interaction):
    user = get_user(interaction.user.id)

    cd_hours = get_setting("slut_cd_hours")
    if not await cooldown_check(interaction, user["last_slut"], cd_hours, "Slut"):
        return

    success_chance = get_setting("slut_success")
    success = random.random() < success_chance

    if success:
        gain_min = int(get_setting("slut_gain_min"))
        gain_max = int(get_setting("slut_gain_max"))
        amount = random.randint(gain_min, gain_max)
        event_text = random.choice(SLUT_SUCCESS_EVENTS)
        coins = user["coins"] + amount
        update_field(interaction.user.id, "coins", coins)

        bonus = ""
        if random.random() <= get_setting("radcoin_bonus_chance"):
            update_field(interaction.user.id, "radcoin", user["radcoin"] + 1)
            bonus = "\n💋 Клиент был особенно щедрым: **+1 Radcoin!**"

        color = 0xFF66CC
        desc = f"{event_text}\n\nЗаработано: **+{amount}💰**.{bonus}"
    else:
        loss_min = int(get_setting("slut_loss_min"))
        loss_max = int(get_setting("slut_loss_max"))
        amount = random.randint(loss_min, loss_max)
        event_text = random.choice(SLUT_FAIL_EVENTS)
        coins = max(0, user["coins"] - amount)
        update_field(interaction.user.id, "coins", coins)

        color = 0xCC1188
        desc = f"{event_text}\n\nУбыток: **-{amount}💰**."

    update_field(
        interaction.user.id, "last_slut", datetime.datetime.utcnow().isoformat()
    )

    embed = discord.Embed(
        title="💋 Ночная подработка", description=desc, color=color
    )
    await interaction.response.send_message(embed=embed)


# ===================== /rob ================================

@bot.tree.command(
    name="rob",
    description="Попробовать ограбить другого игрока. Маленький шанс успеха, большой штраф.",
)
@app_commands.describe(target="Кого пытаемся ограбить")
async def rob(interaction: discord.Interaction, target: discord.Member):
    if target.id == interaction.user.id:
        await interaction.response.send_message(
            "Нельзя ограбить самого себя 🙃", ephemeral=True
        )
        return
    if target.bot:
        await interaction.response.send_message(
            "Ботов ограбить не получится.", ephemeral=True
        )
        return

    robber = get_user(interaction.user.id)
    victim = get_user(target.id)

    cd_hours = get_setting("rob_cd_hours")
    if not await cooldown_check(interaction, robber["last_rob"], cd_hours, "Rob"):
        return

    success_chance = get_setting("rob_success")
    gain_min_percent = get_setting("rob_gain_min_percent")
    gain_max_percent = get_setting("rob_gain_max_percent")
    penalty_min = int(get_setting("rob_penalty_min"))
    penalty_max = int(get_setting("rob_penalty_max"))

    victim_coins = victim["coins"]
    success = random.random() < success_chance

    if success and victim_coins > 0:
        percent = random.uniform(gain_min_percent, gain_max_percent) / 100.0
        stolen = int(victim_coins * percent)
        if stolen < 1:
            stolen = 1

        new_robber_coins = robber["coins"] + stolen
        new_victim_coins = max(0, victim_coins - stolen)

        update_field(interaction.user.id, "coins", new_robber_coins)
        update_field(target.id, "coins", new_victim_coins)

        event_text = random.choice(ROB_SUCCESS_EVENTS)

        color = 0x00FF00
        desc = (
            f"{event_text}\n\n"
            f"Ты украл у {target.mention} **{stolen}💰** "
            f"(*{percent*100:.1f}%* от его монет на руках)."
        )
    else:
        penalty = random.randint(penalty_min, penalty_max)
        new_robber_coins = max(0, robber["coins"] - penalty)
        update_field(interaction.user.id, "coins", new_robber_coins)

        event_text = random.choice(ROB_FAIL_EVENTS)
        color = 0xFF0000
        desc = f"{event_text}\n\nШтраф: **-{penalty}💰**."

    update_field(
        interaction.user.id, "last_rob", datetime.datetime.utcnow().isoformat()
    )

    embed = discord.Embed(
        title="🔪 Попытка ограбления", description=desc, color=color
    )
    await interaction.response.send_message(embed=embed)


# ===================== /collect-income ======================

@bot.tree.command(
    name="collect-income",
    description="Собрать ежедневный пассивный доход.",
)
async def collect_income(interaction: discord.Interaction):
    user = get_user(interaction.user.id)

    cd_hours = get_setting("income_cd_hours")
    if not await cooldown_check(
        interaction, user["last_income"], cd_hours, "Доход"
    ):
        return

    base_income = 100  # базовый доход
    income = base_income
    breakdown = [f"Базовый доход: **{base_income}💰**"]

    # Роли вида: income_500, income_200 и т.п. (по названию роли)
    name_bonus = 0
    for role in interaction.user.roles:
        if role.name.startswith("income_"):
            try:
                add = int(role.name.split("_")[1])
                name_bonus += add
            except ValueError:
                pass
    if name_bonus:
        income += name_bonus
        breakdown.append(f"За роли (по имени): **{name_bonus}💰**")

    # Роли, настроенные через /set-collect-role (по ID ролей в БД)
    db_roles = get_collect_roles()
    db_bonus = 0
    for role in interaction.user.roles:
        amt = db_roles.get(role.id)
        if amt:
            db_bonus += amt
    if db_bonus:
        income += db_bonus
        breakdown.append(f"За роли (через /set-collect-role): **{db_bonus}💰**")

    coins = user["coins"] + income
    update_field(interaction.user.id, "coins", coins)
    update_field(
        interaction.user.id, "last_income", datetime.datetime.utcnow().isoformat()
    )

    breakdown.append(f"**Итого:** **{income}💰**")

    embed = discord.Embed(
        title="💰 Пассивный доход",
        description="\n".join(breakdown),
        color=0x33CC33,
    )
    await interaction.response.send_message(embed=embed)


# ===================== НАСТРОЙКА ДОХОДА ПО РОЛЯМ ============

@bot.tree.command(
    name="set-collect-role",
    description="Настроить доход /collect-income для роли (только админы).",
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    role="Роль, которой добавить доход",
    amount="Сколько Coins будет давать роль при /collect-income",
)
async def set_collect_role_cmd(
    interaction: discord.Interaction,
    role: discord.Role,
    amount: int,
):
    if amount < 0:
        await interaction.response.send_message(
            "Сумма не может быть отрицательной.", ephemeral=True
        )
        return

    set_collect_role_db(role.id, amount)
    embed = discord.Embed(
        title="✅ Настройка пассивного дохода",
        description=(
            f"Роль {role.mention} теперь даёт **{amount}💰** "
            f"при использовании `/collect-income`."
        ),
        color=0x2ECC71,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ===================== РУЛЕТКА ==============================

@bot.tree.command(
    name="roulette",
    description="Рулетка: поставь на красное, чёрное или зелёное.",
)
@app_commands.describe(
    amount="Сколько ставим (Coins)",
    color="На что ставим: red / black / green",
)
async def roulette(
    interaction: discord.Interaction,
    amount: int,
    color: app_commands.Choice[str],
):
    user = get_user(interaction.user.id)

    # КД
    cd_minutes = get_setting("roulette_cd_minutes")
    cd_hours = cd_minutes / 60.0
    if not await cooldown_check(
        interaction, user["last_roulette"], cd_hours, "Roulette"
    ):
        return

    min_bet = int(get_setting("roulette_min_bet"))
    max_bet = int(get_setting("roulette_max_bet"))

    if amount < min_bet or amount > max_bet:
        await interaction.response.send_message(
            f"Ставка должна быть от **{min_bet}** до **{max_bet}** Coins.",
            ephemeral=True,
        )
        return

    if amount > user["coins"]:
        await interaction.response.send_message(
            "У тебя нет столько Coins для ставки.", ephemeral=True
        )
        return

    bet_color = color.value  # "red" / "black" / "green"

    # Крутим рулетку (0–36)
    roll = random.randint(0, 36)
    if roll == 0:
        result_color = "green"
    elif roll % 2 == 0:
        result_color = "black"
    else:
        result_color = "red"

    payout_rb = get_setting("roulette_payout_red_black")
    payout_g = get_setting("roulette_payout_green")

    old_coins = user["coins"]
    new_coins = old_coins - amount  # сначала списываем ставку
    win = False
    win_amount = 0

    if bet_color == result_color:
        win = True
        if result_color == "green":
            win_amount = int(amount * payout_g)
        else:
            win_amount = int(amount * payout_rb)
        new_coins += amount + win_amount  # возврат ставки + выигрыш

    update_field(interaction.user.id, "coins", new_coins)
    update_field(
        interaction.user.id,
        "last_roulette",
        datetime.datetime.utcnow().isoformat(),
    )

    color_map = {"red": "🔴", "black": "⚫", "green": "🟢"}
    res_emoji = color_map.get(result_color, "🎲")

    if win:
        desc = (
            f"Выпало {res_emoji} **{result_color.upper()}** ({roll}).\n"
            f"Ты выиграл **+{win_amount}💰**!\n"
            f"Твой баланс: **{new_coins}💰**."
        )
        embed_color = 0x2ECC71
    else:
        desc = (
            f"Выпало {res_emoji} **{result_color.upper()}** ({roll}).\n"
            f"Ты проиграл ставку **-{amount}💰**.\n"
            f"Твой баланс: **{new_coins}💰**."
        )
        embed_color = 0xE74C3C

    embed = discord.Embed(
        title="🎰 Рулетка", description=desc, color=embed_color
    )
    await interaction.response.send_message(embed=embed)


@roulette.autocomplete("color")
async def roulette_color_autocomplete(
    interaction: discord.Interaction, current: str
):
    current = current.lower()
    options = [
        ("red", "red — красное"),
        ("black", "black — чёрное"),
        ("green", "green — зелёное (0)"),
    ]
    result: List[app_commands.Choice[str]] = []
    for value, label in options:
        if current in value or current in label:
            result.append(app_commands.Choice(name=label, value=value))
    return result[:25]


# ===================== БЛЭКДЖЕК ============================

# Упрощённый одностадийный блэкджек (без кнопок, авто-игра по базовой логике)

def draw_card():
    ranks = ["A"] + [str(i) for i in range(2, 11)] + ["J", "Q", "K"]
    suits = ["♠", "♥", "♦", "♣"]
    return random.choice(ranks), random.choice(suits)


def hand_value(cards):
    # cards: list[(rank, suit)]
    total = 0
    aces = 0
    for rank, _ in cards:
        if rank in ("J", "Q", "K"):
            total += 10
        elif rank == "A":
            total += 11
            aces += 1
        else:
            total += int(rank)
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def is_blackjack(cards):
    return len(cards) == 2 and hand_value(cards) == 21


@bot.tree.command(
    name="blackjack",
    description="Блэкджек против дилера. Автоигра по базовой логике.",
)
@app_commands.describe(amount="Ставка Coins")
async def blackjack(interaction: discord.Interaction, amount: int):
    user = get_user(interaction.user.id)

    cd_minutes = get_setting("blackjack_cd_minutes")
    cd_hours = cd_minutes / 60.0
    if not await cooldown_check(
        interaction, user["last_blackjack"], cd_hours, "Blackjack"
    ):
        return

    min_bet = int(get_setting("blackjack_min_bet"))
    max_bet = int(get_setting("blackjack_max_bet"))

    if amount < min_bet or amount > max_bet:
        await interaction.response.send_message(
            f"Ставка должна быть от **{min_bet}** до **{max_bet}** Coins.",
            ephemeral=True,
        )
        return

    if amount > user["coins"]:
        await interaction.response.send_message(
            "У тебя нет столько Coins для ставки.", ephemeral=True
        )
        return

    blackjack_payout = get_setting("blackjack_blackjack_payout")
    dealer_hits_soft17 = bool(get_setting("blackjack_dealer_hits_soft17"))

    # Списываем ставку
    coins = user["coins"] - amount

    # Раздача
    player = [draw_card(), draw_card()]
    dealer = [draw_card(), draw_card()]

    player_val = hand_value(player)
    dealer_val = hand_value(dealer)

    player_bj = is_blackjack(player)
    dealer_bj = is_blackjack(dealer)

    result_text = ""
    win_amount = 0

    # Проверяем блэкджеки
    if player_bj or dealer_bj:
        if player_bj and dealer_bj:
            # ничья
            coins += amount  # возврат ставки
            result_text = "Оба получили блэкджек. Ничья."
        elif player_bj:
            win_amount = int(amount * blackjack_payout)
            coins += amount + win_amount
            result_text = f"У тебя **Blackjack!** Выигрыш **+{win_amount}💰**."
        else:
            result_text = "У дилера Blackjack. Ты проиграл ставку."
    else:
        # Авто-логика игрока: тянем пока < 17
        while player_val < 17:
            player.append(draw_card())
            player_val = hand_value(player)
            if player_val > 21:
                break

        # Если игрок не сгорел, играет дилер
        if player_val <= 21:
            while True:
                dealer_val = hand_value(dealer)
                soft17 = dealer_val == 17 and any(
                    r == "A" for r, _ in dealer
                )
                if dealer_val < 17 or (soft17 and dealer_hits_soft17):
                    dealer.append(draw_card())
                    continue
                break

        dealer_val = hand_value(dealer)

        if player_val > 21:
            result_text = "Ты перебрал (больше 21). Ставка проиграна."
        elif dealer_val > 21:
            win_amount = amount
            coins += amount * 2
            result_text = (
                f"Дилер перебрал (**{dealer_val}**). Ты выиграл **+{win_amount}💰**."
            )
        else:
            if player_val > dealer_val:
                win_amount = amount
                coins += amount * 2
                result_text = (
                    f"У тебя **{player_val}**, у дилера **{dealer_val}**. "
                    f"Ты выиграл **+{win_amount}💰**."
                )
            elif player_val < dealer_val:
                result_text = (
                    f"У тебя **{player_val}**, у дилера **{dealer_val}**. "
                    f"Ты проиграл ставку."
                )
            else:
                coins += amount
                result_text = (
                    f"У тебя и у дилера **{player_val}**. Ничья, ставка возвращена."
                )

    update_field(interaction.user.id, "coins", coins)
    update_field(
        interaction.user.id,
        "last_blackjack",
        datetime.datetime.utcnow().isoformat(),
    )

    def format_hand(cards):
        return " ".join([f"{r}{s}" for r, s in cards])

    embed = discord.Embed(
        title="🃏 Blackjack",
        description=(
            f"**Твоя рука:** {format_hand(player)} (*{hand_value(player)}*)\n"
            f"**Рука дилера:** {format_hand(dealer)} (*{hand_value(dealer)}*)\n\n"
            f"{result_text}\n\n"
            f"Твой баланс: **{coins}💰**"
        ),
        color=0x1ABC9C,
    )
    await interaction.response.send_message(embed=embed)


# ===================== ТОПЫ ================================

async def _send_top_coins(interaction: discord.Interaction):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message(
            "Пока ещё никто не заработал ни одной монеты.",
            ephemeral=True,
        )
        return

    text = ""
    for i, row in enumerate(rows, 1):
        uid = row["user_id"]
        coins = row["coins"]
        u = await bot.fetch_user(uid)
        text += f"**{i}. {u} — {coins}💰**\n"

    embed = discord.Embed(
        title="🏆 Топ по Coins", description=text, color=0xFFFF00
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="top-coins", description="Топ игроков по обычным монетам.")
async def top_coins(interaction: discord.Interaction):
    await _send_top_coins(interaction)


@bot.tree.command(name="top-cash", description="Топ игроков по наличным (алиас топа по Coins).")
async def top_cash(interaction: discord.Interaction):
    await _send_top_coins(interaction)


@bot.tree.command(name="top-radcoin", description="Топ игроков по Radcoin.")
async def top_radcoin(interaction: discord.Interaction):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id, radcoin FROM users ORDER BY radcoin DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message(
            "Ещё никто не получил ни одного Radcoin.",
            ephemeral=True,
        )
        return

    text = ""
    for i, row in enumerate(rows, 1):
        uid = row["user_id"]
        rc = row["radcoin"]
        u = await bot.fetch_user(uid)
        text += f"**{i}. {u} — {rc}🪙**\n"

    embed = discord.Embed(
        title="🏆 Топ по Radcoin", description=text, color=0x00FFFF
    )
    await interaction.response.send_message(embed=embed)


# ===================== /set-economy =========================

ECON_CHOICES = [
    ("work_cd_hours", "work_cd_hours — КД /work (часы)"),
    ("work_min", "work_min — мин. зарплата /work"),
    ("work_max", "work_max — макс. зарплата /work"),

    ("crime_cd_hours", "crime_cd_hours — КД /crime (часы)"),
    ("crime_gain_min", "crime_gain_min — мин. прибыль /crime"),
    ("crime_gain_max", "crime_gain_max — макс. прибыль /crime"),
    ("crime_loss_min", "crime_loss_min — мин. штраф /crime"),
    ("crime_loss_max", "crime_loss_max — макс. штраф /crime"),
    ("crime_success", "crime_success — шанс успеха /crime (0–1)"),

    ("slut_cd_hours", "slut_cd_hours — КД /slut (часы)"),
    ("slut_gain_min", "slut_gain_min — мин. прибыль /slut"),
    ("slut_gain_max", "slut_gain_max — макс. прибыль /slut"),
    ("slut_loss_min", "slut_loss_min — мин. штраф /slut"),
    ("slut_loss_max", "slut_loss_max — макс. штраф /slut"),
    ("slut_success", "slut_success — шанс успеха /slut (0–1)"),

    ("rob_cd_hours", "rob_cd_hours — КД /rob (часы)"),
    ("rob_success", "rob_success — шанс успеха /rob (0–1)"),
    ("rob_gain_min_percent", "rob_gain_min_percent — мин. % кражи"),
    ("rob_gain_max_percent", "rob_gain_max_percent — макс. % кражи"),
    ("rob_penalty_min", "rob_penalty_min — мин. штраф /rob"),
    ("rob_penalty_max", "rob_penalty_max — макс. штраф /rob"),

    ("income_cd_hours", "income_cd_hours — КД /collect-income (часы)"),

    ("roulette_cd_minutes", "roulette_cd_minutes — КД /roulette (минуты)"),
    ("roulette_min_bet", "roulette_min_bet — мин. ставка /roulette"),
    ("roulette_max_bet", "roulette_max_bet — макс. ставка /roulette"),
    ("roulette_payout_red_black", "roulette_payout_red_black — множитель красное/чёрное"),
    ("roulette_payout_green", "roulette_payout_green — множитель зелёное"),

    ("blackjack_cd_minutes", "blackjack_cd_minutes — КД /blackjack (минуты)"),
    ("blackjack_min_bet", "blackjack_min_bet — мин. ставка /blackjack"),
    ("blackjack_max_bet", "blackjack_max_bet — макс. ставка /blackjack"),
    ("blackjack_blackjack_payout", "blackjack_blackjack_payout — множитель за Blackjack"),
    ("blackjack_dealer_hits_soft17", "blackjack_dealer_hits_soft17 — дилер добирает на мягких 17 (0/1)"),

    ("radcoin_bonus_chance", "radcoin_bonus_chance — шанс бонусного Radcoin (0–1)"),
]


@bot.tree.command(
    name="set-economy",
    description="Настроить экономику (только админы).",
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    parameter="Какой параметр меняем",
    value="Новое значение (число, можно с точкой)",
)
async def set_economy(
    interaction: discord.Interaction,
    parameter: app_commands.Choice[str],
    value: float,
):
    key = parameter.value
    set_setting(key, value)
    embed = discord.Embed(
        title="⚙ Настройки экономики обновлены",
        description=f"**{key}** теперь = **{value}**",
        color=0x3498DB,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@set_economy.autocomplete("parameter")
async def econ_autocomplete(
    interaction: discord.Interaction, current: str
):
    current_lower = current.lower()
    choices: List[app_commands.Choice[str]] = []
    for key, desc in ECON_CHOICES:
        if current_lower in key.lower() or current_lower in desc.lower():
            choices.append(app_commands.Choice(name=desc, value=key))
    return choices[:25]


# ===================== ФОНОВЫЙ ПРОЦЕСС =====================

@tasks.loop(minutes=5)
async def background_worker():
    if not bot.is_ready():
        return

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[BACKGROUND] Бот жив, время (UTC): {now}")
    # Здесь можно потом добавить авто-ивенты/новости/экономику


# ===================== ON_READY =============================

@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
        print(f"Залогинен как {bot.user} и slash-команды синхронизированы.")
    except Exception as e:
        print("Ошибка sync:", e)

    if not background_worker.is_running():
        background_worker.start()
        print("[BACKGROUND] Фоновый процесс запущен")


# ===================== ЗАПУСК ===============================

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("Переменная окружения TOKEN не задана (TOKEN)!")
    bot.run(TOKEN)
