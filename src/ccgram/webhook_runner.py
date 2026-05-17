"""Webhook runner wrapper for python-telegram-bot.

Provides a fallback mechanism: attempts to start the webhook, and if port binding
fails, falls back to polling.
"""

import structlog
from telegram.ext import Application

logger = structlog.get_logger()

def run_with_fallback(application: Application, config: object) -> None:
    """Run the application with Webhook if configured, falling back to Polling."""
    webhook_url = getattr(config, "webhook_url", None)
    
    if not webhook_url:
        logger.info("Polling mode active (no WEBHOOK_URL defined).")
        application.run_polling(
            allowed_updates=["message", "callback_query"],
            stop_signals=None,
        )
        return

    logger.info(
        "Webhook registration triggered", 
        url=webhook_url, 
        listen=config.webhook_listen, 
        port=config.webhook_port
    )

    try:
        application.run_webhook(
            listen=config.webhook_listen,
            port=config.webhook_port,
            webhook_url=webhook_url,
            secret_token=getattr(config, "webhook_secret_token", None) or None,
            allowed_updates=["message", "callback_query"],
            stop_signals=None,
        )
        logger.info("Webhook stopped cleanly.")
    except Exception as e:  # noqa: BLE001
        logger.error("Webhook failed (%s): %s", type(e).__name__, e)
        logger.info("Falling back to polling mode")
        
        # python-telegram-bot closes the event loop on run_webhook failure.
        # We must recreate the loop before falling back.
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        application.run_polling(
            allowed_updates=["message", "callback_query"],
            stop_signals=None,
        )
