import os
import base64
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from openai import OpenAI
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
)
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
user_followup_mode = {}

STATS_FILE = "stats.json"
ACCESS_FILE = "access.json"
USAGE_FILE = "usage.json"
MEMORY_FILE = "memory.json"

ADMIN_ID = 669799237

FREE_DAILY_LIMIT = 3
WEEKLY_STARS = 200
MONTHLY_STARS = 500

START_TEXT = """
💬 Welcome to SheTexted

Send:
• screenshot
• copied chat
• dating app convo

Get:
• best reply
• emotional analysis
• better texting energy
• what she actually means
• help when you overthink
• follow-up advice about your situation


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


def load_usage():
    return load_json(USAGE_FILE, {})


def save_usage(usage):
    save_json(USAGE_FILE, usage)


def load_memory():
    return load_json(MEMORY_FILE, {})


def save_memory(memory):
    save_json(MEMORY_FILE, memory)


def get_memory_summary(user_id):
    memory = load_memory()
    uid = str(user_id)
    return memory.get(uid, {}).get("summary", "")


def save_memory_summary(user_id, summary):
    memory = load_memory()
    uid = str(user_id)

    memory[uid] = {
        "summary": summary.strip()[:1200],
        "updated_at": datetime.now().isoformat()
    }

    save_memory(memory)


async def update_user_memory(user_id, latest_chat="", latest_question="", latest_answer=""):
    """
    Keeps a short relationship/situation summary for continuity.
    This makes follow-up answers feel like they remember the user's situation
    without storing the full chat forever.
    """
    previous_summary = get_memory_summary(user_id)

    prompt = f"""
Update the user's dating situation memory.

Write a short private summary that will help answer future questions.
Keep only useful context:
- who the user is talking to, if known
- relationship status / emotional context
- important recent events
- user's worries or goals
- girl's apparent energy
- what advice was already given

Rules:
- Maximum 6 concise bullet points
- Do not invent facts
- Do not include irrelevant details
- Keep it neutral and useful
- If there is no useful context, return the previous summary

Previous memory:
{previous_summary}

Latest chat/conversation:
{latest_chat}

Latest user question:
{latest_question}

Latest assistant answer:
{latest_answer}
"""

    try:
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
            temperature=0.3,
            max_output_tokens=180
        )

        new_summary = response.output_text.strip()

        if new_summary:
            save_memory_summary(user_id, new_summary)

    except Exception:
        # Memory should never break the main bot experience.
        pass


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def reset_daily_stats(stats):
    today = today_str()

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


def has_active_pro(user_id):
    access = load_access()
    uid = str(user_id)

    if uid not in access:
        return False

    try:
        expires_at = datetime.fromisoformat(access[uid]["expires_at"])
        return datetime.now() < expires_at
    except:
        return False


def extend_access(user_id, days, plan):
    access = load_access()
    uid = str(user_id)

    now = datetime.now()

    if uid in access:
        try:
            current_expiry = datetime.fromisoformat(access[uid]["expires_at"])
            start_date = max(now, current_expiry)
        except:
            start_date = now
    else:
        start_date = now

    new_expiry = start_date + timedelta(days=days)

    access[uid] = {
        "plan": plan,
        "expires_at": new_expiry.isoformat()
    }

    save_access(access)


def get_free_usage(user_id):
    usage = load_usage()
    uid = str(user_id)
    today = today_str()

    if uid not in usage or usage[uid].get("date") != today:
        usage[uid] = {"date": today, "count": 0}
        save_usage(usage)

    return usage[uid]["count"]


def increment_free_usage(user_id):
    usage = load_usage()
    uid = str(user_id)
    today = today_str()

    if uid not in usage or usage[uid].get("date") != today:
        usage[uid] = {"date": today, "count": 0}

    usage[uid]["count"] += 1
    save_usage(usage)


def can_use_bot(user_id):
    if has_active_pro(user_id):
        return True

    used = get_free_usage(user_id)
    return used < FREE_DAILY_LIMIT


def get_access_text(user_id):
    if has_active_pro(user_id):
        access = load_access()
        uid = str(user_id)
        plan = access[uid]["plan"]
        expires_at = datetime.fromisoformat(access[uid]["expires_at"])
        days_left = max(0, (expires_at - datetime.now()).days)
        return f"Pro {plan.title()} · {days_left} days left"

    used = get_free_usage(user_id)
    remaining = max(0, FREE_DAILY_LIMIT - used)
    return f"Free · {remaining}/{FREE_DAILY_LIMIT} analyses left today"


def after_answer_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔁 More replies", callback_data="regenerate_options")],
        [InlineKeyboardButton("❤️ Ask About Your Situation", callback_data="ask_about_chat")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def show_paywall(message, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Pro Weekly — $3.99/week", callback_data="buy_weekly")],
        [InlineKeyboardButton("⭐ Pro Monthly — $9.99/month", callback_data="buy_monthly")],
    ]

    text = """
