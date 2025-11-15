import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import datetime
import random
import os

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

# ===================== БАЗА =================================

def db():
    return sqlite3.connect("economy.db")

def setup_db():
    conn = db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
                 user_id INTEGER PRIMARY KEY,
                 coins INTEGER DEFAULT 0,
                 radcoin INTEGER DEFAULT 0,
                 last_work TEXT,
                 last_crime TEXT,
                 last_slut TEXT,
                 last_income TEXT
                )""")

    conn.commit()
    conn.close()

setup_db()

# ===================== УТИЛИТЫ ===============================

def get_user(user_id):
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


def update_field(user_id, field, value):
    conn = db()
    c = conn.cursor()
    c.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()


def format_time(seconds):
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h}ч {m}м {s}с"


def progress_bar(passed, total):
    bar_len = 20
    percent = passed / total
    filled = int(bar_len * percent)
    empty = bar_len - filled
    return "▰" * filled + "▱" * empty, int(percent * 100)

# ===================== ОГРАНИЧЕНИЕ КОМАНД ===================

async def cooldown_check(interaction, last_time_str, cooldown_hours, title):
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
                    f"Команда будет доступна через:\n"
                    f"**{format_time(remaining_seconds)}**\n\n"
                    f"Прогресс: `{bar}` **{percent}%**"
                ),
                color=0xffcc00
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
    return True

# ===================== ОСНОВНЫЕ КОМАНДЫ ======================

@bot.tree.command(name="work", description="Пойти на работу")
async def work(interaction: discord.Interaction):
    user = get_user(interaction.user.id)

    if not await cooldown_check(interaction, user[3], 1, "Работа"):
        return

    salary = random.randint(50, 120)
    bonus = ""

    # шанс премии
    if random.random() <= 0.05:
        rad = user[2] + 1
        update_field(interaction.user.id, "radcoin", rad)
        bonus = "\n🎉 **Вам выдали премию: +1 Radcoin!**"

    coins = user[1] + salary
    update_field(interaction.user.id, "coins", coins)
    update_field(interaction.user.id, "last_work", datetime.datetime.utcnow().isoformat())

    embed = discord.Embed(
        title="💼 Работа выполнена!",
        description=f"Вы заработали **{salary}💰**.{bonus}",
        color=0x00ff99
    )
    await interaction.response.send_message(embed=embed)

# ===================== CRIME ======================

@bot.tree.command(name="crime", description="Совершить преступление")
async def crime(interaction: discord.Interaction):
    user = get_user(interaction.user.id)

    if not await cooldown_check(interaction, user[4], 1, "Crime"):
        return

    amount = random.randint(30, 150)
    success = random.choice([True, False, True])  # 66% успех

    bonus = ""
    rad = user[2]

    if random.random() <= 0.05:
        rad += 1
        update_field(interaction.user.id, "radcoin", rad)
        bonus = "\n🎉 **Вы нашли Radcoin: +1!**"

    if success:
        coins = user[1] + amount
        update_field(interaction.user.id, "coins", coins)
        text = f"Вы успешно ограбили кого-то: **+{amount}💰**!{bonus}"
    else:
        coins = max(0, user[1] - amount)
        update_field(interaction.user.id, "coins", coins)
        text = f"Вас поймали! Потеряно **-{amount}💰**!"

    update_field(interaction.user.id, "last_crime", datetime.datetime.utcnow().isoformat())

    embed = discord.Embed(title="🕵 Crime", description=text, color=0xaa0000)
    await interaction.response.send_message(embed=embed)

# ===================== SLUT ======================

@bot.tree.command(name="slut", description="Заработать продажным путём")
async def slut(interaction: discord.Interaction):
    user = get_user(interaction.user.id)

    if not await cooldown_check(interaction, user[5], 1, "Slut"):
        return

    earn = random.randint(20, 80)
    bonus = ""

    if random.random() <= 0.05:
        update_field(interaction.user.id, "radcoin", user[2] + 1)
        bonus = "\n💋 **Премия клиента: +1 Radcoin!**"

    coins = user[1] + earn
    update_field(interaction.user.id, "coins", coins)
    update_field(interaction.user.id, "last_slut", datetime.datetime.utcnow().isoformat())

    embed = discord.Embed(
        title="💋 Работка выполнена",
        description=f"Заработано **{earn}💰**.{bonus}",
        color=0xff66cc
    )
    await interaction.response.send_message(embed=embed)

# ===================== COLLECT-INCOME ======================

@bot.tree.command(name="collect-income", description="Собрать ежедневный доход")
async def collect_income(interaction: discord.Interaction):

    user = get_user(interaction.user.id)

    # проверка КД — 24 часа
    if not await cooldown_check(interaction, user[6], 24, "Доход"):
        return

    income = 0
    for role in interaction.user.roles:
        if role.name.startswith("income_"):  # пример роли: income_500
            income += int(role.name.split("_")[1])

    if income == 0:
        income = 100  # базовый доход

    coins = user[1] + income
    update_field(interaction.user.id, "coins", coins)
    update_field(interaction.user.id, "last_income", datetime.datetime.utcnow().isoformat())

    embed = discord.Embed(
        title="💰 Доход собран!",
        description=f"Вы получили **{income}💰**.",
        color=0x33cc33
    )
    await interaction.response.send_message(embed=embed)

# ===================== ТОП ======================

@bot.tree.command(name="top-coins", description="Топ игроков по монетам")
async def top_coins(interaction: discord.Interaction):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id, coins FROM users ORDER BY coins DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()

    text = ""
    for i, (uid, coins) in enumerate(rows, 1):
        user = await bot.fetch_user(uid)
        text += f"**{i}. {user} — {coins}💰**\n"

    embed = discord.Embed(title="🏆 Топ по Coins", description=text, color=0xffff00)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="top-radcoin", description="Топ по Radcoin")
async def top_radcoin(interaction: discord.Interaction):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT user_id, radcoin FROM users ORDER BY radcoin DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()

    text = ""
    for i, (uid, r) in enumerate(rows, 1):
        user = await bot.fetch_user(uid)
        text += f"**{i}. {user} — {r}🪙**\n"

    embed = discord.Embed(title="🏆 Топ Radcoin", description=text, color=0x00ffff)
    await interaction.response.send_message(embed=embed)


# ===================== СИНХРОНИЗАЦИЯ ======================

@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
        print("Slash-команды синхронизированы!")
    except Exception as e:
        print(e)

bot.run(TOKEN)
