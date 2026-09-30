"""Stream revisions preserve seat filtering without resending history for a clock."""
import json
import time

import pytest
from diplomind.config import Config
from diplomind.rooms import RoomManager
from diplomind.session import Session
import diplomind.web as web


@pytest.fixture
def room(monkeypatch):
    rm = RoomManager()
    monkeypatch.setattr(web, 'RM', rm)
    monkeypatch.setattr(rm, 'checkpoint', lambda room: None)
    r = rm.create('stream fixture', 'host', 'FRANCE')
    r.session = Session('FRANCE', cfg=Config(api='mock', api_key=None))
    r.status = 'playing'
    rm._bind(r)
    async def tick(_):
        return None
    monkeypatch.setattr(web.asyncio, 'sleep', tick)
    yield r
    r.session.close()


def payload(frame):
    return json.loads(next(line[6:] for line in frame.splitlines() if line.startswith('data: ')))


@pytest.mark.asyncio
async def test_clock_skips_expensive_state_and_history(room, monkeypatch):
    for i in range(700):
        room.session.bus.post(1, 'ENGLAND', 'broadcast', [], 'x' * 2000, 'S1901M')
    stream = (await web.stream(room.code, room.owner)).body_iterator
    full = await anext(stream)
    assert len(full) > 1_400_000
    monkeypatch.setattr(room.session, 'state', lambda *_: pytest.fail('clock rebuilt full state'))
    room.deadline = time.time() + 100
    clock = await anext(stream)
    assert clock.startswith('event: clock\n') and len(clock) < 300
    assert 98 <= payload(clock)['secs_left'] <= 100
    assert 'channels' not in payload(clock)
    assert await anext(stream) == ': keepalive\n\n'
    assert time.time() - room.seen['FRANCE'] < 1
    await stream.aclose()


@pytest.mark.asyncio
async def test_reconnect_full_state_and_revocation(room):
    stream = (await web.stream(room.code, room.owner)).body_iterator
    assert (await anext(stream)).startswith('data: ')
    await stream.aclose()
    second = (await web.stream(room.code, room.owner)).body_iterator
    assert payload(await anext(second))['human'] == 'FRANCE'
    web.RM.tokens.pop(room.owner)
    with pytest.raises(StopAsyncIteration):
        await anext(second)


@pytest.mark.asyncio
async def test_each_seat_filter_stays_private(room):
    observer = 'test-observer'
    web.RM.tokens[observer] = room.code
    room.session.bus.post(1, 'ENGLAND', 'private', ['FRANCE'], 'PRIVATE_CANARY', 'S1901M')
    room.session.mode = 'ORDERS'
    room.session._horders['FRANCE'] = ['A PAR - BUR']
    owner_stream = (await web.stream(room.code, room.owner)).body_iterator
    observer_stream = (await web.stream(room.code, observer)).body_iterator
    assert 'PRIVATE_CANARY' in await anext(owner_stream)
    public = await anext(observer_stream)
    assert 'PRIVATE_CANARY' not in public and 'A PAR - BUR' not in public
    assert payload(public)['human'] is None
    room.session._changed()
    public = await anext(observer_stream)
    assert public.startswith('data: ') and 'PRIVATE_CANARY' not in public
    await owner_stream.aclose(); await observer_stream.aclose()


@pytest.mark.asyncio
async def test_ai_mutation_settling_and_phase_each_trigger_full_state(room):
    stream = (await web.stream(room.code, room.owner)).body_iterator
    await anext(stream)
    version = room.version
    room.session._done['ENGLAND'] = None
    room.session._changed()
    assert room.version == version + 1
    assert 'ENGLAND' not in payload(await anext(stream))['pending']
    room.session._settling = True
    assert payload(await anext(stream))['settling'] is True
    room.session._ai_orders['ITALY'] = []
    assert (await anext(stream)).startswith('data: ')
    room.session.eng.process()
    assert payload(await anext(stream))['phase'] != 'S1901M'
    room.session._settling = False
    room.session._changed()
    assert payload(await anext(stream))['settling'] is False
    await stream.aclose()


@pytest.mark.asyncio
async def test_members_owner_pause_and_session_replacement_trigger_updates(room):
    stream = (await web.stream(room.code, room.owner)).body_iterator
    await anext(stream)
    room.status = 'paused'; web._bump(room)
    assert payload(await anext(stream))['status'] == 'paused'
    room.owner = 'new-owner'; web._bump(room)
    assert payload(await anext(stream))['owner'] is False
    old = room.session
    room.session = Session('FRANCE', cfg=Config(api='mock', api_key=None)); web.RM._bind(room)
    assert payload(await anext(stream))['turn_id'] != old.turn_id
    old.close()
    await stream.aclose()


@pytest.mark.asyncio
async def test_board_direct_json_matches_encoder_and_retains_headers(room):
    import httpx
    from fastapi.encoders import jsonable_encoder
    from fastapi.responses import JSONResponse
    from diplomind.board import board_state
    expected = JSONResponse(jsonable_encoder(board_state(room.session.eng))).body
    room.session._horders['FRANCE'] = ['A PAR - BUR']
    room.session.bus.post(1, 'ENGLAND', 'private', ['FRANCE'], 'BOARD_PRIVATE_CANARY', 'S1901M')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=web.app), base_url='http://test') as client:
        response = await client.get('/api/board', params={'token': room.owner})
        assert response.status_code == 200 and response.content == expected
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['referrer-policy'] == 'no-referrer'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert 'BOARD_PRIVATE_CANARY' not in response.text and 'A PAR - BUR' not in response.text
        assert (await client.get('/api/board', params={'token': 'invalid'})).status_code == 401
        public = await client.get('/api/board')
        assert public.status_code == 200 and public.json()['phase'] == 'S1901M'


@pytest.mark.asyncio
async def test_presence_changes_use_small_event_and_touch_active_seat(room, monkeypatch):
    room.seats['GERMANY'] = {'name': 'guest', 'kind': 'human', 'token': 'guest'}
    room.seen['GERMANY'] = time.time() - 60
    stream = (await web.stream(room.code, room.owner)).body_iterator
    assert payload(await anext(stream))['dropped'] == ['GERMANY']
    monkeypatch.setattr(room.session, 'state', lambda *_: pytest.fail('presence rebuilt full state'))
    room.seen['GERMANY'] = time.time()
    assert payload(await anext(stream))['dropped'] == []
    room.seen['GERMANY'] = time.time() - 60
    assert payload(await anext(stream))['dropped'] == ['GERMANY']
    assert time.time() - room.seen['FRANCE'] < 1
    await stream.aclose()
