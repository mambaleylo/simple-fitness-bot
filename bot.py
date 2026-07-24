import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import (
    BOT_TOKEN, SCHEDULE_DAYS, SCHEDULE_TIME, ADMIN_IDS,
    BEPAID_PROVIDER_TOKEN, SUBSCRIPTION_PRICE, SUBSCRIPTION_DAYS,
    SUBSCRIPTION_WELCOME_TEXT, WELCOME_PHOTO_FILE_ID
)
from database import (
    add_user, is_subscribed, get_subscription_days_left,
    activate_subscription, get_permanent_workouts, get_active_weekly_workouts,
    has_completed_workout, mark_workout_done, cleanup_old_workouts,
    add_weekly_workouts, add_permanent_workout, get_all_users, get_db,
    get_nutrition_lectures, get_nutrition_lecture, add_nutrition_lecture,
    delete_nutrition_lecture, get_next_unsent_workout, mark_workout_sent,
    get_permanent_workout, update_permanent_workout, delete_permanent_workout,
    get_weekly_workout, update_weekly_workout, delete_weekly_workout,
    update_nutrition_lecture,
    get_extra_materials, get_extra_material, add_extra_material,
    update_extra_material, delete_extra_material,
    save_body_params, get_body_params, save_progress_photo, get_progress_photo,
    get_body_params_history, get_progress_photos, get_user_by_username
)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

async def send_welcome(uid: int, reply_markup=None):
    """Отправляет приветственное сообщение с фото если настроено."""
    if WELCOME_PHOTO_FILE_ID:
        await bot.send_photo(
            uid,
            WELCOME_PHOTO_FILE_ID,
            caption=SUBSCRIPTION_WELCOME_TEXT,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    else:
        await bot.send_message(
            uid,
            SUBSCRIPTION_WELCOME_TEXT,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )



# ========== FSM STATES ==========

class AddPermanentState(StatesGroup):
    title = State()
    description = State()
    url = State()

class AddWeeklyState(StatesGroup):
    title = State()
    description = State()
    url = State()

class BroadcastState(StatesGroup):
    text = State()

class ActivateState(StatesGroup):
    user_id = State()
    days = State()

class AddLectureState(StatesGroup):
    title = State()
    description = State()
    url = State()
    media = State()

class AddExtraState(StatesGroup):
    title = State()
    description = State()
    url = State()
    media = State()

class BodyParamsState(StatesGroup):
    weight = State()
    chest = State()
    waist = State()
    hips = State()
    arm = State()
    thigh = State()
    photo = State()

class EditFieldState(StatesGroup):
    waiting_value = State()


# ========== KEYBOARDS ==========

def main_menu(user_id=None):
    buttons = [
        [InlineKeyboardButton(text="🏋️ Закреплённые тренировки", callback_data="permanent")],
        [InlineKeyboardButton(text="🍎 Информация по питанию", callback_data="lectures")],
        [InlineKeyboardButton(text="📋 Дополнительная информация", callback_data="extra")],
    ]
    if user_id and is_subscribed(user_id):
        days = get_subscription_days_left(user_id)
        buttons.append([InlineKeyboardButton(text="⭐ Тренировки месяца", callback_data="weekly")])
        buttons.append([InlineKeyboardButton(text=f"⭐ Подписка активна ({days} дн.)", callback_data="sub_info")])
    else:
        buttons.append([InlineKeyboardButton(text="💎 Купить подписку", callback_data="buy_sub")])
    buttons.append([InlineKeyboardButton(text="📊 Мой прогресс", callback_data="progress")])
    buttons.append([InlineKeyboardButton(text="❓ Помощь", callback_data="help")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏋️ Добавить закреплённую", callback_data="adm:add_permanent")],
        [InlineKeyboardButton(text="📅 Добавить тренировку месяца", callback_data="adm:add_weekly")],
        [InlineKeyboardButton(text="🍎 Добавить информацию по питанию", callback_data="adm:add_lecture")],
        [InlineKeyboardButton(text="✏️ Редактировать закреплённые", callback_data="adm:edit_permanent_list")],
        [InlineKeyboardButton(text="✏️ Редактировать тренировки месяца", callback_data="adm:edit_weekly_list")],
        [InlineKeyboardButton(text="✏️ Редактировать информацию по питанию", callback_data="adm:edit_lecture_list")],
        [InlineKeyboardButton(text="📋 Добавить доп. информацию", callback_data="adm:add_extra")],
        [InlineKeyboardButton(text="✏️ Редактировать доп. информацию", callback_data="adm:edit_extra_list")],
        [InlineKeyboardButton(text="✅ Активировать подписку", callback_data="adm:activate")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="adm:users")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:broadcast")],
        [InlineKeyboardButton(text="🗑️ Очистить старые тренировки", callback_data="adm:cleanup")],
        [InlineKeyboardButton(text="❓ Помощь по панели", callback_data="adm:help")],
    ])


def workout_list_keyboard(workouts, workout_type, user_id):
    buttons = []
    for w in workouts:
        done = has_completed_workout(user_id, w["id"], workout_type)
        status = "✅ " if done else "◻️ "
        buttons.append([InlineKeyboardButton(
            text=f"{status}{w['title']}",
            callback_data=f"wk:{workout_type}:{w['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_keyboard(target="back"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data=target)]
    ])


def cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")]
    ])


# ========== HELPERS ==========

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def send_admin_panel(target, edit=False):
    text = (
        "🔧 <b>Панель администратора</b>\n\n"
        "🏋️ <b>Добавить закреплённую</b> — тренировки которые всегда видны всем (разминка, заминка и др.)\n"
        "📅 <b>Добавить тренировку месяца</b> — встаёт в очередь и автоматически отправляется подписчикам в вс/вт/чт в 20:00\n"
        "🍎 <b>Добавить лекцию</b> — материалы по питанию, доступны всем без подписки\n"
        "✏️ <b>Редактировать</b> — изменить или удалить уже добавленный контент\n"
        "✅ <b>Активировать подписку</b> — открыть пользователю доступ к тренировкам месяца\n"
        "👥 <b>Пользователи</b> — список всех, кто запускал бота\n"
        "📢 <b>Рассылка</b> — отправить сообщение всем пользователям\n"
        "🗑️ <b>Очистить</b> — удалить отправленные тренировки старше 30 дней"
    )
    if edit:
        await target.message.edit_text(text, reply_markup=admin_menu(), parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=admin_menu(), parse_mode="HTML")


# ========== COMMANDS ==========

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    uid = message.from_user.id
    add_user(uid, message.from_user.username)

    if is_subscribed(uid):
        # Премиум пользователь — приветствие с фото
        await send_welcome(uid, reply_markup=main_menu(uid))
    else:
        # Обычный пользователь
        await message.answer(
            f"👋 Привет, {message.from_user.first_name}!\n\n"
            "Здесь есть закреплённые тренировки и информация по питанию — "
            "они доступны всем бесплатно.\n\n"
            "Для доступа к тренировкам месяца нужна подписка 💎\n\n"
            "⬇️ Выбери действие:",
            reply_markup=main_menu(uid)
        )


@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await send_admin_panel(message)


@dp.message(Command("cancel"))
async def cmd_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.",
                         reply_markup=admin_menu() if is_admin(message.from_user.id) else None)


@dp.message(Command("getfileid"))
async def cmd_getfileid(message: types.Message):
    """Команда для получения file_id фото — только для админов."""
    if not is_admin(message.from_user.id):
        return
    await message.answer(
        "📎 Пришли фото следующим сообщением — я верну его file_id.\n"
        "Вставь его в config.py как WELCOME_PHOTO_FILE_ID."
    )