You’ve used your 3 free replies today 🖤

Unlock SheTexted Pro:

• Unlimited reply generation
• Screenshot & chat analysis
• Better texting energy
• Smarter, smoother replies
• Dating app conversation help

⭐ Most users choose Monthly
"""

    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


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
    active_pro_users = 0

    for uid in access:
        try:
            expires_at = datetime.fromisoformat(access[uid]["expires_at"])
            if datetime.now() < expires_at:
                active_pro_users += 1
        except:
            pass

    text = (
        f"📊 SheTexted Stats\n\n"
        f"👥 Total users: {len(stats_data['users'])}\n"
        f"🆕 New today: {stats_data['new_users_today']}\n"
        f"💬 Messages today: {stats_data['messages_today']}\n"
        f"📩 Total messages: {stats_data['total_messages']}\n"
        f"💎 Active Pro users: {active_pro_users}"
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

    if user_followup_mode.get(user_id):
        if not can_use_bot(user_id):
            await show_paywall(update.message, context)
            return

        if not update.message.text:
            await update.message.reply_text("Send your question in text 🧠")
            return

        original_chat = user_messages.get(user_id, "")
        followup_question = update.message.text

        if not original_chat:
            user_followup_mode[user_id] = False
            await update.message.reply_text("Send me a chat first 🖤")
            return

        loading_msg = await update.message.reply_text("Thinking...")

        memory_summary = get_memory_summary(user_id)
        output = await generate_followup_answer(original_chat, followup_question, memory_summary)

        user_followup_mode[user_id] = False

        if not has_active_pro(user_id):
            increment_free_usage(user_id)

        await update_user_memory(
            user_id,
            latest_chat=original_chat,
            latest_question=followup_question,
            latest_answer=output
        )

        await loading_msg.delete()
        await update.message.reply_text(output)
        return

    if not can_use_bot(user_id):
        await show_paywall(update.message, context)
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

    await update_user_memory(user_id, latest_chat=text)

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

    remaining = max(0, FREE_DAILY_LIMIT - get_free_usage(user_id))

    if has_active_pro(user_id):
        usage_text = "Pro access active 💎"
    else:
        usage_text = f"Free analyses left today: {remaining}/{FREE_DAILY_LIMIT}"

    await update.message.reply_text(
        f"What vibe do you want?\n\n{usage_text}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def generate_main_answer(user_text, vibe):
    prompt = f"""
You are SheTexted — a socially intelligent AI texting assistant for modern dating conversations.

Your personality:
- emotionally sharp
- modern dating-aware
- confident but not cringe
- direct but not rude
- playful when appropriate
- human, casual, and copy-paste ready
- never robotic
- never overly therapeutic
- never manipulative
- never pickup-artist style

The user selected this vibe: {vibe}

Main goal:
Make the replies sound like a real attractive person texting naturally — not like an AI assistant, dating coach, therapist, or polished writer.

Return ONLY this exact format:

🖤 Best Reply:
Write the strongest reply the user should send.

✨ One More:
Write 1 alternative reply with noticeably different energy.

🧠 Why it works:
Write ONLY 1 very short sentence.
Maximum 8 words.
Start with a capital letter.

📩 Next step:
Send another chat for analysis ✨

Reply style rules:
- ONLY give 2 reply options total
- NEVER write "Bolder Option"
- NEVER write "Chill Option"
- Best Reply and One More must feel clearly different
- Best Reply should match the selected vibe: {vibe}
- One More should use a different energy, like softer, colder, funnier, more teasing, or more chill
- Keep replies short, natural, and easy to copy
- Prefer real texting language over perfect grammar
- Use natural texting capitalization
- Most replies should start with a capital letter
- Lowercase can be used occasionally for vibe, but not constantly
- Emojis are allowed but do not overuse them
- Avoid long polished sentences
- Avoid overly articulate phrasing
- Avoid "tell me something that..." style unless it sounds very natural
- Avoid corporate, therapist-like, or dating-coach language
- Avoid cringe pickup lines
- Avoid neediness
- Avoid overexplaining
- If her energy is low, stay calm and don't chase
- If she is warm/flirty, match it smoothly
- If the chat is dry, create an easy hook without trying too hard
- Keep the full output clean and fast to read
- Always end with the Next step section exactly as shown
- Do not try to make every reply clever or impressive
- Sometimes the best reply is very simple
- Prefer natural texting over perfect flirting
- Do not invent meaning when the chat is too short or unclear
- For random words, typos, or low-context messages, keep the analysis simple and honest
- Analysis should feel like a friend giving quick advice, not a therapist or coach
- Avoid generic compliment responses
- Avoid cheesy flirting templates
- Prefer witty, playful, modern texting energy
- Replies should feel socially sharp and screenshot-worthy  
- Do not sound like a dating app chatbot
- Avoid basic replies like "you made my day", "you are not so bad yourself", "you are making me blush", or "thanks"
- For compliments, respond with playful confidence, teasing, or light tension
- Do not overuse winky face emojis

