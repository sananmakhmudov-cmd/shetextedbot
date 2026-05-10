import os
import base64
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    PreCheckoutQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

user_messages = {}

STATS_FILE = "stats.json"
ACCESS_FILE = "access.json"

ADMIN_ID = 669799237

TRIAL_DAYS = 3
WEEKLY_STARS = 200
MONTHLY_STARS = 500

START_TEXT = """
💬 Welcome to SheTexted

Send a screenshot or copy your chat.

I’ll analyze:
• what she actually means
• best reply for your goal
• emotional tone
• flirting signals
• mixed energy

Works for:
• texting
• dating apps
• ex situations
• ghosting
• flirting

👇 Send your chat
"""


def load_json(file_name, default):
    try:
        with open(file_name, "r") as f:
            return json.load(f)
    except:
        return default


def save_json(file_name, data):
    with open(file_name, "w") as f:
        json.dump(data, f)


def load_stats():
    return load_json(STATS_FILE, {
        "users": [],
        "messages_today": 0,
        "new_users_today": 0,
        "total_messages": 0,
        "last_reset": ""
    })


def save_stats(stats):
    save_json(STATS_FILE, stats)


def load_access():
    return load_json(ACCESS_FILE, {})


def save_access(access):
    save_json(ACCESS_FILE, access)


def reset_daily_stats(stats):
    today = datetime.now().strftime("%Y-%m-%d")

    if stats.get("last_reset") != today:
        stats["messages_today"] = 0
        stats["new_users_today"] = 0
        stats["last_reset"] = today

    if "total_messages" not in stats:
        stats["total_messages"] = 0

    return stats


def track_user(user_id):
    stats = load_stats()
    stats = reset_daily_stats(stats)

    stats["messages_today"] += 1
    stats["total_messages"] += 1

    if user_id not in stats["users"]:
        stats["users"].append(user_id)
        stats["new_users_today"] += 1

    save_stats(stats)


def start_trial_if_needed(user_id):
    access = load_access()
    uid = str(user_id)

    if uid not in access:
        expires_at = datetime.now() + timedelta(days=TRIAL_DAYS)
        access[uid] = {
            "plan": "trial",
            "expires_at": expires_at.isoformat()
        }
        save_access(access)


def has_active_access(user_id):
    access = load_access()
    uid = str(user_id)

    if uid not in access:
        return False

    expires_at = datetime.fromisoformat(access[uid]["expires_at"])
    return datetime.now() < expires_at


def extend_access(user_id, days, plan):
    access = load_access()
    uid = str(user_id)

    now = datetime.now()

    if uid in access:
        current_expiry = datetime.fromisoformat(access[uid]["expires_at"])
        start_date = max(now, current_expiry)
    else:
        start_date = now

    new_expiry = start_date + timedelta(days=days)

    access[uid] = {
        "plan": plan,
        "expires_at": new_expiry.isoformat()
    }

    save_access(access)


def get_access_text(user_id):
    access = load_access()
    uid = str(user_id)

    if uid not in access:
        return "No active plan"

    plan = access[uid]["plan"]
    expires_at = datetime.fromisoformat(access[uid]["expires_at"])
    days_left = max(0, (expires_at - datetime.now()).days)

    return f"{plan.title()} · {days_left} days left"