@dp.message(F.photo & F.text.is_(None))
async def handle_photo_for_fileid(message: types.Message, state: FSMContext):
    """Если админ прислал фото без состояния FSM — возвращаем file_id."""
    if not is_admin(message.from_user.id):
        return
    current = await state.get_state()
    if current is not None:
        return  # в FSM — не перехватываем
    file_id = message.photo[-1].file_id
    await message.answer(
        f"✅ <b>file_id фото:</b>\n<code>{file_id}</code>\n\n"
        "Вставь это значение в переменную <code>WELCOME_PHOTO_FILE_ID</code> в config.py",
        parse_mode="HTML"
    )


# ========== USER CALLBACKS ==========

@dp.callback_query(F.data == "back")
async def cb_back(callback: types.CallbackQuery):
    text = "📋 Главное меню:"
    kb = main_menu(callback.from_user.id)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb)
    await callback.answer()


@dp.callback_query(F.data == "permanent")
async def cb_permanent(callback: types.CallbackQuery):
    uid = callback.from_user.id
    workouts = get_permanent_workouts()
    if not workouts:
        await callback.message.edit_text("📭 Закреплённых тренировок пока нет.", reply_markup=back_keyboard())
        await callback.answer()
        return
    text = "🏋️ <b>Закреплённые тренировки</b> (доступны всегда):\n\n"
    text += "\n".join(f"• {w['title']}" for w in workouts)
    await callback.message.edit_text(text, reply_markup=workout_list_keyboard(workouts, "permanent", uid), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "weekly")
async def cb_weekly(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if not is_subscribed(uid):
        await callback.answer("❌ Подписка не активна! Купите доступ.", show_alert=True)
        return
    workouts = get_active_weekly_workouts()
    if not workouts:
        await callback.message.edit_text(
            "📭 Тренировки этого месяца ещё не добавлены.\n\nОни появляются по расписанию: ПН, СР, ПТ в 10:00.",
            reply_markup=back_keyboard()
        )
        await callback.answer()
        return
    text = "📅 <b>Тренировки этого месяца:</b>\n\n"
    DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    MONTHS_RU = ["", "янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]

    def fmt_date(w):
        try:
            from datetime import datetime as dt
            d = dt.strptime(w["sent_at"][:10], "%Y-%m-%d")
            return f"{DAYS_RU[d.weekday()]} {d.day} {MONTHS_RU[d.month]}"
        except Exception:
            return ""

    text += "\n".join(
        f"• {w['title']} ({fmt_date(w)})" if fmt_date(w) else f"• {w['title']}"
        for w in workouts
    )
    await callback.message.edit_text(text, reply_markup=workout_list_keyboard(workouts, "weekly", uid), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "lectures")
async def cb_lectures(callback: types.CallbackQuery):
    """Лекции по питанию — бесплатно, без подписки."""
    lectures = get_nutrition_lectures()

    if not lectures:
        text = "📭 Материалы по питанию пока не добавлены.\n\nСкоро здесь появятся материалы 🍎"
        kb = back_keyboard()
    else:
        buttons = []
        for lec in lectures:
            buttons.append([InlineKeyboardButton(
                text=f"🍎 {lec['title']}",
                callback_data=f"lec:{lec['id']}"
            )])
        buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back")])
        text = "🍎 <b>Информация по питанию</b>\n\nДоступны всем бесплатно:\n\n"
        text += "\n".join(f"• {lec['title']}" for lec in lectures)
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        # Предыдущее сообщение было медиа — удаляем и отправляем новое
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("lec:"))
async def cb_show_lecture(callback: types.CallbackQuery):
    lecture_id = int(callback.data.split(":")[1])
    lecture = get_nutrition_lecture(lecture_id)
    if not lecture:
        await callback.answer("Лекция не найдена")
        return

    text = f"🍎 <b>{lecture['title']}</b>\n\n"
    if lecture["description"]:
        text += f"📝 {lecture['description']}\n"

    buttons = []
    # Одна кнопка для материала — ссылка на Google Drive (видео, PDF или что угодно)
    if lecture["video_url"]:
        buttons.append([InlineKeyboardButton(text="📎 Открыть материал", url=lecture["video_url"])])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="lectures")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    media_id = lecture["media_file_id"] if "media_file_id" in lecture.keys() else None
    # Обратная совместимость со старым полем gif_file_id
    if not media_id and "gif_file_id" in lecture.keys():
        media_id = lecture["gif_file_id"]
    media_type = lecture["media_type"] if "media_type" in lecture.keys() else ("animation" if media_id else None)

    if media_id:
        await callback.message.delete()
        if media_type == "photo":
            await bot.send_photo(callback.from_user.id, media_id, caption=text, reply_markup=kb, parse_mode="HTML")
        elif media_type == "video_note":
            # video_note не поддерживает caption — сначала кружочек, потом текст
            await bot.send_video_note(callback.from_user.id, media_id)
            await bot.send_message(callback.from_user.id, text, reply_markup=kb, parse_mode="HTML")
        elif media_type == "video":
            await bot.send_video(callback.from_user.id, media_id, caption=text, reply_markup=kb, parse_mode="HTML")
        else:
            await bot.send_animation(callback.from_user.id, media_id, caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("wk:"))
async def cb_show_workout(callback: types.CallbackQuery):
    _, workout_type, wid_str = callback.data.split(":", 2)
    workout_id = int(wid_str)
    uid = callback.from_user.id

    workouts = get_permanent_workouts() if workout_type == "permanent" else get_active_weekly_workouts()
    if workout_type == "weekly" and not is_subscribed(uid):
        await callback.answer("❌ Подписка не активна!", show_alert=True)
        return

    workout = next((w for w in workouts if w["id"] == workout_id), None)
    if not workout:
        await callback.answer("Тренировка не найдена")
        return

    done = has_completed_workout(uid, workout_id, workout_type)
    text = f"🏋️ <b>{workout['title']}</b>\n\n"
    if done:
        text += "✅ <i>Вы уже выполнили эту тренировку</i>\n\n"
    text += f"📝 {workout['description']}\n\n" if workout['description'] else ""

    buttons = []
    if workout["video_url"]:
        buttons.append([InlineKeyboardButton(text="🎥 Смотреть видео", url=workout["video_url"])])
    if not done:
        buttons.append([InlineKeyboardButton(text="✅ Отметить выполненным", callback_data=f"done:{workout_type}:{workout_id}")])
    back_target = "permanent" if workout_type == "permanent" else "weekly"
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=back_target)])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("done:"))
async def cb_complete(callback: types.CallbackQuery):
    _, workout_type, wid_str = callback.data.split(":", 2)
    workout_id = int(wid_str)
    uid = callback.from_user.id

    if workout_type == "weekly" and not is_subscribed(uid):
        await callback.answer("❌ Подписка не активна!", show_alert=True)
        return
    if has_completed_workout(uid, workout_id, workout_type):
        await callback.answer("Уже отмечено ранее.", show_alert=True)
        return

    mark_workout_done(uid, workout_id, workout_type)
    await callback.answer("✅ Отлично! Тренировка засчитана!", show_alert=True)
    callback.data = f"wk:{workout_type}:{workout_id}"
    await cb_show_workout(callback)



@dp.callback_query(F.data == "sub_info")
async def cb_sub_info(callback: types.CallbackQuery):
    days = get_subscription_days_left(callback.from_user.id)
    await callback.answer(f"⭐ Осталось дней подписки: {days}", show_alert=True)


