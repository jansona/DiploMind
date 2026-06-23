"""房间注册: 建房得码+owner、认领座位、token路由、列表、占座防顶替、开局补AI。"""
from diplomind.rooms import RoomManager


def test_create_claim_token():
    m = RoomManager()
    r = m.create("桌1", "Al", "FRANCE")
    assert len(r.code) == 4 and r.seats["FRANCE"]["name"] == "Al"
    assert m.tokens[r.owner] == r.code and r.seat_of(r.owner) == "FRANCE"


def test_join_take_seat_and_route():
    m = RoomManager(); r = m.create("t", "Al", "FRANCE")
    r2, tok = m.join(r.code, "GERMANY", "Bo", None)
    assert r2 is r and r.seat_of(tok) == "GERMANY" and set(r.humans()) == {"FRANCE", "GERMANY"}


def test_seat_not_stolen():
    m = RoomManager(); r = m.create("t", "Al", "FRANCE")
    assert r.claim("FRANCE", "Mallory", "other-token") is False    # owner's seat protected
    assert r.seats["FRANCE"]["name"] == "Al"


def test_start_fills_ai():
    m = RoomManager(); r = m.create("t", "Al", "FRANCE"); m.join(r.code, "GERMANY", "Bo", None)
    r.start()
    assert r.status == "playing" and set(r.session.humans) == {"FRANCE", "GERMANY"} and len(r.session.ai) == 5


def test_list_and_gc():
    m = RoomManager(); a = m.create("a", "x", "FRANCE"); b = m.create("b", "y", "ITALY")
    assert len(m.list()) == 2; b.status = "ended"; m.gc()
    assert b.code not in m.rooms and len(m.list()) == 1


def test_timer_penalty_secs():
    from diplomind.rooms import DEFAULT_SECS, SHORT_SECS
    m = RoomManager(); r = m.create("t", "Al", "FRANCE"); r.start()
    assert r.secs == DEFAULT_SECS == 180 and SHORT_SECS == 30
    r.short.add("FRANCE")                                  # after a timeout, that seat is penalized
    assert (SHORT_SECS if r.short else r.secs) == 30       # next round uses short clock


def test_passcode_gates_join():
    m = RoomManager(); r = m.create("t", "Al", "FRANCE", passcode="1234")
    assert r.summary()["locked"]
    bad, why = m.join(r.code, "GERMANY", "Bo", None, passcode="0000"); assert bad is None and why == "badpass"
    ok, tok = m.join(r.code, "GERMANY", "Bo", None, passcode="1234"); assert ok is r and ok.seat_of(tok) == "GERMANY"
    miss, why = m.join("ZZZZ", None, "x", None); assert miss is None and why == "notfound"


def test_returning_token_skips_passcode():
    m = RoomManager(); r = m.create("t", "Al", "FRANCE", passcode="1234")
    ok, tok = m.join(r.code, "GERMANY", "Bo", None, passcode="1234"); assert ok
    again, _ = m.join(r.code, "GERMANY", "Bo", tok, passcode=""); assert again is r   # known token, no passcode needed


def test_transfer_and_secs_and_dropped():
    import time
    m = RoomManager(); r = m.create("t", "Al", "FRANCE"); m.join(r.code, "GERMANY", "Bo", None); r.start()
    g = r.seats["GERMANY"]["token"]
    assert r.transfer("GERMANY") and r.owner == g                  # ownership handed to Bo
    assert not r.transfer("RUSSIA")                                # RUSSIA is AI, not a human seat
    r.set_secs(90); assert r.secs == 90 and r.timer_on
    r.set_secs(0); assert r.secs == 0 and not r.timer_on           # 0 = no clock
    r.touch("FRANCE"); assert "FRANCE" not in r.dropped()          # just pinged
    assert "GERMANY" in r.dropped()                                # never pinged -> dropped


def test_kick_aiify():
    m = RoomManager(); r = m.create("t", "Al", "FRANCE"); _, gtok = m.join(r.code, "GERMANY", "Bo", None); r.start()
    assert r.session.humans == ["FRANCE", "GERMANY"] and "GERMANY" not in r.session.ai
    assert m.kick(r.code, "GERMANY") and "GERMANY" not in r.seats          # seat freed
    assert r.session.humans == ["FRANCE"] and "GERMANY" in r.session.ai     # AI took over w/ persona
    assert r.session.persona_of["GERMANY"] and m.tokens.get(gtok) is None   # blank-mem agent, token invalidated
    assert not m.kick(r.code, "FRANCE")                                     # can't kick owner
