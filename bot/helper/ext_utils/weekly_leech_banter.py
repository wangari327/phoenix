#!/usr/bin/env python3
from asyncio import Lock
from html import escape
from time import time

from pyrogram.enums import ParseMode

from bot import DATABASE_URL, LOGGER, bot
from bot.helper.ext_utils.db_handler import DbManger

WEEK_SECONDS = 7 * 24 * 60 * 60
WINDOW_SECONDS = 2 * WEEK_SECONDS
banter_lock = Lock()

DEFAULT_SETTINGS = {
    'target_id': '',
    'message': '',
    'sticker_id': '',
    'enabled': False,
    'started_at': 0,
    'last_sent_at': 0,
    'sent_count': 0,
}


async def get_weekly_leech_banter():
    settings = DEFAULT_SETTINGS.copy()
    if not DATABASE_URL:
        return settings
    stored = await DbManger().get_weekly_leech_banter()
    settings.update({key: stored[key] for key in DEFAULT_SETTINGS if key in stored})
    return settings


async def update_weekly_leech_banter(values):
    if DATABASE_URL:
        await DbManger().update_weekly_leech_banter(values)


async def maybe_send_weekly_leech_banter(chat_id, reply_to_message_id, user_id, tag):
    """Send the configured one-per-week sticker gag after a successful leech."""
    if not DATABASE_URL:
        return

    async with banter_lock:
        settings = await get_weekly_leech_banter()
        try:
            target_id = int(settings['target_id'])
        except (TypeError, ValueError):
            return

        if not settings['enabled'] or user_id != target_id:
            return

        now = time()
        if (settings['sent_count'] >= 2 or
                now >= settings['started_at'] + WINDOW_SECONDS):
            await update_weekly_leech_banter({'enabled': False})
            return
        if settings['last_sent_at'] and now - settings['last_sent_at'] < WEEK_SECONDS:
            return
        if not settings['message'] or not settings['sticker_id']:
            return

        try:
            sticker_message = await bot.send_sticker(
                chat_id=chat_id,
                sticker=settings['sticker_id'],
                reply_to_message_id=reply_to_message_id,
                disable_notification=True)
            await bot.send_message(
                chat_id=chat_id,
                text=f"{tag}\n{escape(settings['message'])}",
                parse_mode=ParseMode.HTML,
                reply_to_message_id=sticker_message.id,
                disable_notification=True)
        except Exception as error:
            LOGGER.error(f'Weekly leech banter could not be sent: {error}')
            return

        sent_count = settings['sent_count'] + 1
        await update_weekly_leech_banter({
            'last_sent_at': now,
            'sent_count': sent_count,
            'enabled': sent_count < 2,
        })
