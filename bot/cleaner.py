import os
import json
import logging
from bot.telegram_poster import delete_telegram_message

logger = logging.getLogger(__name__)

# Identified bad / duplicate / outdated / junk message IDs sent to Telegram
PURGE_MESSAGE_IDS = [94, 95, 96, 97, 98, 99, 101, 104, 105, 107, 108, 109, 110]

def purge_bad_messages(data_file_path: str):
    """
    Deletes bad / junk messages from Telegram channel and removes their entries from history.json.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")

    logger.info("Starting purge of bad / duplicate / junk messages from Telegram...")
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

    # Remove purged keys from history.json
    try:
        if os.path.exists(data_file_path):
            with open(data_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            posted = data.get("posted", {})
            keys_to_remove = [k for k, v in posted.items() if v.get("message_id") in PURGE_MESSAGE_IDS]
            for k in keys_to_remove:
                del posted[k]
            data["posted"] = posted
            with open(data_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Purged {len(keys_to_remove)} bad records from {data_file_path}")
    except Exception as e:
        logger.warning(f"Error purging records from history: {e}")

    logger.info(f"Purge complete. Successfully deleted {deleted_count} messages from Telegram.")
