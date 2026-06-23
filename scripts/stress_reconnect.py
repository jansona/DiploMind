"""掉线/重连风暴压测: K房×2人, 反复 SSE 连断 + token 重连 + 状态轮询并发, 验座位稳/无500/延迟. 起服:8775 (ollama免费)."""
import asyncio, time, statistics, httpx

B = "http://localhost:8775"; ROOMS = 6; CYCLES = 40
lat = []; errs = 0


async def storm(c, code, tok, seat):
    global errs
    for _ in range(CYCLES):
        t = time.time()
        try:
            j = (await c.post("/api/room/join", json={"code": code, "power": seat, "name": "x", "token": tok})).json()  # token rejoin
            if j.get("seat") != seat: errs += 1
            async with c.stream("GET", f"/api/stream/{code}?token={tok}") as s:   # open SSE
                async for _ in s.aiter_lines(): break                              # one frame then drop
            if (await c.get(f"/api/state?token={tok}")).json().get("human") != seat: errs += 1
        except Exception: errs += 1
        lat.append(time.time() - t)


async def main():
    async with httpx.AsyncClient(base_url=B, timeout=15) as c:
        rooms = []
        for i in range(ROOMS):
            d = (await c.post("/api/room/create", json={"power": "FRANCE", "name": f"r{i}"})).json()
            j = (await c.post("/api/room/join", json={"code": d["code"], "power": "GERMANY"})).json()
            await c.post("/api/room/start", json={"token": d["token"]})
            rooms += [(d["code"], d["token"], "FRANCE"), (d["code"], j["token"], "GERMANY")]
        t0 = time.time()
        await asyncio.gather(*(storm(c, *r) for r in rooms))                       # all seats storm at once
        n = len(rooms) * CYCLES
        print(f"房{ROOMS} 座{len(rooms)} 操作{n} 用时{time.time()-t0:.1f}s 错误{errs} "
              f"p50={statistics.median(lat)*1000:.0f}ms p95={sorted(lat)[int(len(lat)*.95)]*1000:.0f}ms")
        print("rooms still listed:", len((await c.get("/api/rooms")).json()["rooms"]))
        print("ALL PASS" if errs == 0 else "FAIL")

asyncio.run(main())
