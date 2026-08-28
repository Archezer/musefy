import asyncio
import os
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from app.domain.models import Track
from app.ingestion.audio import AudioIngestionService, SUPPORTED_AUDIO_EXTENSIONS
from app.storage.memory import InMemoryMusicStore


INBOX_DIR = Path("data/inbox")

dispatcher = Dispatcher()
store = InMemoryMusicStore()
ingestion_service = AudioIngestionService(store)


@dispatcher.message(CommandStart())
async def handle_start(message: Message) -> None:
    await message.answer(
        "Send an audio file and I will analyze it locally."
    )