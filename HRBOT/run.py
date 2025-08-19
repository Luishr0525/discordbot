import asyncio
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

from hrbot.bot import create_bot


async def main() -> None:
    env_path = Path.cwd() / '.env'
    load_dotenv(dotenv_path=env_path, override=True)
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO),
                        format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')

    bot = create_bot()
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise RuntimeError('環境変数 DISCORD_TOKEN が設定されていません (.env を確認)')
    await bot.start(token)


if __name__ == '__main__':
    asyncio.run(main())