@dp.callback_query(F.data == "help")
async def cb_help(callback: types.CallbackQuery):
    days_names = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
    days_str = ", ".join(days_names[d] for d in SCHEDULE_DAYS)
    text = (
        "❓ <b>Помощь</b>\n\n"
        "Как пользоваться ботом:\n"
        "1. Выбери раздел в меню\n"
        "2. Нажми на тренировку или материал для просмотра\n"
        "3. После выполнения тренировки отметь её ✅\n\n"
        f"📅 Тренировки выходят по расписанию: {days_str} в {SCHEDULE_TIME}\n"
        "🔄 Контент обновляется каждый месяц\n\n"
        "📏 В разделе «Прогресс» можно отслеживать параметры тела и добавлять фото\n\n"
        "По вопросам подписки и оплаты: @rom_la\n"
        "⚙️ По техническим вопросам: @rom_la"
    )
    try:
        await callback.message.edit_text(text, reply_markup=back_keyboard(), parse_mode="HTML")
    except Exception:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=back_keyboard(), parse_mode="HTML")
    await callback.answer()

    text = (
        "❓ <b>Помощь</b>\n\n"
        "Как пользоваться ботом:\n"
        "1. Выбери тип тренировок в меню\n"
        "2. Нажми на тренировку для просмотра\n"
        "3. После выполнения отметь её ✅\n\n"
        f"📅 Новые тренировки выходят: {days_str} в {SCHEDULE_TIME}\n"
        "🔄 В конце каждого месяца контент обновляется\n\n"
        "По вопросам: @rom_la"
    )
    await callback.message.edit_text(text, reply_markup=back_keyboard(), parse_mode="HTML")
    await callback.answer()


# ========== ОПЛАТА (bePaid / Telegram Payments) ==========

@dp.callback_query(F.data == "buy_sub")
async def cb_buy_sub(callback: types.CallbackQuery):
    uid = callback.from_user.id

    # Если провайдер не настроен — показываем инструкцию
    if not BEPAID_PROVIDER_TOKEN or BEPAID_PROVIDER_TOKEN == "ВСТАВЬ_PROVIDER_TOKEN":
        text = (
            "💎 <b>Подписка на фитнес-бот</b>\n\n"
            f"Цена: <b>{SUBSCRIPTION_PRICE} BYN / {SUBSCRIPTION_DAYS} дней</b>\n\n"
            "Что включено:\n"
            "• Новые тренировки каждую неделю\n"
            "• Доступ ко всем материалам месяца\n"
            "• Автоматические уведомления\n\n"
            "Для оплаты напишите администратору: @rom_la"
        )
        await callback.message.edit_text(text, reply_markup=back_keyboard(), parse_mode="HTML")
        await callback.answer()
        return

    # Отправляем инвойс через Telegram Payments
    await callback.message.delete()
    await bot.send_invoice(
        chat_id=uid,
        title="💎 Подписка на фитнес-бот",
        description=(
            f"Доступ к тренировкам на {SUBSCRIPTION_DAYS} дней.\n"
            "Новые тренировки каждую неделю, уведомления по расписанию."
        ),
        payload=f"sub_{uid}_{SUBSCRIPTION_DAYS}",
        provider_token=BEPAID_PROVIDER_TOKEN,
        currency="BYR",
        prices=[LabeledPrice(label=f"Подписка {SUBSCRIPTION_DAYS} дней", amount=SUBSCRIPTION_PRICE * 100)],
        start_parameter="subscribe",
        photo_url="https://i.imgur.com/5k3gPRk.png",
        photo_width=800,
        photo_height=400,
        need_name=False,
        need_phone_number=False,
        need_email=False,
        is_flexible=False,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 Оплатить {SUBSCRIPTION_PRICE} BYN", pay=True)],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back")]
        ])
    )
    await callback.answer()


@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    """Подтверждаем платёж перед списанием."""
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    """Платёж прошёл — активируем подписку."""
    uid = message.from_user.id
    payload = message.successful_payment.invoice_payload  # "sub_123456_30"

    try:
        days = int(payload.split("_")[-1])
    except (ValueError, IndexError):
        days = SUBSCRIPTION_DAYS

    activate_subscription(uid, days)

    # Приветственное сообщение с фото если настроено
    await send_welcome(uid, reply_markup=main_menu(uid))

    # Уведомляем админов
    username = f"@{message.from_user.username}" if message.from_user.username else str(uid)
    amount = message.successful_payment.total_amount // 100
    currency = message.successful_payment.currency
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"💰 <b>Новая оплата!</b>\n\n"
                f"👤 Пользователь: {username} (id: {uid})\n"
                f"💵 Сумма: {amount} {currency}\n"
                f"📅 Подписка на: {days} дней",
                parse_mode="HTML"
            )
        except Exception:
            pass


# ========== ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ ==========

@dp.callback_query(F.data == "extra")
async def cb_extra(callback: types.CallbackQuery):
    materials = get_extra_materials()
    if not materials:
        try:
            await callback.message.edit_text(
                "📭 Дополнительные материалы пока не добавлены.",
                reply_markup=back_keyboard()
            )
        except Exception:
            await callback.message.delete()
            await callback.message.answer("📭 Дополнительные материалы пока не добавлены.", reply_markup=back_keyboard())
        await callback.answer()
        return

    buttons = [[InlineKeyboardButton(text=f"📋 {m['title']}", callback_data=f"ext:{m['id']}")] for m in materials]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back")])
    text = "📋 <b>Дополнительная информация</b>\n\n" + "\n".join(f"• {m['title']}" for m in materials)
    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    except Exception:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("ext:"))
async def cb_show_extra(callback: types.CallbackQuery):
    material_id = int(callback.data.split(":")[1])
    m = get_extra_material(material_id)
    if not m:
        await callback.answer("Материал не найден")
        return

    text = f"📋 <b>{m['title']}</b>\n\n"
    if m["description"]:
        text += f"📝 {m['description']}\n"

    buttons = []
    if m["video_url"]:
        buttons.append([InlineKeyboardButton(text="📎 Открыть материал", url=m["video_url"])])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="extra")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    media_id = m["media_file_id"] if "media_file_id" in m.keys() else None
    media_type = m["media_type"] if "media_type" in m.keys() else None

    if media_id:
        await callback.message.delete()
        if media_type == "photo":
            await bot.send_photo(callback.from_user.id, media_id, caption=text, reply_markup=kb, parse_mode="HTML")
        elif media_type == "video":
            await bot.send_video(callback.from_user.id, media_id, caption=text, reply_markup=kb, parse_mode="HTML")
        elif media_type == "video_note":
            await bot.send_video_note(callback.from_user.id, media_id)
            await bot.send_message(callback.from_user.id, text, reply_markup=kb, parse_mode="HTML")
        else:
            await bot.send_animation(callback.from_user.id, media_id, caption=text, reply_markup=kb, parse_mode="HTML")
    else:
        try:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ========== ПРОГРЕСС ==========

