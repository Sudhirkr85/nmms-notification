import os
import json
import logging
from bot.telegram_poster import delete_telegram_message

logger = logging.getLogger(__name__)

# Identified bad / duplicate / outdated / junk message IDs sent to Telegram
PURGE_MESSAGE_IDS = list(range(80, 140))

def purge_bad_messages(data_file_path: str):
    """
    Deletes bad / duplicate messages directly from the Telegram channel using the Bot API.
    Critically: KEEPS the event record in history.json (with message_id=None) so the scraper
    permanently remembers the event was already processed and NEVER re-posts it!
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")

    logger.info("Starting purge of bad / duplicate messages from Telegram channel...")
    deleted_count = 0

    if token and channel_id:
        for msg_id in PURGE_MESSAGE_IDS:
            try:
                success = delete_telegram_message(msg_id)
                if success:
                    deleted_count += 1
                    logger.info(f"   -> [PURGED FROM TELEGRAM] Deleted message ID {msg_id}")
            except Exception as e:
                logger.warning(f"Failed deleting message {msg_id}: {e}")

    # Mark purged entries in history.json without deleting them so scrapers never re-post them
    try:
        if os.path.exists(data_file_path):
            with open(data_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            posted = data.get("posted", {})
            updated = False
            for k, v in posted.items():
                if v.get("message_id") in PURGE_MESSAGE_IDS:
                    v["message_id"] = None
                    v["purged_from_channel"] = True
                    updated = True

            if updated:
                with open(data_file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                logger.info(f"Updated purged records in {data_file_path}")
    except Exception as e:
        logger.warning(f"Error updating records in history: {e}")

    logger.info(f"Purge complete. Successfully deleted {deleted_count} messages from Telegram channel.")
