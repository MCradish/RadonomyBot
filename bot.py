import discord
from discord import app_commands
from discord.ext import commands, tasks
import sqlite3
import datetime
import random
import os

# ===================== НАСТРОЙКА ТОКЕНА =====================

TOKEN = os.getenv("TOKEN")  # на Render должен быть задан env TOKEN

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

# ===================== БАЗА ДАННЫХ =========================

DB_NAME = "economy.db"

def db():
    return sqlite3.connect(DB_NAME)

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
            last_rob TEXT
        )
    """)

    # Таблица настроек экономики
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()

setup_db()

# ===================== НАСТРОЙКИ ЭКОНОМИКИ ==================

DEFAULT_SETTINGS = {
    # work
    "work_min": 40,
    "work_max": 90,

    # crime
    "crime_gain_min": 120,
    "crime_gain_max": 260,
    "crime_loss_min": 80,
    "crime_loss_max": 180,
    "crime_success": 0.6,       # 60% успеха

    # slut
    "slut_gain_min": 100,
    "slut_gain_max": 220,
    "slut_loss_min": 60,
    "slut_loss_max": 160,
    "slut_success": 0.7,        # 70% успеха

    # rob
    "rob_success": 0.25,        # 25% успеха
    "rob_gain_min_percent": 5,  # % от монет цели
    "rob_gain_max_percent": 20,
    "rob_penalty": 100          # штраф при провале
}

def get_setting(key: str) -> float:
    conn = db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    if row is None:
        default = DEFAULT_SETTINGS.get(key, 0)
        c.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, str(default)))
        conn.commit()
        conn.close()
        return float(default)
    conn.close()
    return float(row[0])

def set_setting(key: str, value: float):
    conn = db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
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
    "Ты просто честно отработал свой день. Спокойно и без лишнего шума."
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
    "Ты сыграл грязно — но результат того стоил."
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
    "Ты поверил сомнительному плану и был наказан монетами."
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
    "Ты провёл смену без простоев и всё время был при деле."
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
    "Ты переоценил свои силы и остался в убытке."
]

ROB_SUCCESS_EVENTS = [
    "Ты незаметно стянул кошелёк у цели.",
    "Ты подкараулил жертву в переулке и забрал часть налички.",
    "Ты ловко выдернул кошелёк, пока жертва отвлеклась.",
    "Ты провернул карманную кражу в толпе.",
    "Ты обчистил задний карман, и жертва ничего не почувствовала."
]

ROB_FAIL_EVENTS = [
    "Цель заметила попытку ограбления и вызвала охрану.",
    "Тебя поймали за руку и заставили заплатить штраф.",
    "Жертва оказалась сильнее, чем ты думал — пришлось расплачиваться.",
    "Рядом был патруль, и тебе выписали крупный штраф.",
    "Тебя скрутили очевидцы и ты еле отделался штрафом."
]

# ===================== УТИЛИТЫ ==============================

def get_user(user_id: int):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()

    if not user:
        c.execute("INSERT INTO users (user_id, coins, radcoin) VALUES (?, 0, 0)", (user_id,))
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

# ===================== КУЛДАУН ==============================

async def cooldown_check(interaction: discord.Interaction, last_time_str: str | None, cooldown_hours: int, title: str):
    if last_time_str:
        last_time = datetime.datetime.fromisoformat(last_time_str)
        now = datetime.datetime.utcnow()
        delta = now - last_time
        delta_hours = delta.total_seconds() / 3600

        if delta_hours < cooldown_hours:
            total_seconds = cooldown_hours * 3600
            passed_seconds = int(delta.total_seconds())
            remaining_seconds = total_seconds - passed_seconds

            bar, percent = progress_bar(passed_seconds, total_seconds)

            embed = discord.Embed(
                title=f"⏳ {title} уже использована!",
                description=(
                    "Команда будет доступна через:\n"
                    f"**{format_time(remaining_seconds)}**\n\n"
                    f"Прогресс: `{bar}` **{percent}%**"
                ),
                color=0xffcc00
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
    return True

# ===================== /work ================================

@bot.tree.command(
    name="work",
    description="Стабильная работа: всегда плюс, но не очень много."
)
async def work(interaction: discord.Interaction):
    user = get_user(interaction.user.id)

    if not await cooldown_check(interaction, user[3], 1, "Работа"):
        return

    work_min = int(get_setting("work_min"))
    work_max = int(get_setting("work_max"))

    amount = random.randint(work_min, work_max)
    event_text = random.choice(WORK_EVENTS)

    coins = user[1] + amount
    update_field(interaction.user.id, "coins", coins)
    update_field(interaction.user.id, "last_work", datetime.datetime.utcnow().isoformat())

    bonus = ""
    if random.random() <= 0.05:
        update_field(interaction.user.id, "radcoin", user[2] + 1)
        bonus = "\n🎉 Сегодня на работе тебе выдали **премию: +1 Radcoin!**"

    embed = discord.Embed(
        title="💼 Рабочая смена",
        description=f"{event_text}\n\nТы заработал **{amount}💰**.{bonus}",
        color=0x00ff99
    )
    await interaction.response.send_message(embed=embed)

# ===================== /crime ===============================

@bot.tree.command(
    name="crime",
    description="Рискованное дело: можно поднять много, а можно улететь в минус."
)
async def crime(interaction: discord.Interaction):
    user = get_user(interaction.user.id)

    if not await cooldown_check(interaction, user[4], 1, "Crime"):
        return

    success_chance = get_setting("crime_success")
    success = random.random() < success_chance

    if success:
        gain_min = int(get_setting("crime_gain_min"))
        gain_max = int(get_setting("crime_gain_max"))
        amount = random.randint(gain_min, gain_max)
        event_text = random.choice(CRIME_SUCCESS_EVENTS)
        coins = user[1] + amount
        update_field(interaction.user.id, "coins", coins)

        bonus = ""
        if random.random() <= 0.05:
            update_field(interaction.user.id, "radcoin", user[2] + 1)
            bonus = "\n🪙 В добыче затесался **1 Radcoin!**"

        color = 0x22cc22
        desc = f"{event_text}\n\nДобыча: **+{amount}💰**.{bonus}"
    else:
        loss_min = int(get_setting("crime_loss_min"))
        loss_max = int(get_setting("crime_loss_max"))
        amount = random.randint(loss_min, loss_max)
        event_text = random.choice(CRIME_FAIL_EVENTS)
        coins = max(0, user[1] - amount)
        update_field(interaction.user.id, "coins", coins)

        color = 0xcc2222
        desc = f"{event_text}\n\nШтраф: **-{amount}💰**."

    update_field(interaction.user.id, "last_crime", datetime.datetime.utcnow().isoformat())

    embed = discord.Embed(
        title="🕵 Преступный промысел",
        description=desc,
        color=color
    )
    await interaction.response.send_message(embed=embed)

# ===================== /slut ================================

@bot.tree.command(
    name="slut",
    description="Грязный, но прибыльный заработок. Много денег, но бывают провалы."
)
async def slut(interaction: discord.Interaction):
    user = get_user(interaction.user.id)

    if not await cooldown_check(interaction, user[5], 1, "Slut"):
        return

    success_chance = get_setting("slut_success")
    success = random.random() < success_chance

    if success:
        gain_min = int(get_setting("slut_gain_min"))
        gain_max = int(get_setting("slut_gain_max"))
        amount = random.randint(gain_min, gain_max)
        event_text = random.choice(SLUT_SUCCESS_EVENTS)
        coins = user[1] + amount
        update_field(interaction.user.id, "coins", coins)

        bonus = ""
        if random.random() <= 0.05:
            update_field(interaction.user.id, "radcoin", user[2] + 1)
            bonus = "\n💋 Клиент был особенно щедрым: **+1 Radcoin!**"

        color = 0xff66cc
        desc = f"{event_text}\n\nЗаработано: **+{amount}💰**.{bonus}"
    else:
        loss_min = int(get_setting("slut_loss_min"))
        loss_max = int(get_setting("slut_loss_max"))
        amount = random.randint(loss_min, loss_max)
        event_text = random.choice(SLUT_FAIL_EVENTS)
        coins = max(0, user[1] - amount)
        update_field(interaction.user.id, "coins", coins)

        color = 0xcc1188
        desc = f"{event_text}\n\nУбыток: **-{amount}💰**."

    update_field(interaction.user.id, "last_slut", datetime.datetime.utcnow().isoformat())

    embed = discord.Embed(
        title="💋 Ночная подработка",
        description=desc,
        color=color
    )
    await interaction.response.send_message(embed=embed)

# ===================== /rob ================================

@bot.tree.command(
    name="rob",
    description="Попробовать ограбить другого игрока. Маленький шанс успеха, большой штраф."
)
@app_commands.describe(target="Кого пытаемся ограбить")
async def rob(interaction: discord.Interaction, target: discord.Member):
    if target.id == interaction.user.id:
        await interaction.response.send_message("Нельзя ограбить самого себя 🙃", ephemeral=True)
        return
    if target.bot:
        await interaction.response.send_message("Ботов ограбить не получится.", ephemeral=True)
        return

    robber = get_user(interaction.user.id)
    victim = get_user(target.id)

    last_rob = robber[7]  # last_rob
    if not await cooldown_check(interaction, last_rob, 1, "Rob"):
        return

    success_chance = get_setting("rob_success")
    gain_min_percent = get_setting("rob_gain_min_percent")
    gain_max_percent = get_setting("rob_gain_max_percent")
    penalty = int(get_setting("rob_penalty"))

    victim_coins = victim[1]
    success = random.random() < success_chance

    if success and victim_coins > 0:
        percent = random.uniform(gain_min_percent, gain_max_percent) / 100.0
        stolen = int(victim_coins * percent)
        if stolen < 1:
            stolen = 1

        new_robber_coins = robber[1] + stolen
        new_victim_coins = max(0, victim_coins - stolen)

        update_field(interaction.user.id, "coins", new_robber_coins)
        update_field(target.id, "coins", new_victim_coins)

        event_text = random.choice(ROB_SUCCESS_EVENTS)

        color = 0x00ff00
        desc = (
            f"{event_text}\n\n"
            f"Ты украл у {target.mention} **{stolen}💰** "
            f"(*{percent*100:.1f}%* от его монет на руках)."
        )
    else:
        new_robber_coins = max(0, robber[1] - penalty)
        update_field(interaction.user.id, "coins", new_robber_coins)

        event_text = random.choice(ROB_FAIL_EVENTS)
        color = 0xff0000
        desc = f"{event_text}\n\nШтраф: **-{penalty}💰**."

    update_field(interaction.user.id, "last_rob", datetime.datetime.utcnow().isoformat())

    embed = discord.Embed(
        title="🔪 Попытка ограбления",
        description=desc,
        color=color
    )
    await interaction.response.send_message(embed=embed)

# ===================== /collect-income ======================

@bot.tree.command(
    name="collect-income",
    description="Собрать ежедневный пассивный доход."
)
async def collect_income(interaction: discord.Interaction):
    user = get_user(interaction.user.id)

    if not await cooldown_check(interaction, user[6], 24, "Доход"):
        return

    income = 100  # базовый доход

    # Роли вида: income_500, income_200 и т.п.
    for role in interaction.user.roles:
        if role.name.startswith("income_"):
            try:
                income += int(role.name.split("_")[1])
            except ValueError:
                pass

    coins = user[1] + income
    update_field(interaction.user.id, "coins", coins)
    update_field(interaction.user.id, "last_income", datetime.datetime.utcnow().isoformat())

    embed = discord.Embed(
        title="💰 Пассивный доход",
        description=f"Ты собрал ежедневный доход: **+{income}💰**.",
        color=0x33cc33
    )
    await interaction.response.send_message(embed=embed)

# ===================== ТОПЫ ================================

@bot.tree.command(name="top-coins", description="Топ игроков по обычным монетам.")
async def top_coins(interaction: discord.Interaction):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()

    if not rows:
        await interaction.response.send_message(
            "Пока ещё никто не заработал ни одной монеты.",
            ephemeral=True
        )
        return

    text = ""
    for i, (uid, coins) in enumerate(rows, 1):
        u = await bot.fetch_user(uid)
        text += f"**{i}. {u} — {coins}💰**\n"

    embed = discord.Embed(title="🏆 Топ по Coins", description=text, color=0xffff00)
    await interaction.response.send_message(embed=embed)

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
            ephemeral=True
        )
        return

    text = ""
    for i, (uid, r) in enumerate(rows, 1):
        u = await bot.fetch_user(uid)
        text += f"**{i}. {u} — {r}🪙**\n"

    embed = discord.Embed(title="🏆 Топ по Radcoin", description=text, color=0x00ffff)
    await interaction.response.send_message(embed=embed)

# ===================== /set-economy =========================

ECON_CHOICES = [
    ("work_min", "work_min — мин. зарплата /work"),
    ("work_max", "work_max — макс. зарплата /work"),
    ("crime_gain_min", "crime_gain_min — мин. прибыль /crime"),
    ("crime_gain_max", "crime_gain_max — макс. прибыль /crime"),
    ("crime_loss_min", "crime_loss_min — мин. штраф /crime"),
    ("crime_loss_max", "crime_loss_max — макс. штраф /crime"),
    ("crime_success", "crime_success — шанс успеха /crime (0–1)"),
    ("slut_gain_min", "slut_gain_min — мин. прибыль /slut"),
    ("slut_gain_max", "slut_gain_max — макс. прибыль /slut"),
    ("slut_loss_min", "slut_loss_min — мин. штраф /slut"),
    ("slut_loss_max", "slut_loss_max — макс. штраф /slut"),
    ("slut_success", "slut_success — шанс успеха /slut (0–1)"),
    ("rob_success", "rob_success — шанс успеха /rob (0–1)"),
    ("rob_gain_min_percent", "rob_gain_min_percent — мин. % кражи"),
    ("rob_gain_max_percent", "rob_gain_max_percent — макс. % кражи"),
    ("rob_penalty", "rob_penalty — штраф за провал /rob"),
]

@bot.tree.command(
    name="set-economy",
    description="Настроить экономику (только админы)."
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    parameter="Какой параметр меняем",
    value="Новое значение (число, можно с точкой)"
)
async def set_economy(
    interaction: discord.Interaction,
    parameter: app_commands.Choice[str],
    value: float
):
    key = parameter.value
    set_setting(key, value)
    embed = discord.Embed(
        title="⚙ Настройки экономики обновлены",
        description=f"**{key}** теперь = **{value}**",
        color=0x3498db
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@set_economy.autocomplete("parameter")
async def econ_autocomplete(
    interaction: discord.Interaction,
    current: str
):
    current_lower = current.lower()
    choices: list[app_commands.Choice[str]] = []
    for key, desc in ECON_CHOICES:
        if current_lower in key.lower() or current_lower in desc.lower():
            choices.append(app_commands.Choice(name=desc, value=key))
    return choices[:25]

# ===================== ФОНОВЫЙ ПРОЦЕСС =====================

@tasks.loop(minutes=5)
async def background_worker():
    """
    Простой фоновый процесс.
    Пока что он просто пишет в консоль, что бот жив.
    При желании сюда можно добавить:
    - авто-события экономики
    - пассивное изменение курса
    - глобальные ивенты
    """
    if not bot.is_ready():
        return

    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[BACKGROUND] Бот жив, время (UTC): {now}")

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
        raise RuntimeError("Переменная окружения TOKEN не задана!")
    bot.run(TOKEN)