@dp.callback_query(F.data == "progress")
async def cb_progress(callback: types.CallbackQuery):
    uid = callback.from_user.id
    with get_db() as conn:
        perm = conn.execute('SELECT COUNT(*) FROM completed_workouts WHERE user_id=? AND workout_type="permanent"', (uid,)).fetchone()[0]
        week = conn.execute('SELECT COUNT(*) FROM completed_workouts WHERE user_id=? AND workout_type="weekly"', (uid,)).fetchone()[0]

    params = get_body_params(uid)
    history = get_body_params_history(uid, limit=5)
    photos = get_progress_photos(uid)

    text = "📊 <b>Мой прогресс</b>\n\n"
    text += f"🏋️ Закреплённых выполнено: <b>{perm}</b>\n"
    if is_subscribed(uid):
        text += f"⭐ Тренировок месяца выполнено: <b>{week}</b>\n"
        text += f"⏳ Осталось дней подписки: <b>{get_subscription_days_left(uid)}</b>\n"

    text += "\n📏 <b>Текущие параметры:</b>\n"
    PARAM_LABELS = [
        ("weight", "Вес", "кг"),
        ("chest", "Грудь", "см"),
        ("waist", "Талия", "см"),
        ("hips", "Бёдра", "см"),
        ("arm", "Рука", "см"),
        ("thigh", "Бедро", "см"),
    ]

    if params:
        prev = history[1] if len(history) > 1 else None
        has_any = False
        for field, name, unit in PARAM_LABELS:
            val = params[field]
            if val:
                diff = ""
                if prev and prev[field]:
                    delta = round(val - prev[field], 1)
                    if delta > 0:
                        diff = f" <i>(+{delta})</i>"
                    elif delta < 0:
                        diff = f" <i>({delta})</i>"
                text += f"• {name}: <b>{val} {unit}</b>{diff}\n"
                has_any = True
        if not has_any:
            text += "<i>Параметры не заполнены</i>\n"
        if params["updated_at"]:
            text += f"\n<i>Обновлено: {params['updated_at'][:10]}</i>"
    else:
        text += "<i>Параметры не заполнены</i>\n"

    if len(history) > 1:
        text += "\n\n📈 <b>История замеров:</b>\n"
        for rec in history[:4]:
            date = rec["recorded_at"][:10] if rec["recorded_at"] else "—"
            parts = []
            if rec["weight"]: parts.append(f"вес {rec['weight']} кг")
            if rec["waist"]: parts.append(f"талия {rec['waist']} см")
            if rec["hips"]: parts.append(f"бёдра {rec['hips']} см")
            if parts:
                text += f"<i>{date}: {', '.join(parts)}</i>\n"

    if photos:
        text += f"\n📸 Фото прогресса: <b>{len(photos)} шт.</b>"

    buttons = [
        [InlineKeyboardButton(text="📏 Обновить параметры", callback_data="progress:params")],
        [InlineKeyboardButton(text="📸 Добавить фото прогресса", callback_data="progress:photo")],
    ]
    if len(photos) >= 2:
        buttons.append([InlineKeyboardButton(text=f"🔄 Сравнить до/после ({len(photos)} фото)", callback_data="progress:compare")])
    elif len(photos) == 1:
        buttons.append([InlineKeyboardButton(text="🖼️ Посмотреть фото", callback_data="progress:view_photo")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back")])

    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    except Exception:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data == "progress:params")
async def cb_progress_params(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BodyParamsState.weight)
    await state.update_data(params={})
    await callback.message.edit_text(
        "📏 <b>Параметры тела (1/6)</b>\n\n⚖️ Вес\nВведи число в <b>кг</b>:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="params:skip:weight")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="progress")],
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


BODY_FIELDS_ORDER = [
    ("weight", "⚖️ Вес",          "кг", BodyParamsState.weight,  "chest"),
    ("chest",  "📐 Обхват груди", "см", BodyParamsState.chest,   "waist"),
    ("waist",  "📐 Обхват талии", "см", BodyParamsState.waist,   "hips"),
    ("hips",   "📐 Обхват бёдер", "см", BodyParamsState.hips,    "arm"),
    ("arm",    "📐 Обхват руки",  "см", BodyParamsState.arm,     "thigh"),
    ("thigh",  "📐 Обхват бедра", "см", BodyParamsState.thigh,   None),
]
FIELD_IDX = {f[0]: i for i, f in enumerate(BODY_FIELDS_ORDER)}


def _param_kb(skip_field):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data=f"params:skip:{skip_field}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="progress")],
    ])


async def _save_and_next(target, state, field, value, edit=False):
    data = await state.get_data()
    params = data.get("params", {})
    if value is not None:
        params[field] = value
    await state.update_data(params=params)

    # Найти следующее поле
    current = next((f for f in BODY_FIELDS_ORDER if f[0] == field), None)
    next_field = current[4] if current else None

    if next_field:
        next_info = next(f for f in BODY_FIELDS_ORDER if f[0] == next_field)
        idx = FIELD_IDX[next_field] + 1
        text = f"📏 <b>Параметры тела ({idx}/6)</b>\n\n{next_info[1]}\nВведи число в <b>{next_info[2]}</b>:"
        await state.set_state(next_info[3])
        try:
            await target.edit_text(text, reply_markup=_param_kb(next_field), parse_mode="HTML")
        except Exception:
            await target.answer(text, reply_markup=_param_kb(next_field), parse_mode="HTML")
    else:
        # Всё заполнено — сохраняем
        uid = target.chat.id if hasattr(target, 'chat') else getattr(target, 'from_user', None)
        if uid and hasattr(uid, 'id'):
            uid = uid.id
        if params and uid:
            save_body_params(uid, params)
        await state.clear()
        labels = {f[0]: f[1] for f in BODY_FIELDS_ORDER}
        units = {f[0]: f[2] for f in BODY_FIELDS_ORDER}
        saved = "\n".join(f"• {labels[k]}: <b>{v} {units[k]}</b>" for k,v in params.items()) if params else "<i>Ничего не сохранено</i>"
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ К прогрессу", callback_data="progress")]])
        text = f"✅ <b>Параметры сохранены!</b>\n\n{saved}"
        try:
            await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await target.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data.startswith("params:skip:"))
async def cb_param_skip(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[2]
    await _save_and_next(callback.message, state, field, None, edit=True)
    await callback.answer()


@dp.message(BodyParamsState.weight)
async def bp_weight(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.strip().replace(",", "."))
        await _save_and_next(message, state, "weight", val, edit=False)
    except ValueError:
        await message.answer("❌ Введи число (кг), например: <code>65</code>", reply_markup=_param_kb("weight"), parse_mode="HTML")


@dp.message(BodyParamsState.chest)
async def bp_chest(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.strip().replace(",", "."))
        await _save_and_next(message, state, "chest", val, edit=False)
    except ValueError:
        await message.answer("❌ Введи число (см), например: <code>90</code>", reply_markup=_param_kb("chest"), parse_mode="HTML")


@dp.message(BodyParamsState.waist)
async def bp_waist(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.strip().replace(",", "."))
        await _save_and_next(message, state, "waist", val, edit=False)
    except ValueError:
        await message.answer("❌ Введи число (см), например: <code>70</code>", reply_markup=_param_kb("waist"), parse_mode="HTML")


@dp.message(BodyParamsState.hips)
async def bp_hips(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.strip().replace(",", "."))
        await _save_and_next(message, state, "hips", val, edit=False)
    except ValueError:
        await message.answer("❌ Введи число (см), например: <code>95</code>", reply_markup=_param_kb("hips"), parse_mode="HTML")


@dp.message(BodyParamsState.arm)
async def bp_arm(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.strip().replace(",", "."))
        await _save_and_next(message, state, "arm", val, edit=False)
    except ValueError:
        await message.answer("❌ Введи число (см), например: <code>28</code>", reply_markup=_param_kb("arm"), parse_mode="HTML")


@dp.message(BodyParamsState.thigh)
async def bp_thigh(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.strip().replace(",", "."))
        await _save_and_next(message, state, "thigh", val, edit=False)
    except ValueError:
        await message.answer("❌ Введи число (см), например: <code>55</code>", reply_markup=_param_kb("thigh"), parse_mode="HTML")


@dp.callback_query(F.data == "progress:photo")
async def cb_progress_photo_prompt(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(BodyParamsState.photo)
    await callback.message.edit_text(
        "📸 <b>Фото прогресса</b>\n\nПришли фотографию — она сохранится и будет видна только тебе.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="progress")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(BodyParamsState.photo, F.photo)
async def cb_save_progress_photo(message: types.Message, state: FSMContext):
    save_progress_photo(message.from_user.id, message.photo[-1].file_id)
    await state.clear()
    await message.answer(
        "✅ Фото прогресса сохранено!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К прогрессу", callback_data="progress")]
        ])
    )