Chat:
{user_text}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=1.0,
        max_output_tokens=260
    )

    return response.output_text


async def generate_more_options(user_text):
    prompt = f"""
You are SheTexted — a modern AI texting assistant.

Give exactly 2 fresh reply options for this chat.

Return ONLY this exact format:

🖤 Best Reply:
Write 1 short strong reply.

✨ One More:
Write 1 short alternative reply with clearly different energy.

Rules:
- No explanations
- No bullet points
- Usually 1 sentence per reply
- Only use 2 short sentences if the chat is emotional
- Replies must be copy-paste ready
- Make both options feel noticeably different
- Sound like a real person texting, not an AI
- Casual modern English
- Prefer natural texting over perfect writing
- Use natural texting capitalization
- Most replies should start with a capital letter
- Lowercase can be used occasionally for vibe, but not constantly
- Emojis are allowed but do not overuse them
- Avoid cringe
- Avoid sounding needy
- Avoid sounding aggressive
- Avoid long polished sentences
- Avoid therapist-like or dating-coach language
- If her energy is low, don't chase too hard
- If she is warm/flirty, match it smoothly

Chat:
{user_text}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.95,
        max_output_tokens=220
    )

    return response.output_text


async def generate_followup_answer(user_text, user_question, memory_summary=""):
    prompt = f"""
You are SheTexted — a socially intelligent AI for modern dating situations.

The user already sent a dating/chat conversation.
Now they are asking a follow-up question about that same situation.

You have access to a short memory summary from previous interactions.
Use it only when it clearly helps. Do not mention "memory" to the user.

Previous situation memory:
{memory_summary}

Current conversation:
{user_text}

User's follow-up question:
{user_question}

Your job:
Answer like a smart, emotionally aware friend who understands texting, dating tension, mixed signals, and overthinking.

Automatically choose the best mode:

1) ANALYSIS MODE
Use when the user asks what she meant, whether she is interested, why she acted a certain way, or what is happening.
Give a realistic interpretation + what it means for the situation.

2) REPLY MODE
Use when the user asks what to answer, how to continue, or wants message options.
Give copy-paste ready replies. If writing actual messages, use this format:
🖤 Best Reply:
...
✨ One More:
...

3) OVERTHINKING CALMING MODE
Use when the user is anxious, wants to delete a message, worries they ruined everything, says she has not replied, thinks she has someone else, or asks for reassurance.
First calm them down, then explain the situation, then give the safest next step.
Help them avoid impulsive actions.
Do not create false certainty.

Rules:
- Keep the answer short and useful
- Usually 3-7 natural sentences
- Be honest if the situation is unclear
- If she seems interested, say it clearly
- If her energy seems low, say it calmly
- Do not overanalyze tiny details
- Do not encourage manipulation or pickup-artist tactics
- Do not sound like a therapist
- Do not sound like a corporate AI assistant
- Sound human, casual, supportive, and direct
- Avoid long paragraphs
- Avoid generic motivational advice
- If the user asks for replies, keep them natural, short, and copy-paste ready
- If the user is overthinking, prioritize emotional steadiness over strategy
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.85,
        max_output_tokens=420
    )

    return response.output_text

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    track_user(user_id)

    if query.data == "buy_weekly":
        await send_invoice(query, context, "weekly")
        return

    if query.data == "buy_monthly":
        await send_invoice(query, context, "monthly")
        return

    if not can_use_bot(user_id):
        await show_paywall(query.message, context)
        return

    user_text = user_messages.get(user_id, "")

    if not user_text:
        await query.message.reply_text("Send me a chat first 🖤")
        return

    if query.data == "ask_about_chat":
        user_followup_mode[user_id] = True
        await query.message.reply_text(
            "Ask anything about your situation ❤️\n\n"
            "You can ask things like:\n\n"
            "• “What does she really mean?”\n"
            "• “Did I mess this up?”\n"
            "• “Should I text her again?”\n"
            "• “She stopped replying”\n"
            "• “I want to delete my message”\n"
            "• “Does she still like me?”"
        )
        return

    if query.data == "regenerate_options":
        loading_msg = await query.message.reply_text("Generating 2 more options...")
        output = await generate_more_options(user_text)

        if not has_active_pro(user_id):
            increment_free_usage(user_id)

        await loading_msg.delete()
        await query.message.reply_text(
            output,
            reply_markup=after_answer_keyboard()
        )
        return

    loading_msg = await query.message.reply_text("Analyzing conversation...")

    vibe = query.data
    output = await generate_main_answer(user_text, vibe)

    if not has_active_pro(user_id):
        increment_free_usage(user_id)

    await loading_msg.delete()
    await query.message.reply_text(
        output,
        reply_markup=after_answer_keyboard()
    )


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