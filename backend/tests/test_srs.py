from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlmodel import create_engine

from app import db as db_module
from app.models import SavedPhrase
from app.services import srs
from app.services.srs import AGAIN, EASY, GOOD, HARD, Card

NOW = datetime(2026, 9, 26, 12, 0, 0)


def days(due):
    return round((due - NOW).total_seconds() / 86400, 3)


def test_a_phrase_remembered_again_and_again_comes_back_after_longer_gaps():
    card, gaps = Card(), []
    for _ in range(5):
        card, due = srs.schedule(card, GOOD, NOW)
        gaps.append(days(due))
    assert gaps[:3] == [1.0, 6.0, 15.0]  # 1 day, 6 days, then times the ease (2.5)
    assert gaps == sorted(gaps) and gaps[-1] > 90 and card.reps == 5 and card.lapses == 0


def test_forgetting_starts_over_comes_back_in_ten_minutes_and_lowers_the_ease():
    card, _ = srs.schedule(srs.schedule(Card(), GOOD, NOW)[0], GOOD, NOW)
    card, due = srs.schedule(card, AGAIN, NOW)
    assert due == NOW + timedelta(minutes=10) and (card.reps, card.interval_days, card.lapses) == (0, 0.0, 1) and card.ease == 2.3
    card, due = srs.schedule(card, GOOD, NOW)  # remembered after the lapse: back to one day
    assert days(due) == 1.0


def test_hard_grows_slowly_and_easy_grows_fast():
    start = Card(reps=2, interval_days=10, ease=2.5)
    hard, h_due = srs.schedule(start, HARD, NOW)
    good, g_due = srs.schedule(start, GOOD, NOW)
    easy, e_due = srs.schedule(start, EASY, NOW)
    assert days(h_due) == 12.0 and days(g_due) == 25.0 and days(e_due) == 32.5
    assert hard.ease < good.ease < easy.ease
    assert srs.schedule(Card(), EASY, NOW)[0].interval_days == 4.0  # a first easy answer skips ahead


def test_the_ease_never_drops_below_the_floor_and_intervals_are_capped_at_a_year():
    card = Card(reps=3, interval_days=20, ease=1.35)
    for _ in range(5):
        card, _ = srs.schedule(card, AGAIN, NOW)
    assert card.ease == srs.MIN_EASE
    huge, due = srs.schedule(Card(reps=9, interval_days=300, ease=3.0), EASY, NOW)
    assert huge.interval_days == srs.MAX_INTERVAL_DAYS and days(due) == 365.0


def test_a_grade_outside_the_four_is_refused():
    for bad in (-1, 4, 9):
        with pytest.raises(ValueError):
            srs.schedule(Card(), bad, NOW)


def test_the_gap_always_grows_at_least_a_day_for_a_remembered_phrase():
    card = Card(reps=2, interval_days=1.0, ease=1.3)
    _, due = srs.schedule(card, GOOD, NOW)
    assert days(due) >= 2.0  # 1 x 1.3 would be less than a day more


# ---- the API ----------------------------------------------------------------------------------


def add(session, text_="break the ice", due_in_days=0.0, **kw):
    p = SavedPhrase(text=text_, translation="打破僵局", user_id=1, due_at=srs.utcnow() + timedelta(days=due_in_days), **kw)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def test_review_lists_only_due_phrases_oldest_first_with_the_counts(client, session):
    add(session, "later", due_in_days=3)
    old = add(session, "oldest", due_in_days=-2)
    add(session, "today", due_in_days=-0.1)
    body = client.get("/api/phrases/review").json()
    assert [c["text"] for c in body["cards"]] == ["oldest", "today"] and body["due_count"] == 2 and body["total"] == 3
    assert body["next_due"] is not None and old.id == body["cards"][0]["id"]
    assert len(client.get("/api/phrases/review", params={"limit": 1}).json()["cards"]) == 1


def test_a_new_phrase_is_due_right_away_and_nothing_is_due_when_there_is_nothing(client, session):
    assert client.get("/api/phrases/review").json() == {"cards": [], "due_count": 0, "total": 0, "next_due": None}
    client.post("/api/phrases", json={"text": "new phrase"})
    assert client.get("/api/phrases/review").json()["due_count"] == 1


def test_reviewing_moves_the_due_date_and_keeps_the_record(client, session):
    p = add(session)
    good = client.post(f"/api/phrases/{p.id}/review", json={"grade": 2}).json()
    assert good["reps"] == 1 and good["interval_days"] == 1.0 and good["due_at"] > srs.utcnow().isoformat()
    assert client.get("/api/phrases/review").json()["due_count"] == 0  # not due any more
    again = client.post(f"/api/phrases/{p.id}/review", json={"grade": 0}).json()
    assert (again["reps"], again["lapses"]) == (0, 1)
    assert client.get("/api/phrases/review").json()["due_count"] == 0  # comes back in ten minutes, not now


def test_review_input_is_validated(client, session):
    p = add(session)
    for bad in (-1, 4):
        assert client.post(f"/api/phrases/{p.id}/review", json={"grade": bad}).status_code == 422
    assert client.post(f"/api/phrases/{p.id}/review", json={}).status_code == 422
    assert client.post("/api/phrases/9999/review", json={"grade": 2}).status_code == 404


def test_old_phrases_get_the_review_columns_and_are_due_at_once(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE savedphrase (id INTEGER PRIMARY KEY, text VARCHAR NOT NULL, created_at DATETIME)"))
        conn.execute(text("INSERT INTO savedphrase (id, text, created_at) VALUES (1, 'old phrase', '2026-09-01 08:00:00.000000')"))
    monkeypatch.setattr(db_module, "engine", engine)
    db_module._add_missing_columns()
    db_module._add_missing_columns()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT due_at, interval_days, ease, reps, lapses FROM savedphrase")).one()
        assert row == ("2026-09-01 08:00:00.000000", 0.0, 2.5, 0, 0)