@dp.callback_query(F.data == "progress:view_photo")
async def cb_view_progress_photo(callback: types.CallbackQuery):
    uid = callback.from_user.id
    photos = get_progress_photos(uid, limit=1)
    if not photos:
        await callback.answer("Фото не найдено", show_alert=True)
        return
    await callback.message.delete()
    await bot.send_photo(
        uid, photos[0]["file_id"],
        caption=f"🖼️ Твоё фото ({photos[0]['uploaded_at'][:10]})",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К прогрессу", callback_data="progress")]
        ])
    )
    await callback.answer()


@dp.callback_query(F.data == "progress:compare")
async def cb_compare_photos(callback: types.CallbackQuery):
    uid = callback.from_user.id
    photos = get_progress_photos(uid)
    if len(photos) < 2:
        await callback.answer("Нужно минимум 2 фото для сравнения", show_alert=True)
        return

    await callback.message.delete()
    # Самое новое фото
    latest = photos[0]
    # Самое старое фото
    oldest = photos[-1]

    await bot.send_photo(
        uid, oldest["file_id"],
        caption=f"⬅️ <b>Начало</b> ({oldest['uploaded_at'][:10]})",
        parse_mode="HTML"
    )
    await bot.send_photo(
        uid, latest["file_id"],
        caption=f"➡️ <b>Сейчас</b> ({latest['uploaded_at'][:10]})\n\n"
                f"📸 Всего фото: {len(photos)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К прогрессу", callback_data="progress")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()



# ========== ADMIN CALLBACKS ==========

@dp.callback_query(F.data == "adm:help")
async def adm_help(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    text = (
        "❓ <b>Подробная помощь по панели</b>\n\n"

        "🏋️ <b>Закреплённые тренировки</b>\n"
        "Видны всем пользователям без подписки. Это постоянный контент — разминка, заминка, дыхание и т.д. "
        "Добавляй сюда то, что актуально всегда.\n\n"

        "📅 <b>Тренировки месяца</b>\n"
        "Видны только подписчикам. После добавления тренировка встаёт в очередь. "
        "Каждый вс/вт/чт в 20:00 бот берёт следующую из очереди и рассылает подписчикам. "
        "Накануне в 12:00 ты получишь предупреждение если очередь пуста.\n\n"

        "🍎 <b>Информация по питанию</b>\n"
        "Доступны всем без подписки. Добавляй ссылки на Google Drive с видео или PDF. "
        "Можно прикрепить фото/видео которое будет показываться при открытии лекции.\n\n"

        "✅ <b>Активация подписки</b>\n"
        "После оплаты активируй подписку вручную. Выбери длительность: 1/30/60/90 дней. "
        "Пользователь получит приветственное сообщение автоматически.\n\n"

        "✏️ <b>Редактирование</b>\n"
        "Можно менять название, описание, ссылку на видео, медиафайл. "
        "⚠️ Удаление необратимо — данные нельзя восстановить!\n\n"

        "📢 <b>Рассылка</b>\n"
        "Отправляет сообщение ВСЕМ пользователям кто когда-либо запускал бота. "
        "Поддерживается HTML: <code>&lt;b&gt;жирный&lt;/b&gt;</code>, <code>&lt;i&gt;курсив&lt;/i&gt;</code>.\n\n"

        "🗑️ <b>Очистка</b>\n"
        "Удаляет только уже отправленные тренировки старше 30 дней. "
        "Неотправленные тренировки из очереди НЕ затрагиваются.\n\n"

        "💾 <b>Бэкап</b>\n"
        "Каждое воскресенье в 04:00 бот автоматически присылает тебе файл базы данных. "
        "Сохраняй эти файлы — это твоя страховка от потери данных."
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "adm:cancel")
async def adm_cancel(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.clear()
    await send_admin_panel(callback, edit=True)


@dp.callback_query(F.data == "adm:users")
async def adm_users(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    users = get_all_users()
    if not users:
        await callback.message.edit_text("Пользователей пока нет.", reply_markup=back_keyboard("adm:back"))
        await callback.answer()
        return

    total = len(users)
    active = sum(1 for u in users if is_subscribed(u["user_id"]))
    lines = []
    for u in users[:30]:
        name = f"@{u['username']}" if u["username"] else str(u["user_id"])
        if is_subscribed(u["user_id"]):
            days_left = get_subscription_days_left(u["user_id"])
            lines.append(f"⭐ {name} — осталось <b>{days_left} дн.</b> (до {u['subscribed_until']})")
        else:
            lines.append(f"👤 {name} — без подписки")

    text = f"👥 <b>Пользователи: {total}</b> (активных подписок: {active})\n\n" + "\n".join(lines)
    if total > 30:
        text += f"\n\n... и ещё {total - 30}"

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "adm:cleanup")
async def adm_cleanup(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    deleted = cleanup_old_workouts()
    await callback.answer(
        f"🗑️ Удалено {deleted} отправленных тренировок старше 30 дней.\n"
        f"Неотправленные тренировки из очереди не тронуты.",
        show_alert=True
    )
    await send_admin_panel(callback, edit=True)


@dp.callback_query(F.data == "adm:back")
async def adm_back(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await send_admin_panel(callback, edit=True)


# --- Активация вручную ---

@dp.callback_query(F.data == "adm:activate")
async def adm_activate_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(ActivateState.user_id)
    await callback.message.edit_text(
        "✅ <b>Активация подписки</b>\n\n"
        "ℹ️ После активации пользователь получит приветственное сообщение "
        "и доступ к разделу «⭐ Тренировки месяца».\n\n"
        "Введи <b>@никнейм</b> или <b>Telegram ID</b> пользователя:",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.message(ActivateState.user_id)
async def adm_activate_uid(message: types.Message, state: FSMContext):
    text = message.text.strip()
    uid = None
    display = text

    if text.lstrip('@').isdigit():
        # Это числовой ID
        uid = int(text.lstrip('@'))
        display = str(uid)
    else:
        # Это никнейм — ищем в базе
        user = get_user_by_username(text)
        if user:
            uid = user["user_id"]
            display = f"@{user['username']} (id: {uid})"
        else:
            await message.answer(
                f"❌ Пользователь <code>{text}</code> не найден в базе.\n\n"
                "Пользователь должен сначала запустить бота (/start), "
                "чтобы появиться в базе.\n\nПопробуй ещё раз:",
                reply_markup=cancel_keyboard(), parse_mode="HTML"
            )
            return

    await state.update_data(user_id=uid)
    await state.set_state(ActivateState.days)
    await message.answer(
        f"👤 Пользователь: <b>{display}</b>\n\nНа сколько дней?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="1 день", callback_data="adm:days:1"),
                InlineKeyboardButton(text="30 дней", callback_data="adm:days:30"),
                InlineKeyboardButton(text="60 дней", callback_data="adm:days:60"),
                InlineKeyboardButton(text="90 дней", callback_data="adm:days:90"),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")]
        ]),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("adm:days:"))
async def adm_activate_days(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    days = int(callback.data.split(":")[2])
    data = await state.get_data()
    uid = data.get("user_id")
    if not uid:
        await state.clear()
        await send_admin_panel(callback, edit=True)
        return
    add_user(uid, None)
    activate_subscription(uid, days)
    await state.clear()
    try:
        await send_welcome(uid)
    except Exception:
        pass
    await callback.message.edit_text(
        f"✅ Подписка для <code>{uid}</code> активирована на <b>{days} дней</b>.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


# --- Добавить закреплённую ---

@dp.callback_query(F.data == "adm:add_permanent")
async def adm_add_perm_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AddPermanentState.title)
    await callback.message.edit_text(
        "🏋️ <b>Добавить закреплённую тренировку</b>\n\n"
        "ℹ️ Закреплённые тренировки <b>видны всем пользователям без подписки</b> — это постоянный базовый контент.\n\n"
        "Введи <b>название</b> тренировки:",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddPermanentState.title)
async def ap_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddPermanentState.description)
    await message.answer(
        "Введи <b>описание</b>:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="adm:perm_skip_desc")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")],
        ]),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "adm:perm_skip_desc", AddPermanentState.description)
