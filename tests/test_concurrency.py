"""并发闸单测：≤3 国同时打 ollama，余者排队。"""
import asyncio

from diplomind.gateway import Gateway
from diplomind.schemas import Intent


def test_max_three_in_flight():
    gw = Gateway(concurrency=3)
    cur = peak = 0

    async def fake_post(*a, **k):
        nonlocal cur, peak
        cur += 1; peak = max(peak, cur)
        await asyncio.sleep(0.05)
        cur -= 1
        return type("R", (), {"json": lambda self: {"message": {"content": '{"goal":"x"}'}}})()

    gw.aclient.post = fake_post

    async def run():
        await asyncio.gather(*(gw.achat([{"role": "u", "content": "hi"}], Intent) for _ in range(7)))
    asyncio.run(run())
    assert peak <= 3            # 7 国并发, 峰值不超 3
