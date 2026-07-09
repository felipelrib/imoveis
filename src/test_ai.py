import asyncio
import logging

from adapters.ai.client import create_ai_client

logging.basicConfig(level=logging.INFO)


async def main():
    client = create_ai_client()
    try:
        print("Testing visuals")
        v = await client.analyze_visuals(["test.jpg"], "prompt")
        print(v)
        print("Testing text")
        t = await client.analyze_text("text", "prompt")
        print(t)
    except Exception:
        logging.exception("Error")
    finally:
        await client.close()


asyncio.run(main())
