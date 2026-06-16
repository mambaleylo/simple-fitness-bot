import os

# Токен бота (получить у @BotFather)
BOT_TOKEN = os.getenv("BOT_TOKEN", "8660610624:AAFZhDDSpcTHvjr8scRzGEJE4nOx7a8ksTs")

# Расписание уведомлений о новых тренировках
# 0=ПН, 1=ВТ, 2=СР, 3=ЧТ, 4=ПТ, 5=СБ, 6=ВС
SCHEDULE_DAYS = [0, 2, 4]  # ПН, СР, ПТ
SCHEDULE_TIME = "10:00"    # в 10:00 по Москве

# Цена подписки
SUBSCRIPTION_PRICE = 500  # рублей

# Telegram ID администраторов
ADMIN_IDS = [181970023]  # замени на свой ID (узнать: @userinfobot)
