import os
import base64
from dotenv import load_dotenv
from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

user_messages = {}

START_TEXT = """
🔥 Welcome to SheTexted

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_TEXT)


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
                        "text": "Extract all text from this chat screenshot exactly as written."
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


async def handle_vibe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    loading_msg = await query.message.reply_text("Analyzing conversation...")

    user_id = query.from_user.id
    vibe = query.data
    user_text = user_messages.get(user_id, "")

    prompt = f"""
You are SheTexted.

Return ONLY this exact format with emojis and spacing:

🔥 What her message likely means:
Write a natural explanation in maximum 2 sentences about her vibe, intentions, and emotional tone.
Sound emotionally intelligent and human, not robotic.

💬 Best reply:
"1 natural confident text."

✨ Another option:
"1 natural confident text."

🧠 Why it works:
Write 1-3 short sentences explaining why these replies work emotionally and socially.

📩 Next step:
Write exactly: "Send another chat for analysis ✨"

Rules:
- No other sections
- No bullet points
- No long essays
- Sound modern and natural
- Casual English
- Slightly detailed but easy to read
- Match the requested vibe
- Do not overanalyze too much
- Always end with the Next step section

Message:
{user_text}

Vibe:
{vibe}
"""

    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.7,
        max_output_tokens=220
    )

    await loading_msg.delete()

    await query.message.reply_text(response.output_text)


def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
            handle_message
        )
    )

    app.add_handler(CallbackQueryHandler(handle_vibe))

    print("SheTexted bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()