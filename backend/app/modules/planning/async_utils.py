"""Bounded external operations; cancel siblings before closing their HTTP pool."""

import asyncio


async def bounded_map(function, items, concurrency: int):
    semaphore = asyncio.Semaphore(concurrency)

    async def run(item):
        async with semaphore:
            return await function(item)

    tasks = [asyncio.create_task(run(item)) for item in items]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
