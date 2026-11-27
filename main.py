import asyncio
import glob
import os
import tempfile

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, Message
from google import genai
from google.genai import types
import yt_dlp

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing!")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable is missing!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
ai_client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_INSTRUCTION = (
    "Sen universal AI yordamchisan. Foydalanuvchi savollariga aniq, tushunarli va "
    "foydali javob ber. Matematika va hisob-kitoblarni bosqichma-bosqich, xatosiz "
    "yechib tushuntir. Agar foydalanuvchi rasm yuborsa, rasmdagi matn, masalalar, "
    "ob'ektlar yoki holatni batafsil tahlil qil. Javoblarni foydalanuvchi qaysi tilda "
    "yozsa, o'sha tilda (ko'pincha o'zbek tilida) ber."
)


async def ask_gemini(prompt: str, image_bytes: bytes | None = None, mime_type: str = "image/jpeg") -> str:
    contents = []
    if image_bytes:
        contents.append(types.Part.from_bytes(data=image_bytes, mime_type=mime_type))
    contents.append(prompt)

    response = await asyncio.to_thread(
        ai_client.models.generate_content,
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.4,
        ),
    )
    return (response.text or "Javob qaytarib bo‘lmadi.").strip()


def download_song_mp3(query: str, out_dir: str) -> tuple[str, str]:
    ydl_opts = {
        "format": "bestaudio/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }
    search_query = query if query.startswith("http") else f"ytsearch1:{query}"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(search_query, download=True)
        if "entries" in info and info["entries"]:
            info = info["entries"][0]
        title = info.get("title") or query

    mp3_files = glob.glob(os.path.join(out_dir, "*.mp3"))
    if not mp3_files:
        raise FileNotFoundError("MP3 fayl yaratilmadi.")
    return mp3_files[0], title


async def send_long_text(message: Message, text: str) -> None:
    max_len = 4000
    for i in range(0, len(text), max_len):
        await message.answer(text[i : i + max_len])


@dp.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Salom! Men universal AI yordamchi botman.\n\n"
        "Nimalar qila olaman:\n"
        "• **Savol-javob va hisob-kitob:** har qanday savol, masala yoki hisob-kitob yozing.\n"
        "• **Rasm tahlili:** rasm yuboring (izoh bilan yoki izohsiz) — tahlil qilib beraman.\n"
        "• **Musiqa:** <code>/music qo'shiq nomi</code> deb yozing — MP3 topib yuboraman.",
        parse_mode="HTML",
    )


@dp.message(F.text.startswith("/music"))
async def cmd_music(message: Message) -> None:
    query = message.text.replace("/music", "", 1).strip()
    if not query:
        await message.answer("Qo‘shiq nomini yozing. Masalan:\n<code>/music Konsta O‘zbekiston</code>", parse_mode="HTML")
        return

    status_msg = await message.answer(f"🔎 <b>{query}</b> qidirilmoqda...", parse_mode="HTML")
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            mp3_path, title = await asyncio.to_thread(download_song_mp3, query, tmp_dir)
            size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
            if size_mb > 48:
                await status_msg.edit_text("Fayl hajmi Telegram limitidan katta bo‘lib ketdi (48 MB+).")
                return
            audio_file = FSInputFile(mp3_path, filename=f"{title[:60]}.mp3")
            await message.answer_audio(audio=audio_file, title=title[:100])
            await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"Musiqa yuklashda xatolik yuz berdi: {e}")


@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    status_msg = await message.answer("🖼 Rasm tahlil qilinmoqda...")
    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        buffer = await bot.download_file(file.file_path)
        image_bytes = buffer.read()
        prompt = message.caption.strip() if message.caption else (
            "Ushbu rasmda nima borligini tushuntir. Agar masala yoki matn bo'lsa, yechimini batafsil yoz."
        )
        answer = await ask_gemini(prompt=prompt, image_bytes=image_bytes, mime_type="image/jpeg")
        await status_msg.delete()
        await send_long_text(message, answer)
    except Exception as e:
        await status_msg.edit_text(f"Rasmni tahlil qilishda xatolik: {e}")


@dp.message(F.text)
async def handle_text(message: Message) -> None:
    text = message.text.strip()
    if not text:
        return

    status_msg = await message.answer("💭 O‘ylayapman...")
    try:
        answer = await ask_gemini(prompt=text)
        await status_msg.delete()
        await send_long_text(message, answer)
    except Exception as e:
        await status_msg.edit_text(f"Xatolik yuz berdi: {e}")


async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
                          
