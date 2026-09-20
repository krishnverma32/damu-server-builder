"""Tests for SQLite persistence and Repository layer."""
from __future__ import annotations

import asyncio
import pathlib
from services.database import Database
from services.repositories import (
    AutoModRepository,
    BuildRepository,
    GuildRepository,
    ModerationRepository,
    SnapshotRepository,
    TicketRepository,
)


def _init_test_db(tmp_path: pathlib.Path) -> Database:
    db_file = tmp_path / "test_damu.sqlite"
    return Database(str(db_file))


def test_build_repository(tmp_path: pathlib.Path):
    async def run():
        db = _init_test_db(tmp_path)
        await db.create_tables()
        repo = BuildRepository(db)

        build_id = await repo.create_build(
            guild_id=123456789,
            user_id=987654321,
            template="gaming",
            schema_version="2.0",
            plan_dict={"test": True},
        )
        assert build_id > 0

        record = await repo.get_build(build_id)
        assert record is not None
        assert record["guild_id"] == 123456789
        assert record["status"] == "running"

        await repo.complete_build(
            build_id=build_id,
            status="completed",
            created_resources=[111, 222, 333],
        )

        updated = await repo.get_build(build_id)
        assert updated["status"] == "completed"
        assert updated["created_resources"] == [111, 222, 333]

        builds = await repo.list_builds(123456789)
        assert len(builds) == 1
        assert builds[0]["build_id"] == build_id

        await repo.record_rollback(build_id)
        rolled_back = await repo.get_build(build_id)
        assert rolled_back["status"] == "rolled_back"
        await db.close()

    asyncio.run(run())


def test_snapshot_repository(tmp_path: pathlib.Path):
    async def run():
        db = _init_test_db(tmp_path)
        await db.create_tables()
        repo = SnapshotRepository(db)

        snap_data = {"server_name": "Snap Server", "roles": [], "categories": []}
        snap_id = await repo.create_snapshot(
            guild_id=123456789,
            user_id=987654321,
            name="My Backup",
            data=snap_data,
        )
        assert snap_id > 0

        snap = await repo.get_snapshot(snap_id)
        assert snap is not None
        assert snap["name"] == "My Backup"
        assert snap["data"]["server_name"] == "Snap Server"

        snaps = await repo.list_snapshots(123456789)
        assert len(snaps) == 1
        await db.close()

    asyncio.run(run())


def test_automod_repository(tmp_path: pathlib.Path):
    async def run():
        db = _init_test_db(tmp_path)
        await db.create_tables()
        repo = AutoModRepository(db)

        config = await repo.get_config(123456789)
        assert config["badwords_enabled"] is False

        await repo.set_filter_enabled(123456789, "badwords_enabled", True)
        await repo.add_bad_words(123456789, ["foo", "bar"])

        updated = await repo.get_config(123456789)
        assert updated["badwords_enabled"] is True
        assert "foo" in updated["bad_words"]
        assert "bar" in updated["bad_words"]
        await db.close()

    asyncio.run(run())


def test_ticket_repository(tmp_path: pathlib.Path):
    async def run():
        db = _init_test_db(tmp_path)
        await db.create_tables()
        repo = TicketRepository(db)

        cfg = await repo.get_config(123456789)
        assert cfg == {}

        await repo.set_config(123456789, {
            "channel_id": "111",
            "category_id": "222",
            "support_role_id": "333",
        })

        updated = await repo.get_config(123456789)
        assert updated is not None
        assert updated["channel_id"] == "111"
        assert updated["category_id"] == "222"
        await db.close()

    asyncio.run(run())
