import asyncio

import httpx
import pytest
from workforce_core.verify import CHECKERS


def check(key, fields, handler):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await CHECKERS[key](http, fields)

    return asyncio.run(go())


def test_cloudflare_key_check():
    seen = []

    def ok(req):
        seen.append(req)
        return httpx.Response(200, json={"success": True, "result": []})

    acc = "0123456789abcdef0123456789abcdef"
    assert check("cloudflare_ai", {"account_id": f" {acc} ", "api_token": "t"}, ok) == (
        acc,
        "Cloudflare account ••cdef",
    )
    assert seen[0].url.path == f"/client/v4/accounts/{acc}/ai/models/search"
    assert seen[0].headers["authorization"] == "Bearer t"

    with pytest.raises(ValueError, match="too short"):
        check("cloudflare_ai", {"account_id": "abc", "api_token": "t"}, ok)
    with pytest.raises(ValueError, match="didn't accept"):
        check(
            "cloudflare_ai",
            {"account_id": acc, "api_token": "bad"},
            lambda r: httpx.Response(403, json={"success": False}),
        )