async def ap_desc_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(description=None)
    await state.set_state(AddPermanentState.url)
    await callback.message.edit_text(
        "Введи <b>ссылку на видео</b>:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="adm:perm_skip_url")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")],
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddPermanentState.description)
async def ap_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddPermanentState.url)
    await message.answer(
        "Введи <b>ссылку на видео</b>:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="adm:perm_skip_url")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")],
        ]),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "adm:perm_skip_url", AddPermanentState.url)
async def ap_url_skip(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    add_permanent_workout(data["title"], data.get("description"), None, 0)
    await state.clear()
    await callback.message.edit_text(
        f"✅ Тренировка «<b>{data['title']}</b>» добавлена!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddPermanentState.url)
async def ap_url(message: types.Message, state: FSMContext):
    data = await state.get_data()
    add_permanent_workout(data["title"], data.get("description"), message.text.strip(), 0)
    await state.clear()
    await message.answer(
        f"✅ Тренировка «<b>{data['title']}</b>» добавлена!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )



# --- Добавить тренировку месяца ---

@dp.callback_query(F.data == "adm:add_weekly")
async def adm_add_weekly_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AddWeeklyState.title)
    await callback.message.edit_text(
        "📅 <b>Добавить тренировку месяца</b>\n\n"
        "ℹ️ Тренировка встанет в очередь и будет автоматически отправлена подписчикам "
        "в ближайший день по расписанию (вс/вт/чт в 20:00).\n\n"
        "Введи <b>название</b> тренировки:",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddWeeklyState.title)
async def aw_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddWeeklyState.description)
    await message.answer(
        "Введи <b>описание</b>:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="adm:week_skip_desc")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")],
        ]),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "adm:week_skip_desc", AddWeeklyState.description)
async def aw_desc_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(description=None)
    await state.set_state(AddWeeklyState.url)
    await callback.message.edit_text(
        "Введи <b>ссылку на видео</b>:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="adm:week_skip_url")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")],
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddWeeklyState.description)
async def aw_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddWeeklyState.url)
    await message.answer(
        "Введи <b>ссылку на видео</b>:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="adm:week_skip_url")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")],
        ]),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "adm:week_skip_url", AddWeeklyState.url)
async def aw_url_skip(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    add_weekly_workouts([{"title": data["title"], "description": data.get("description"), "video_url": None, "duration": 0}])
    await state.clear()
    await callback.message.edit_text(
        f"✅ Тренировка «<b>{data['title']}</b>» добавлена в тренировки месяца!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddWeeklyState.url)
async def aw_url(message: types.Message, state: FSMContext):
    data = await state.get_data()
    add_weekly_workouts([{"title": data["title"], "description": data.get("description"), "video_url": message.text.strip(), "duration": 0}])
    await state.clear()
    await message.answer(
        f"✅ Тренировка «<b>{data['title']}</b>» добавлена в тренировки месяца!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )


# --- Добавить лекцию по питанию ---

def skip_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭️ Пропустить", callback_data="adm:lec_skip")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="adm:cancel")],
    ])


@dp.callback_query(F.data == "adm:add_lecture")
async def adm_add_lecture_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AddLectureState.url)
    await callback.message.edit_text(
        "🍎 <b>Новая лекция по питанию</b>\n\n"
        "Пришли <b>ссылку на Google Drive</b> (видео или PDF).\n"
        "Пользователь увидит кнопку «📎 Открыть материал».\n\n"
        "Или нажми «⏭️ Пропустить» если материала нет:",
        reply_markup=skip_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "adm:lec_skip", AddLectureState.url)
async def al_url_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(video_url=None)
    await state.set_state(AddLectureState.title)
    await callback.message.edit_text(
        "Введи <b>название</b> лекции:",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddLectureState.url)
async def al_url(message: types.Message, state: FSMContext):
    url = message.text.strip() if message.text else ""
    await state.update_data(video_url=url if url else None)
    await state.set_state(AddLectureState.title)
    await message.answer(
        "Введи <b>название</b> лекции:\n\n<i>Например: «Шпаргалка по питанию»</i>",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )


@dp.callback_query(F.data == "adm:lec_skip", AddLectureState.title)
async def al_title_skip(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("Введи название вручную", show_alert=True)


@dp.message(AddLectureState.title)
async def al_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddLectureState.description)
    await message.answer(
        "Введи <b>описание</b> или нажми «⏭️ Пропустить»:",
        reply_markup=skip_keyboard(), parse_mode="HTML"
    )


@dp.callback_query(F.data == "adm:lec_skip", AddLectureState.description)
async def al_desc_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(description=None)
    await state.set_state(AddLectureState.media)
    await callback.message.edit_text(
        "🖼️ Пришли <b>фото, GIF или короткое видео</b> для лекции, или нажми «⏭️ Пропустить»:",
        reply_markup=skip_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.message(AddLectureState.description)
async def al_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(AddLectureState.media)
    await message.answer(
        "🖼️ Пришли <b>фото, GIF или короткое видео</b> для лекции, или нажми «⏭️ Пропустить»:",
        reply_markup=skip_keyboard(), parse_mode="HTML"
    )


@dp.message(AddLectureState.media, F.animation | F.photo | F.video | F.video_note | F.document)
async def al_media_any(message: types.Message, state: FSMContext):
    file_id, media_type = _get_media_from_message(message)
    if not file_id:
        await message.answer("❌ Не удалось распознать файл. Пришли фото, GIF или видео:", reply_markup=skip_keyboard())
        return
    await state.update_data(media_file_id=file_id, media_type=media_type)
    await _save_lecture(message, state, answer_method="answer")


@dp.callback_query(F.data == "adm:lec_skip", AddLectureState.media)
async def al_gif_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(media_file_id=None)
    await _save_lecture(callback.message, state, answer_method="edit")
    await callback.answer()


async def _save_lecture(target, state: FSMContext, answer_method="answer"):
    data = await state.get_data()
    title = data.get("title") or "Лекция"
    add_nutrition_lecture(
        title, data.get("description"), data.get("video_url"),
        media_file_id=data.get("media_file_id"),
        media_type=data.get("media_type")
    )
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
    ])
    text = f"✅ Материал «<b>{title}</b>» добавлен!"
    if answer_method == "edit":
        await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


# --- Добавить доп. информацию (аналог лекций) ---

@dp.callback_query(F.data == "adm:add_extra")
async def adm_add_extra_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(AddExtraState.url)
    await callback.message.edit_text(
        "📋 <b>Новый доп. материал</b>\n\n"
        "Пришли <b>ссылку на материал</b> (Google Drive, YouTube и т.д.)\n"
        "или нажми «⏭️ Пропустить»:",
        reply_markup=skip_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data == "adm:lec_skip", AddExtraState.url)
async def ae_url_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(video_url=None)
    await state.set_state(AddExtraState.title)
    await callback.message.edit_text("Введи <b>название</b> материала:", reply_markup=cancel_keyboard(), parse_mode="HTML")
    await callback.answer()


@dp.message(AddExtraState.url)
async def ae_url(message: types.Message, state: FSMContext):
    await state.update_data(video_url=message.text.strip())
    await state.set_state(AddExtraState.title)
    await message.answer("Введи <b>название</b> материала:", reply_markup=cancel_keyboard(), parse_mode="HTML")


