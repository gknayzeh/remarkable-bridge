---
title: "Test Note — Code Heavy"
tags: [type/reference, topic/python]
---

# Python Async Patterns

## Basic coroutine

```python
import asyncio

async def fetch_data(url: str) -> dict:
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.json()

async def main():
    tasks = [fetch_data(f"https://api.example.com/{i}") for i in range(10)]
    results = await asyncio.gather(*tasks)
    for result in results:
        print(result["status"])
```

Inline code: use `asyncio.run(main())` to start the event loop.

## Error handling

```python
async def safe_fetch(url: str) -> dict | None:
    try:
        return await fetch_data(url)
    except aiohttp.ClientError as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None
```
