"""Mock Discord objects for offline unit and integration testing."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord


class MockRole:
    def __init__(
        self,
        id: int,
        name: str,
        position: int = 1,
        permissions: discord.Permissions | None = None,
        color: discord.Colour | None = None,
        hoist: bool = False,
        mentionable: bool = False,
        is_default_role: bool = False,
    ) -> None:
        self.id = id
        self.name = name
        self.position = position
        self.permissions = permissions or discord.Permissions.none()
        self.color = color or discord.Colour.default()
        self.hoist = hoist
        self.mentionable = mentionable
        self.managed = False
        self._is_default = is_default_role
        self.members: list[Any] = []
        self.mention = f"<@&{id}>"

    def is_default(self) -> bool:
        return self._is_default

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, MockRole):
            return self.position >= other.position
        return False

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, MockRole):
            return self.position > other.position
        return False

    def __le__(self, other: Any) -> bool:
        if isinstance(other, MockRole):
            return self.position <= other.position
        return False

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, MockRole):
            return self.position < other.position
        return False

    async def delete(self, reason: str | None = None) -> None:
        pass

    async def edit(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class MockChannel:
    def __init__(
        self,
        id: int,
        name: str,
        guild: MockGuild,
        category: MockCategoryChannel | None = None,
        ch_type: discord.ChannelType = discord.ChannelType.text,
    ) -> None:
        self.id = id
        self.name = name
        self.guild = guild
        self.category = category
        self.category_id = category.id if category else None
        self.type = ch_type
        self.position = 0
        self.overwrites: dict[Any, discord.PermissionOverwrite] = {}
        self.permissions_synced = False
        self.topic = ""
        self.slowmode_delay = 0
        self.nsfw = False
        self.mention = f"<#{id}>"
        self.send = AsyncMock(return_value=MagicMock(id=9999))

    @property
    def jump_url(self) -> str:
        return f"https://discord.com/channels/{self.guild.id}/{self.id}"

    def permissions_for(self, target: Any) -> discord.Permissions:
        # Default full permissions for testing
        return discord.Permissions.all()

    def overwrites_for(self, target: Any) -> discord.PermissionOverwrite:
        return self.overwrites.get(target, discord.PermissionOverwrite())

    async def set_permissions(self, target: Any, overwrite: discord.PermissionOverwrite | None = None, **kwargs: Any) -> None:
        if overwrite is not None:
            self.overwrites[target] = overwrite

    async def edit(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

    async def delete(self, reason: str | None = None) -> None:
        if self in self.guild.channels:
            self.guild.channels.remove(self)


class MockCategoryChannel(MockChannel):
    def __init__(self, id: int, name: str, guild: MockGuild) -> None:
        super().__init__(id, name, guild, None, discord.ChannelType.category)
        self.channels: list[MockChannel] = []


class MockMember:
    def __init__(self, id: int, name: str, guild: MockGuild, roles: list[MockRole] | None = None) -> None:
        self.id = id
        self.name = name
        self.guild = guild
        self.roles = roles or []
        self.bot = False
        self.mention = f"<@{id}>"
        self.display_avatar = MagicMock(url="https://example.com/avatar.png")
        self.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        self.send = AsyncMock()

    @property
    def top_role(self) -> MockRole:
        if not self.roles:
            return self.guild.default_role
        return max(self.roles, key=lambda r: r.position)

    @property
    def guild_permissions(self) -> discord.Permissions:
        p = discord.Permissions.none()
        for r in self.roles:
            p.value |= r.permissions.value
        return p

    async def add_roles(self, *roles: MockRole, reason: str | None = None) -> None:
        for r in roles:
            if r not in self.roles:
                self.roles.append(r)

    async def remove_roles(self, *roles: MockRole, reason: str | None = None) -> None:
        for r in roles:
            if r in self.roles:
                self.roles.remove(r)


class MockGuild:
    def __init__(self, id: int = 123456789, name: str = "Test Guild") -> None:
        self.id = id
        self.name = name
        self.member_count = 10
        self.bitrate_limit = 96000
        self.default_role = MockRole(id=id, name="@everyone", position=0, is_default_role=True)
        self.roles: list[MockRole] = [self.default_role]
        self.channels: list[MockChannel] = []
        self.categories: list[MockCategoryChannel] = []
        self.members: list[MockMember] = []
        self.owner_id = 111111111
        self.owner = None

        # Bot member
        bot_perms = discord.Permissions.all()
        self.bot_role = MockRole(id=999, name="DAMU Bot", position=100, permissions=bot_perms)
        self.roles.append(self.bot_role)
        self.me = MockMember(id=888888, name="DAMU Bot", guild=self, roles=[self.bot_role])
        self.me.bot = True

    def get_role(self, role_id: int) -> MockRole | None:
        return discord.utils.get(self.roles, id=role_id)

    def get_channel(self, channel_id: int) -> MockChannel | None:
        return discord.utils.get(self.channels, id=channel_id)

    def get_member(self, user_id: int) -> MockMember | None:
        return discord.utils.get(self.members, id=user_id)

    async def edit(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

    async def create_role(self, **kwargs: Any) -> MockRole:
        role_id = len(self.roles) + 1000
        role = MockRole(
            id=role_id,
            name=kwargs.get("name", "new-role"),
            position=len(self.roles),
            permissions=kwargs.get("permissions"),
            color=kwargs.get("colour") or kwargs.get("color"),
            hoist=kwargs.get("hoist", False),
            mentionable=kwargs.get("mentionable", False),
        )
        self.roles.append(role)
        return role

    async def create_category(self, **kwargs: Any) -> MockCategoryChannel:
        cat_id = len(self.channels) + 2000
        cat = MockCategoryChannel(id=cat_id, name=kwargs.get("name", "new-category"), guild=self)
        if "overwrites" in kwargs and kwargs["overwrites"]:
            cat.overwrites = kwargs["overwrites"]
        self.categories.append(cat)
        self.channels.append(cat)
        return cat

    async def create_text_channel(self, **kwargs: Any) -> MockChannel:
        ch_id = len(self.channels) + 3000
        ch = MockChannel(
            id=ch_id,
            name=kwargs.get("name", "new-channel"),
            guild=self,
            category=kwargs.get("category"),
            ch_type=discord.ChannelType.text,
        )
        ch.topic = kwargs.get("topic", "")
        ch.slowmode_delay = kwargs.get("slowmode_delay", 0)
        ch.nsfw = kwargs.get("nsfw", False)
        if "overwrites" in kwargs and kwargs["overwrites"]:
            ch.overwrites = kwargs["overwrites"]
        self.channels.append(ch)
        if ch.category:
            ch.category.channels.append(ch)
        return ch

    async def create_voice_channel(self, **kwargs: Any) -> MockChannel:
        ch_id = len(self.channels) + 4000
        ch = MockChannel(
            id=ch_id,
            name=kwargs.get("name", "new-voice"),
            guild=self,
            category=kwargs.get("category"),
            ch_type=discord.ChannelType.voice,
        )
        if "overwrites" in kwargs and kwargs["overwrites"]:
            ch.overwrites = kwargs["overwrites"]
        self.channels.append(ch)
        if ch.category:
            ch.category.channels.append(ch)
        return ch

    async def create_forum(self, **kwargs: Any) -> MockChannel:
        ch_id = len(self.channels) + 5000
        ch = MockChannel(
            id=ch_id,
            name=kwargs.get("name", "new-forum"),
            guild=self,
            category=kwargs.get("category"),
            ch_type=discord.ChannelType.forum,
        )
        if "overwrites" in kwargs and kwargs["overwrites"]:
            ch.overwrites = kwargs["overwrites"]
        self.channels.append(ch)
        if ch.category:
            ch.category.channels.append(ch)
        return ch


class MockResponse:
    def __init__(self) -> None:
        self._done = False
        self.send_message = AsyncMock(side_effect=self._on_send)
        self.defer = AsyncMock(side_effect=self._on_defer)
        self.send_modal = AsyncMock(side_effect=self._on_modal)
        self.edit_message = AsyncMock()

    def is_done(self) -> bool:
        return self._done

    async def _on_send(self, *args: Any, **kwargs: Any) -> None:
        if self._done:
            raise discord.InteractionResponded(MagicMock())
        self._done = True

    async def _on_defer(self, *args: Any, **kwargs: Any) -> None:
        if self._done:
            raise discord.InteractionResponded(MagicMock())
        self._done = True

    async def _on_modal(self, modal: Any) -> None:
        if self._done:
            raise discord.InteractionResponded(MagicMock())
        self._done = True


class MockInteraction:
    def __init__(self, guild: MockGuild, user: MockMember | None = None) -> None:
        self.id = 555555555
        self.guild = guild
        self.user = user or MockMember(id=777777, name="TestUser", guild=guild)
        self.channel = MockChannel(id=111, name="general", guild=guild)
        self.created_at = datetime.now(timezone.utc)
        self.response = MockResponse()
        self.followup = MagicMock()
        self.followup.send = AsyncMock(return_value=MagicMock())
        self.edit_original_response = AsyncMock()
        self.client = MagicMock()