@dp.message(AddExtraState.title)
async def ae_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(AddExtraState.description)
    await message.answer("Введи <b>описание</b> или нажми «⏭️ Пропустить»:", reply_markup=skip_keyboard(), parse_mode="HTML")


@dp.callback_query(F.data == "adm:lec_skip", AddExtraState.description)
async def ae_desc_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(description=None)
    await state.set_state(AddExtraState.media)
    await callback.message.edit_text("🖼️ Пришли <b>фото, GIF или видео</b> или нажми «⏭️ Пропустить»:", reply_markup=skip_keyboard(), parse_mode="HTML")
    await callback.answer()


@dp.message(AddExtraState.description)
async def ae_desc(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(AddExtraState.media)
    await message.answer("🖼️ Пришли <b>фото, GIF или видео</b> или нажми «⏭️ Пропустить»:", reply_markup=skip_keyboard(), parse_mode="HTML")


@dp.message(AddExtraState.media, F.animation | F.photo | F.video | F.video_note | F.document)
async def ae_media(message: types.Message, state: FSMContext):
    file_id, media_type = _get_media_from_message(message)
    if not file_id:
        await message.answer("❌ Не удалось распознать файл:", reply_markup=skip_keyboard())
        return
    await state.update_data(media_file_id=file_id, media_type=media_type)
    await _save_extra(message, state, answer_method="answer")


@dp.callback_query(F.data == "adm:lec_skip", AddExtraState.media)
async def ae_media_skip(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(media_file_id=None, media_type=None)
    await _save_extra(callback.message, state, answer_method="edit")
    await callback.answer()


async def _save_extra(target, state: FSMContext, answer_method="answer"):
    data = await state.get_data()
    title = data.get("title") or "Материал"
    add_extra_material(title, data.get("description"), data.get("video_url"),
                       media_file_id=data.get("media_file_id"), media_type=data.get("media_type"))
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]])
    text = f"✅ Материал «<b>{title}</b>» добавлен!"
    if answer_method == "edit":
        await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


# ========== РЕДАКТИРОВАНИЕ КОНТЕНТА (закреплённые/месяц/лекции) ==========
# content_type: "permanent" | "weekly" | "lecture" | "extra"

CONTENT_CONFIG = {
    "permanent": {
        "title": "Закреплённые тренировки",
        "get_list": get_permanent_workouts,
        "get_one": get_permanent_workout,
        "update": update_permanent_workout,
        "delete": delete_permanent_workout,
        "fields": [("title", "Название"), ("description", "Описание"),
                   ("video_url", "Ссылка на видео")],
    },
    "weekly": {
        "title": "Тренировки месяца",
        "get_list": get_active_weekly_workouts,
        "get_one": get_weekly_workout,
        "update": update_weekly_workout,
        "delete": delete_weekly_workout,
        "fields": [("title", "Название"), ("description", "Описание"),
                   ("video_url", "Ссылка на видео")],
    },
    "lecture": {
        "title": "Информация по питанию",
        "get_list": get_nutrition_lectures,
        "get_one": get_nutrition_lecture,
        "update": update_nutrition_lecture,
        "delete": delete_nutrition_lecture,
        "fields": [("title", "Название"), ("description", "Описание"),
                   ("video_url", "Ссылка на видео"), ("pdf_url", "Ссылка на PDF (Google Drive)"), ("media_file_id", "Медиа (фото/GIF/видео)")],
    },
    "extra": {
        "title": "Дополнительная информация",
        "get_list": get_extra_materials,
        "get_one": get_extra_material,
        "update": update_extra_material,
        "delete": delete_extra_material,
        "fields": [("title", "Название"), ("description", "Описание"),
                   ("video_url", "Ссылка на материал"), ("media_file_id", "Медиа (фото/GIF/видео)")],
    },
}


@dp.callback_query(F.data.startswith("adm:edit_") & F.data.endswith("_list"))
async def adm_edit_list(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    content_type = callback.data.replace("adm:edit_", "").replace("_list", "")
    cfg = CONTENT_CONFIG[content_type]
    items = cfg["get_list"]()
    if not items:
        await callback.message.edit_text(
            f"📭 «{cfg['title']}» — пока пусто.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
            ])
        )
        await callback.answer()
        return

    buttons = [
        [InlineKeyboardButton(text=f"✏️ {item['title']}", callback_data=f"adm:edit_item:{content_type}:{item['id']}")]
        for item in items
    ]
    buttons.append([InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")])
    await callback.message.edit_text(
        f"✏️ <b>{cfg['title']}</b>\n\nВыбери, что отредактировать:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:edit_item:"))
async def adm_edit_item(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, _, content_type, item_id = callback.data.split(":")
    item_id = int(item_id)
    cfg = CONTENT_CONFIG[content_type]
    item = cfg["get_one"](item_id)
    if not item:
        await callback.answer("Не найдено")
        return

    text = f"✏️ <b>{item['title']}</b>\n\n📝 {item['description']}\n"
    if item["video_url"]:
        text += f"\n🎥 {item['video_url']}"

    buttons = []
    for field, label in cfg["fields"]:
        buttons.append([InlineKeyboardButton(
            text=f"Изменить: {label}",
            callback_data=f"adm:edit_field:{content_type}:{item_id}:{field}"
        )])
    buttons.append([InlineKeyboardButton(
        text="🗑️ Удалить", callback_data=f"adm:delete_item:{content_type}:{item_id}"
    )])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"adm:edit_{content_type}_list")])

    await callback.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:edit_field:"))
async def adm_edit_field_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, _, content_type, item_id, field = callback.data.split(":")
    cfg = CONTENT_CONFIG[content_type]
    label = dict(cfg["fields"])[field]

    await state.set_state(EditFieldState.waiting_value)
    await state.update_data(content_type=content_type, item_id=int(item_id), field=field)

    if field == "media_file_id":
        await callback.message.edit_text(
            "🖼️ Пришли <b>фото, GIF, видео или видеокружок</b>.\n\nИли напиши <code>-</code> чтобы удалить:",
            reply_markup=cancel_keyboard(), parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            f"Введи новое значение для поля «<b>{label}</b>»:",
            reply_markup=cancel_keyboard(), parse_mode="HTML"
        )
    await callback.answer()


def _get_media_from_message(message) -> tuple:
    """Извлекает (file_id, media_type) из сообщения."""
    if message.animation:
        return message.animation.file_id, "animation"
    if message.photo:
        return message.photo[-1].file_id, "photo"
    if message.video:
        return message.video.file_id, "video"
    if message.video_note:
        return message.video_note.file_id, "video_note"
    if message.document:
        mime = message.document.mime_type or ""
        if mime.startswith("video/"):
            return message.document.file_id, "video"
        if mime.startswith("image/"):
            return message.document.file_id, "photo"
    return None, None


@dp.message(EditFieldState.waiting_value, F.animation | F.photo | F.video | F.video_note | F.document)
async def adm_edit_field_media(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("field") != "media_file_id":
        return
    file_id, media_type = _get_media_from_message(message)
    if not file_id:
        await message.answer("❌ Не удалось распознать файл. Пришли фото, GIF или видео:", reply_markup=cancel_keyboard())
        return
    cfg = CONTENT_CONFIG[data["content_type"]]
    cfg["update"](data["item_id"], "media_file_id", file_id)
    cfg["update"](data["item_id"], "media_type", media_type)
    await state.clear()
    await message.answer("✅ Медиа обновлено!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
    ]))