async def show_paywall(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Pro Weekly — $3.99/week", callback_data="buy_weekly")],
        [InlineKeyboardButton("⭐ Pro Monthly — $9.99/month", callback_data="buy_monthly")],
    ]

    text = """
Your free access has ended 🖤

Unlock SheTexted Pro:

• Instant AI replies
• Chat screenshot analysis
• Flirty, playful, confident & chill replies
• Deep message meaning
• Dating app support

⭐ Monthly is the best value.
"""

    if hasattr(update_or_query, "message") and update_or_query.message:
        await update_or_query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update_or_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def send_invoice(query, context: ContextTypes.DEFAULT_TYPE, plan):
    if plan == "weekly":
        title = "SheTexted Pro Weekly"
        description = "7 days of SheTexted Pro access"
        payload = "weekly_pro"
        stars = WEEKLY_STARS
    else:
        title = "SheTexted Pro Monthly"
        description = "30 days of SheTexted Pro access"
        payload = "monthly_pro"
        stars = MONTHLY_STARS

    await context.bot.send_invoice(
        chat_id=query.message.chat_id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(title, stars)],
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    track_user(user_id)
    start_trial_if_needed(user_id)

    access_text = get_access_text(user_id)

    await update.message.reply_text(
        START_TEXT + f"\n\n✅ Your access: {access_text}"
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id != ADMIN_ID:
        return

    stats_data = load_stats()
    stats_data = reset_daily_stats(stats_data)
    save_stats(stats_data)

    access = load_access()
    active_users = 0

    for uid in access:
        try:
            expires_at = datetime.fromisoformat(access[uid]["expires_at"])
            if datetime.now() < expires_at:
                active_users += 1
        except:
            pass

    text = (
        f"📊 SheTexted Stats\n\n"
        f"👥 Total users: {len(stats_data['users'])}\n"
        f"🆕 New today: {stats_data['new_users_today']}\n"
        f"💬 Messages today: {stats_data['messages_today']}\n"
        f"📩 Total messages: {stats_data['total_messages']}\n"
        f"💎 Active access users: {active_users}"
    )

    await update.message.reply_text(text)


async def extract_text_from_image(photo_file):
    image_bytes = await photo_file.download_as_bytearray()
    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Extract all text from this chat screenshot exactly as written. Preserve names, emojis, timestamps, and message order if visible."
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{base64_image}",
                    },
                ],
            }
        ],
    )

    return response.output_text


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    track_user(user_id)
    start_trial_if_needed(user_id)

    if not has_active_access(user_id):
        await show_paywall(update, context)
        return

    text = ""

    if update.message.text:
        text = update.message.text

    elif update.message.photo:
        loading = await update.message.reply_text("Reading screenshot...")

        photo = update.message.photo[-1]
        photo_file = await photo.get_file()

        text = await extract_text_from_image(photo_file)

        await loading.delete()

    user_messages[user_id] = text

    keyboard = [
        [
            InlineKeyboardButton("Flirty 🖤", callback_data="flirty"),
            InlineKeyboardButton("Playful 😏", callback_data="playful"),
        ],
        [
            InlineKeyboardButton("Confident 🔥", callback_data="confident"),
            InlineKeyboardButton("Chill 🙂", callback_data="chill"),
        ]
    ]

    await update.message.reply_text(
        "What vibe do you want?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    track_user(user_id)
    start_trial_if_needed(user_id)

    if query.data == "buy_weekly":
        await send_invoice(query, context, "weekly")
        return

    if query.data == "buy_monthly":
        await send_invoice(query, context, "monthly")
        return

    if not has_active_access(user_id):
        await show_paywall(query.message, context)
        return

    loading_msg = await query.message.reply_text("Analyzing conversation...")

    vibe = query.data
    user_text = user_messages.get(user_id, "")

    prompt = f"""
You are SheTexted — a socially intelligent AI texting assistant.

Your personality:
- emotionally sharp
- modern dating-aware
- confident but not cringe
- direct but not rude
- playful when appropriate
- never robotic
- never overly therapeutic
- never manipulative
- never pickup-artist style

Your job:
Analyze the emotional dynamics of the chat, the hidden intention, attraction level, tension, effort, and the best social move.
Sound like a smart friend who understands texting, dating apps, flirting, mixed signals, ghosting, exes, and situationships.

The user selected this vibe: {vibe}

Return ONLY this exact format with emojis and spacing:

🔥 What her message likely means:
Write 2 natural sentences. Explain her vibe, emotional tone, interest level, and social dynamic. Be specific to the message. Avoid generic phrases like "she seems interested" unless the chat clearly shows that.

💬 Best reply:
"Write 1 short natural text the user can send. Make it confident, human, and matched to the selected vibe."

✨ Another option:
"Write 1 different short natural text. It should feel fresh, not just a reworded version."

🧠 Why it works:
Write 2 short sentences explaining why these replies work emotionally and socially. Mention confidence, pressure, curiosity, tension, playfulness, or clarity only when relevant.

📩 Next step:
Send another chat for analysis ✨

Rules:
- No other sections
- No bullet points
- No long essays
- Casual English
- Sound like a real person, not ChatGPT
- Do not overhype
- Do not say "high value"
- Do not be needy
- Do not be aggressive
- Do not make the user look desperate
- If her energy is low, do not pretend it is high
- If she is dry, call it out calmly
- If she is warm, make the reply smooth and confident
- If context is unclear, say it naturally without overexplaining
- Always give replies that can actually be copied and sent
- Always end with the Next step section exactly as shown

Chat:
{user_text}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.85,
        max_output_tokens=260
    )

    await loading_msg.delete()
    await query.message.reply_text(response.output_text)


async def precheckout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)


async def successful_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    payment = update.message.successful_payment

    if payment.invoice_payload == "weekly_pro":
        extend_access(user_id, 7, "weekly")
        await update.message.reply_text(
            "✅ Payment received!\n\nSheTexted Pro Weekly is active for 7 days 🖤"
        )

    elif payment.invoice_payload == "monthly_pro":
        extend_access(user_id, 30, "monthly")
        await update.message.reply_text(
            "✅ Payment received!\n\nSheTexted Pro Monthly is active for 30 days 🖤"
        )


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))

    app.add_handler(PreCheckoutQueryHandler(precheckout_callback))

    app.add_handler(
        MessageHandler(
            filters.SUCCESSFUL_PAYMENT,
            successful_payment_callback
        )
    )

    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
            handle_message
        )
    )

    app.add_handler(CallbackQueryHandler(handle_callback))

    print("SheTexted bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()