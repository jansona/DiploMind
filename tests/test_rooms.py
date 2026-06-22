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
