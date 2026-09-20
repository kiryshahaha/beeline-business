"""Read upstream responses with a hard limit, including decompressed chunked bodies."""

import httpx


async def bounded_request(client, method, url, *, max_bytes=4 * 1024 * 1024, **kwargs):
    async with client.stream(method, url, **kwargs) as response:
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > max_bytes:
                raise ValueError("Upstream response exceeds size limit")
        return httpx.Response(
            response.status_code, content=bytes(content), request=response.request
        )