@dp.message(EditFieldState.waiting_value)
async def adm_edit_field_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    content_type = data["content_type"]
    item_id = data["item_id"]
    field = data["field"]
    cfg = CONTENT_CONFIG[content_type]

    # Если ждали GIF но пришёл текст
    if field == "media_file_id":
        if message.text and message.text.strip() in ("-", "нет", "no"):
            cfg["update"](item_id, "media_file_id", None)
            await state.clear()
            await message.answer(
                "✅ Медиа удалено.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ К списку", callback_data=f"adm:edit_{content_type}_list")],
                    [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
                ])
            )
        else:
            await message.answer("❌ Пришли фото, GIF или видео (или напиши <code>-</code> чтобы удалить):", reply_markup=cancel_keyboard(), parse_mode="HTML")
        return

    value = message.text.strip()
    if field == "duration":
        try:
            value = int(value)
        except ValueError:
            await message.answer("❌ Длительность должна быть числом. Попробуй ещё раз:", reply_markup=cancel_keyboard())
            return
    if field in ("video_url", "pdf_url") and value.lower() in ("нет", "no", "-"):
        value = None

    cfg["update"](item_id, field, value)
    await state.clear()
    await message.answer(
        "✅ Изменения сохранены!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К списку", callback_data=f"adm:edit_{content_type}_list")],
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ])
    )


@dp.callback_query(F.data.startswith("adm:delete_item:"))
async def adm_delete_item_confirm(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, _, content_type, item_id = callback.data.split(":")
    type_names = {"permanent": "закреплённую тренировку", "weekly": "тренировку месяца", "lecture": "материал по питанию", "extra": "дополнительный материал"}
    type_name = type_names.get(content_type, "элемент")
    await callback.message.edit_text(
        f"🗑️ <b>Удаление</b>\n\n"
        f"⚠️ Ты собираешься удалить <b>{type_name}</b>.\n\n"
        f"Это действие <b>необратимо</b> — восстановить данные будет невозможно.\n"
        f"Пользователи больше не увидят этот материал.\n\n"
        f"Ты уверен?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"adm:delete_confirm:{content_type}:{item_id}")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"adm:edit_item:{content_type}:{item_id}")]
        ]),
        parse_mode="HTML"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("adm:delete_confirm:"))
async def adm_delete_item_do(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    _, _, content_type, item_id = callback.data.split(":")
    item_id = int(item_id)
    cfg = CONTENT_CONFIG[content_type]
    cfg["delete"](item_id)
    await callback.message.edit_text(
        "🗑️ Удалено.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К списку", callback_data=f"adm:edit_{content_type}_list")],
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ])
    )
    await callback.answer("Удалено")


# --- Рассылка ---

@dp.callback_query(F.data == "adm:broadcast")
async def adm_broadcast_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(BroadcastState.text)
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\n"
        "ℹ️ Сообщение получат <b>все пользователи</b> кто когда-либо запускал бота.\n"
        "Отменить после отправки невозможно.\n\n"
        "Поддерживается HTML:\n"
        "<code>&lt;b&gt;жирный&lt;/b&gt;</code>, <code>&lt;i&gt;курсив&lt;/i&gt;</code>\n\n"
        "Введи текст:",
        reply_markup=cancel_keyboard(), parse_mode="HTML"
    )
    await callback.answer()


@dp.message(BroadcastState.text)
async def adm_broadcast_send(message: types.Message, state: FSMContext):
    await state.clear()
    users = get_all_users()
    sent, failed = 0, 0
    status_msg = await message.answer("⏳ Отправляю рассылку...")
    for u in users:
        try:
            await bot.send_message(u["user_id"], message.text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # 20 сообщений/сек — ниже лимита Telegram
    await status_msg.edit_text(
        f"📢 <b>Рассылка завершена</b>\n\n✅ Отправлено: {sent}\n❌ Ошибок: {failed}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ В панель", callback_data="adm:back")]
        ]),
        parse_mode="HTML"
    )


# ========== SCHEDULER ==========

async def scheduled_cleanup():
    deleted = cleanup_old_workouts()
    logging.info(f"Автоочистка: удалено {deleted}")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, f"🗑️ Автоочистка: удалено {deleted} старых тренировок.")
        except Exception:
            pass


async def backup_database():
    """Еженедельный бэкап базы данных — отправляет файл всем админам."""
    import os
    from config import DATA_DIR
    db_path = os.path.join(DATA_DIR, "fitbot.db")
    if not os.path.exists(db_path):
        return
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    for admin_id in ADMIN_IDS:
        try:
            with open(db_path, "rb") as f:
                await bot.send_document(
                    admin_id, f,
                    filename=f"fitbot_backup_{date_str}.db",
                    caption=f"💾 Еженедельный бэкап базы данных ({date_str})"
                )
        except Exception as e:
            logging.error(f"Ошибка бэкапа для {admin_id}: {e}")


async def send_tomorrow_workout():
    """
    По расписанию (ВС/ВТ/ЧТ, 20:00): вечером отправляем подписчикам
    тренировку на завтра — следующую неотправленную по очерёдности.
    """
    workout = get_next_unsent_workout()
    if not workout:
        logging.info("Нет новых тренировок для отправки — добавь через /admin")
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    "⚠️ Сегодня вечером нужно отправить тренировку на завтра, "
                    "но новых тренировок в очереди нет. Добавь через /admin."
                )
            except Exception:
                pass
        return

    users = get_all_users()
    text = (
        f"🌙 <b>Тренировка на завтра готова!</b>\n\n"
        f"🏋️ {workout['title']}\n\n"
        "Открой меню, чтобы посмотреть подробности 💪"
    )
    count = 0
    for u in users:
        if is_subscribed(u["user_id"]):
            try:
                await bot.send_message(
                    u["user_id"], text, parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="📅 Открыть тренировку", callback_data=f"wk:weekly:{workout['id']}")]
                    ])
                )
                count += 1
            except Exception:
                pass

    mark_workout_sent(workout["id"])
    logging.info(f"Тренировка «{workout['title']}» отправлена {count} подписчикам")


# ========== STARTUP ==========

@dp.message()
async def fallback_handler(message: types.Message, state: FSMContext):
    """Любое нераспознанное сообщение — показываем меню."""
    current_state = await state.get_state()
    if current_state is not None:
        # Если пользователь в FSM — не перебиваем
        return
    uid = message.from_user.id
    add_user(uid, message.from_user.username)
    await message.answer("⬇️ Главное меню:", reply_markup=main_menu(uid))


async def remind_add_workout():
    """
    Напоминание накануне дня тренировки в 12:00 — проверяем очередь.
    Если тренировок нет — предупреждаем админов заранее.
    """
    workout = get_next_unsent_workout()
    if not workout:
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    "⚠️ <b>Напоминание!</b>\n\n"
                    "Завтра день тренировки по расписанию, но очередь пуста.\n"
                    "Добавь тренировку через /admin → «📅 Добавить тренировку месяца».",
                    parse_mode="HTML"
                )
            except Exception:
                pass


async def main():
    hour, minute = SCHEDULE_TIME.split(":")

    # Джобы отправки тренировок по расписанию (вс/вт/чт в 20:00)
    for day in SCHEDULE_DAYS:
        scheduler.add_job(
            send_tomorrow_workout, trigger="cron",
            day_of_week=day, hour=int(hour), minute=int(minute)
        )
        # Напоминание накануне в 12:00 (день - 1, по модулю 7)
        prev_day = (day - 1) % 7
        scheduler.add_job(
            remind_add_workout, trigger="cron",
            day_of_week=prev_day, hour=12, minute=0
        )

    scheduler.add_job(scheduled_cleanup, trigger="cron", day=1, hour=3, minute=0)
    # Еженедельный бэкап базы — каждое воскресенье в 04:00
    scheduler.add_job(backup_database, trigger="cron", day_of_week=6, hour=4, minute=0)
    scheduler.start()
    logging.info("🤖 Бот запущен")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
