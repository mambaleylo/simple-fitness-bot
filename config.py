import os

# Токен бота (получить у @BotFather)
BOT_TOKEN = os.getenv("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_ОТ_BOTFATHER")

# Telegram ID администраторов (узнать свой: @userinfobot)
ADMIN_IDS = [181970023]

# ──────────────────────────────────────────
# ОПЛАТА через bePaid (Telegram Payments)
# ──────────────────────────────────────────
# Как получить BEPAID_PROVIDER_TOKEN:
#   1. Зарегистрируйся на bepaid.by → получи аккаунт магазина
#   2. Напиши @BotFather → /mybots → твой бот → Payments → bePaid
#   3. BotFather выдаст provider_token — вставь его ниже
BEPAID_PROVIDER_TOKEN = os.getenv("BEPAID_PROVIDER_TOKEN", "ВСТАВЬ_PROVIDER_TOKEN")

# Цена подписки в BYN (белорусских рублях)
SUBSCRIPTION_PRICE = 10       # 10 BYN за месяц
SUBSCRIPTION_DAYS  = 30       # на сколько дней

# Расписание уведомлений о новых тренировках
# 0=ПН, 1=ВТ, 2=СР, 3=ЧТ, 4=ПТ, 5=СБ, 6=ВС
SCHEDULE_DAYS = [0, 2, 4]    # ПН, СР, ПТ
SCHEDULE_TIME = "10:00"       # в 10:00 по Москве
