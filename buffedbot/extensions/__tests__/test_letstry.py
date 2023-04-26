from buffedbot.extensions.letstry import LetsTry, LetsTryProposal
from buffedbot.extensions.steam import Game as SteamGame
from discord.ext import commands
import unittest.mock as mock
from pytimeparse import parse as timeparse
from datetime import datetime, timedelta, timezone

import aiosqlite
import pytest
import pytest_asyncio
import dataclasses
import discord


class StringContains(str):
    def __eq__(self, other):
        return self in other


def assert_called_with_game_embed(mock, index, name, url, state=None):
    e = mock.call_args.kwargs["embeds"][index]
    assert e is not None
    assert e.title == name
    assert e.url == url
    if state is not None:
        for f in e.fields:
            if f.name != "State":
                continue
            assert f.value == state


class Nowish(str):
    def __eq__(self, other):
        dt = datetime.now(tz=timezone.utc)
        if self is not None and self != "":
            t = timeparse(self)
            if t is None:
                raise RuntimeError()
            dt += timedelta(seconds=t)
        other_ts = (
            int(other.split(":")[1]) if isinstance(other, str) else other.timestamp()
        )
        return -2 < dt.timestamp() - other_ts < 2


def assert_called_with_ballot_embed(
    mock, created_at, open_at=None, close_at=None, state=None, games=None
):
    mock.assert_called()
    embed: discord.Embed = mock.call_args.kwargs["embed"]
    assert embed is not None
    assert embed.title == "Lets Try Ballot"
    assert created_at == embed.timestamp
    for f in embed.fields:
        match f.name:
            case " ":
                pass
            case "Opens" | "Opened":
                if open_at is not None:
                    assert open_at == f.value
            case "Closes" | "Closed":
                if close_at is not None:
                    assert close_at == f.value
            case "State":
                if state is not None:
                    assert state == f.value
            case name:
                if games is not None:
                    assert name in games


@pytest_asyncio.fixture
async def test_db():
    async with aiosqlite.connect(":memory:") as con:
        yield con


@pytest.fixture
def mock_guild_db(test_db):
    with mock.patch.object(LetsTry, "get_guild_db", return_value=test_db):
        yield


@pytest.fixture
def steam_game(request, default_game_name, default_game_url):
    marker = request.node.get_closest_marker("steamgame")
    if marker is None:
        return SteamGame(
            name=default_game_name,
            url=default_game_url,
            description="",
            image="",
            price=0,
            review_count=0,
            review_summary="",
            date_created="",
        )
    else:
        marker.args[0]


@pytest_asyncio.fixture
async def letstry(mock_guild_db, mock_bot, steam_game):
    letstry = LetsTry(mock_bot)
    await letstry.cog_load()
    with mock.patch.object(letstry, "get_steam_game", return_value=steam_game):
        yield letstry


@pytest_asyncio.fixture
async def create_default_ballot(
    letstry,
    default_guild_context,
    invoke_command,
    default_thread_context,
    added_default_game,
    added_other_game,
):
    await invoke_command(letstry, "letstry ballot create", default_guild_context)
    await invoke_command(
        letstry, "letstry ballot add", default_thread_context, added_default_game.name
    )
    await invoke_command(
        letstry, "letstry ballot add", default_thread_context, added_other_game.name
    )
    await invoke_command(letstry, "letstry ballot submit", default_thread_context)
    default_thread_context.reply.assert_called_with(StringContains("Ballot submitted"))


@pytest.fixture
def table_names():
    return [
        "letstry_games",
        "letstry_proposals",
        "letstry_ballots",
        "letstry_ballot_games",
        "letstry_ballot_votes",
    ]


@pytest.mark.asyncio
async def test_create_letstry(letstry, table_names, test_db):
    db = test_db

    for table_name in table_names:
        async with db.execute(f"SELECT * FROM {table_name}") as cursor:
            async for row in cursor:
                assert row is None, "The table should be empty"

    # This is mostly for verification that the above code would throw
    # if one of the tables didnt exist
    table_name = "table_that_does_not_exist"
    assert table_name not in table_names, "this table shouldnt exist"
    with pytest.raises(aiosqlite.OperationalError):
        async with db.execute(f"SELECT * FROM {table_name}") as cursor:
            pass


@pytest.fixture
def default_game_name():
    return "A buffed game"


@pytest.fixture
def default_game_url():
    return "http://www.boldlyunbuffed.com"


@pytest.fixture
def other_game_name():
    return "Space Engineers"


@pytest.fixture
def other_game_url():
    return "https://store.steampowered.com/app/244850/"


@pytest.mark.asyncio
async def test_create_games(
    letstry: LetsTry,
    default_guild_context,
    default_game_name,
    default_game_url,
    other_game_name,
    other_game_url,
    invoke_command,
):
    # Insert a new non-steam Game
    await invoke_command(
        letstry,
        "letstry games add",
        default_guild_context,
        default_game_name,
        default_game_url,
    )
    default_guild_context.reply.assert_called_with(
        StringContains(f'Added "{default_game_name}" to proposed games')
    )

    await invoke_command(letstry, "letstry games list", default_guild_context)
    assert len(default_guild_context.reply.call_args.kwargs["embeds"]) == 1
    assert_called_with_game_embed(
        default_guild_context.reply, 0, default_game_name, default_game_url
    )

    await invoke_command(
        letstry, "letstry games delete", default_guild_context, default_game_name
    )
    default_guild_context.reply.assert_called_with(StringContains("deleted"))
    await invoke_command(letstry, "letstry games list", default_guild_context)
    default_guild_context.reply.assert_called_with(StringContains("No results"))

    # Will retrieve URL from "steam"
    await invoke_command(
        letstry, "letstry games add", default_guild_context, default_game_name
    )
    await invoke_command(letstry, "letstry games list", default_guild_context)
    assert len(default_guild_context.reply.call_args.kwargs["embeds"]) == 1
    assert_called_with_game_embed(
        default_guild_context.reply, 0, default_game_name, default_game_url
    )

    await invoke_command(
        letstry,
        "letstry games add",
        default_guild_context,
        other_game_name,
        other_game_url,
    )
    await invoke_command(letstry, "letstry games list", default_guild_context)
    assert len(default_guild_context.reply.call_args.kwargs["embeds"]) == 2
    assert_called_with_game_embed(
        default_guild_context.reply, 0, default_game_name, default_game_url
    )
    assert_called_with_game_embed(
        default_guild_context.reply, 1, other_game_name, other_game_url
    )


@pytest_asyncio.fixture
async def added_default_game(
    letstry: LetsTry, default_guild, default_game_name, default_game_url
):
    await letstry.add_game(default_guild, default_game_name, default_game_url)
    return await letstry.get_game(default_guild, default_game_name)


@pytest_asyncio.fixture
async def added_other_game(
    letstry: LetsTry, default_guild, other_game_name, other_game_url
):
    await letstry.add_game(default_guild, other_game_name, other_game_url)
    return await letstry.get_game(default_guild, other_game_name)


@pytest_asyncio.fixture
async def added_rejected_game(
    letstry: LetsTry,
    test_db,
    default_guild,
):
    await letstry.add_game(default_guild, "Rejected Game", "https://www.rejected.game/")
    game = await letstry.get_game(default_guild, "Rejected Game")
    assert game is not None
    game.state = "rejected"
    where = game.primary_key_match()
    await test_db.execute(
        game.update_stmt(where.keys()), where | dataclasses.asdict(game)
    )
    return game


@pytest.mark.asyncio
async def test_proposal(
    letstry: LetsTry,
    default_game_name,
    default_game_url,
    added_other_game,
    invoke_command,
    default_guild_context,
    other_member_context,
):
    # Can propose an existing game
    await invoke_command(
        letstry, "letstry games propose", default_guild_context, added_other_game.name
    )
    default_guild_context.reply.assert_called_with(
        StringContains("Added your proposal of")
    )
    await invoke_command(letstry, "letstry games list", default_guild_context, None)
    assert_called_with_game_embed(
        default_guild_context.reply,
        0,
        added_other_game.name,
        added_other_game.url,
        "submitted",
    )

    # Can retract proposal
    await invoke_command(letstry, "letstry games retract", default_guild_context)
    default_guild_context.reply.assert_called_with(StringContains("Removed proposal"))
    # No longer in normal list after proposal
    await invoke_command(letstry, "letstry games list", default_guild_context)
    default_guild_context.reply.assert_called_with(StringContains("No results"))
    # But instead in oprhaned state list
    await invoke_command(
        letstry, "letstry games list", default_guild_context, "orphaned"
    )
    assert_called_with_game_embed(
        default_guild_context.reply,
        0,
        added_other_game.name,
        added_other_game.url,
        "orphaned",
    )

    # Can propose a game from Steam
    await invoke_command(
        letstry, "letstry games propose", default_guild_context, default_game_name
    )
    default_guild_context.reply.assert_called_with(
        StringContains("Added your proposal of")
    )
    # Steam game now submitted
    await invoke_command(letstry, "letstry games list", default_guild_context)
    assert_called_with_game_embed(
        default_guild_context.reply, 0, default_game_name, default_game_url, "submitted"
    )
    # Other game remains orphaned
    await invoke_command(
        letstry, "letstry games list", default_guild_context, "orphaned"
    )
    assert_called_with_game_embed(
        default_guild_context.reply,
        0,
        added_other_game.name,
        added_other_game.url,
        "orphaned",
    )

    # Cant propose multiple times
    await invoke_command(
        letstry, "letstry games propose", default_guild_context, default_game_name
    )
    default_guild_context.reply.assert_called_with(StringContains("active proposal"))

    # Not even other games
    await invoke_command(
        letstry, "letstry games propose", default_guild_context, added_other_game.name
    )
    default_guild_context.reply.assert_called_with(StringContains("active proposal"))

    # But a different user can (even the same one)
    await invoke_command(
        letstry, "letstry games propose", other_member_context, default_game_name
    )
    other_member_context.reply.assert_called_with(
        StringContains("Added your proposal of")
    )
    await invoke_command(letstry, "letstry games list", default_guild_context)
    assert_called_with_game_embed(
        default_guild_context.reply, 0, default_game_name, default_game_url, "submitted"
    )

    # That user can retract proposal
    await invoke_command(letstry, "letstry games retract", other_member_context)
    other_member_context.reply.assert_called_with(StringContains("Removed proposal"))
    # Game remains submitted if at least one user is proposing
    await invoke_command(letstry, "letstry games list", default_guild_context)
    assert_called_with_game_embed(
        default_guild_context.reply, 0, default_game_name, default_game_url, "submitted"
    )


@pytest.mark.asyncio
async def test_ballots(
    letstry: LetsTry,
    added_default_game,
    added_other_game,
    added_rejected_game,
    invoke_command,
    default_thread_context,
    default_guild_context,
    default_channel,
):
    # Create a ballot
    await invoke_command(letstry, "letstry ballot create", default_guild_context)
    default_channel.create_thread.assert_called()

    await invoke_command(
        letstry,
        "letstry ballot show",
        default_thread_context,
    )
    assert_called_with_ballot_embed(
        default_thread_context.reply,
        Nowish(),
        Nowish(),
        Nowish("3 days"),
        "staging",
        [],
    )

    # Add a game
    await invoke_command(
        letstry, "letstry ballot add", default_thread_context, added_default_game.name
    )
    default_thread_context.reply.assert_called_with(StringContains("added to ballot"))

    await invoke_command(
        letstry,
        "letstry ballot show",
        default_thread_context,
    )
    assert_called_with_ballot_embed(
        default_thread_context.reply,
        Nowish(),
        Nowish(),
        Nowish("3 days"),
        "staging",
        [added_default_game.name],
    )

    # Can't add the same game twice
    await invoke_command(
        letstry, "letstry ballot add", default_thread_context, added_default_game.name
    )
    default_thread_context.reply.assert_called_with(
        StringContains("already in the ballot")
    )

    # But can add a different game
    await invoke_command(
        letstry, "letstry ballot add", default_thread_context, added_other_game.name
    )
    default_thread_context.reply.assert_called_with(StringContains("added to ballot"))

    await invoke_command(
        letstry,
        "letstry ballot show",
        default_thread_context,
    )
    assert_called_with_ballot_embed(
        default_thread_context.reply,
        Nowish(),
        Nowish(),
        Nowish("3 days"),
        "staging",
        [added_default_game.name, added_other_game.name],
    )

    # Cant add games with rejected state
    await invoke_command(
        letstry, "letstry ballot add", default_thread_context, added_rejected_game.name
    )
    default_thread_context.reply.assert_called_with(
        StringContains("is already rejected")
    )

    # Can remove games
    await invoke_command(
        letstry,
        "letstry ballot remove",
        default_thread_context,
        added_default_game.name,
    )
    default_thread_context.reply.assert_called_with(StringContains("removed"))

    await invoke_command(
        letstry,
        "letstry ballot show",
        default_thread_context,
    )
    assert_called_with_ballot_embed(
        default_thread_context.reply,
        Nowish(),
        Nowish(),
        Nowish("3 days"),
        "staging",
        [added_other_game.name],
    )

    # And then readd them
    await invoke_command(
        letstry, "letstry ballot add", default_thread_context, added_default_game.name
    )
    default_thread_context.reply.assert_called_with(StringContains("added to ballot"))

    # Cant add games that don't exist
    await invoke_command(
        letstry, "letstry ballot add", default_thread_context, "Random Game"
    )
    default_thread_context.reply.assert_called_with(StringContains("not found"))

    # And also can't remove them
    await invoke_command(
        letstry, "letstry ballot remove", default_thread_context, "Random Game"
    )
    default_thread_context.reply.assert_called_with(StringContains("not found"))

    # Can't remove games that are not part of a ballot
    await invoke_command(
        letstry,
        "letstry ballot remove",
        default_thread_context,
        added_rejected_game.name,
    )
    default_thread_context.reply.assert_called_with(StringContains("not in the ballot"))

    await invoke_command(
        letstry,
        "letstry ballot show",
        default_thread_context,
    )
    assert_called_with_ballot_embed(
        default_thread_context.reply,
        Nowish(),
        Nowish(),
        Nowish("3 days"),
        "staging",
        [added_default_game.name, added_other_game.name],
    )

    # Can change the duration of the ballot
    await invoke_command(
        letstry, "letstry ballot duration", default_thread_context, "1 week"
    )
    default_thread_context.reply.assert_called_with(
        StringContains("Updated end date to")
    )

    await invoke_command(
        letstry,
        "letstry ballot show",
        default_thread_context,
    )
    assert_called_with_ballot_embed(
        default_thread_context.reply,
        Nowish(),
        Nowish(),
        Nowish("1 week"),
        "staging",
        [added_default_game.name, added_other_game.name],
    )

    # Change when the ballot opens
    await invoke_command(
        letstry, "letstry ballot open", default_thread_context, "1 day"
    )
    default_thread_context.reply.assert_called_with(
        StringContains("Updated open date to")
    )

    await invoke_command(
        letstry,
        "letstry ballot show",
        default_thread_context,
    )
    assert_called_with_ballot_embed(
        default_thread_context.reply,
        Nowish(),
        Nowish("1 day"),
        Nowish("1 week"),
        "staging",
        [added_default_game.name, added_other_game.name],
    )

    # Submit the ballot (finish staging state)
    await invoke_command(
        letstry,
        "letstry ballot submit",
        default_thread_context,
    )
    default_thread_context.reply.assert_called_with(StringContains("Ballot submitted"))

    await invoke_command(
        letstry,
        "letstry ballot show",
        default_thread_context,
    )
    assert_called_with_ballot_embed(
        default_thread_context.reply,
        Nowish(),
        Nowish("1 day"),
        Nowish("1 week"),
        "submitted",
        [added_default_game.name, added_other_game.name],
    )

    # Change the ballot open date to now (opening the ballot)
    await invoke_command(letstry, "letstry ballot open", default_thread_context, "now")
    default_thread_context.reply.assert_called_with(
        StringContains("Updated open date to")
    )

    await invoke_command(
        letstry,
        "letstry ballot show",
        default_thread_context,
    )
    assert_called_with_ballot_embed(
        default_thread_context.reply,
        Nowish(),
        Nowish(),
        Nowish("1 week"),
        "open",
        [added_default_game.name, added_other_game.name],
    )

    # Change the ballot duration to 1 hour (should keep the Ballot open)
    await invoke_command(
        letstry, "letstry ballot duration", default_thread_context, "1 hour"
    )
    default_thread_context.reply.assert_called_with(
        StringContains("Updated end date to")
    )

    await invoke_command(
        letstry,
        "letstry ballot show",
        default_thread_context,
    )
    assert_called_with_ballot_embed(
        default_thread_context.reply,
        Nowish(),
        Nowish(),
        Nowish("1 hour"),
        "open",
        [added_default_game.name, added_other_game.name],
    )

    # Change the ballot duration to 0 minutes (should close the ballot)
    await invoke_command(
        letstry, "letstry ballot duration", default_thread_context, "0 minutes"
    )
    default_thread_context.reply.assert_called_with(
        StringContains("Updated end date to")
    )

    await invoke_command(
        letstry,
        "letstry ballot show",
        default_thread_context,
    )
    assert_called_with_ballot_embed(
        default_thread_context.reply,
        Nowish(),
        Nowish(),
        Nowish(),
        "closed",
        [added_default_game.name, added_other_game.name],
    )


@pytest.mark.asyncio
async def test_basic_voting(
    letstry,
    create_default_ballot,
    invoke_command,
    default_guild_context,
    default_game_name,
    other_game_name,
    default_member,
    click_button,
    other_member,
):
    await invoke_command(letstry, "letstry ballots", default_guild_context)
    assert_called_with_ballot_embed(
        default_guild_context.reply,
        Nowish(),
        Nowish(),
        Nowish("3 days"),
        "open",
        [default_game_name, other_game_name],
    )

    interaction = await click_button(
        default_member, default_guild_context.reply, "Vote now"
    )
    interaction.response.send_message.assert_called_with(
        StringContains("Which game would you like to vote for"),
        view=mock.ANY,
        ephemeral=True,
        delete_after=mock.ANY,
    )

    interaction = await click_button(
        default_member, interaction.response.send_message, default_game_name
    )
    interaction.response.edit_message.assert_called_with(
        content=StringContains("Vote recorded"), view=None, delete_after=mock.ANY
    )

    interaction = await click_button(
        default_member, default_guild_context.reply, "Vote now"
    )
    interaction.response.send_message.assert_called_with(
        StringContains("You have already voted"), ephemeral=True, delete_after=mock.ANY
    )

    interaction = await click_button(
        other_member, default_guild_context.reply, "Vote now"
    )
    interaction.response.send_message.assert_called_with(
        StringContains("Which game would you like to vote for"),
        view=mock.ANY,
        ephemeral=True,
        delete_after=mock.ANY,
    )

    interaction = await click_button(
        other_member, interaction.response.send_message, default_game_name
    )
    interaction.response.edit_message.assert_called_with(
        content=StringContains("Vote recorded"), view=None, delete_after=mock.ANY
    )


@pytest.mark.asyncio
async def test_voting_closed_ballot(
    letstry,
    create_default_ballot,
    invoke_command,
    default_thread_context,
    default_guild_context,
    default_game_name,
    other_game_name,
    default_member,
    click_button,
    other_member,
):
    await invoke_command(letstry, "letstry ballots", default_guild_context)
    assert_called_with_ballot_embed(
        default_guild_context.reply,
        Nowish(),
        Nowish(),
        Nowish("3 days"),
        "open",
        [default_game_name, other_game_name],
    )
    await invoke_command(
        letstry, "letstry ballot duration", default_thread_context, "0 min"
    )

    interaction = await click_button(
        default_member, default_guild_context.reply, "Vote now"
    )
    interaction.response.send_message.assert_called_with(
        StringContains("Which game would you like to vote for"),
        view=mock.ANY,
        ephemeral=True,
        delete_after=mock.ANY,
    )

    interaction = await click_button(
        other_member, interaction.response.send_message, default_game_name
    )
    interaction.response.edit_message.assert_called_with(
        content=StringContains("Ballot not open"), view=mock.ANY, delete_after=mock.ANY
    )


@pytest.mark.asyncio
async def test_voting_submitted(
    letstry,
    create_default_ballot,
    invoke_command,
    default_thread_context,
    default_guild_context,
    default_game_name,
    other_game_name,
    default_member,
    click_button,
    other_member,
):
    await invoke_command(letstry, "letstry ballots", default_guild_context)
    assert_called_with_ballot_embed(
        default_guild_context.reply,
        Nowish(),
        Nowish(),
        Nowish("3 days"),
        "open",
        [default_game_name, other_game_name],
    )
    await invoke_command(
        letstry, "letstry ballot open", default_thread_context, "1 day"
    )

    interaction = await click_button(
        default_member, default_guild_context.reply, "Vote now"
    )
    interaction.response.send_message.assert_called_with(
        StringContains("Which game would you like to vote for"),
        view=mock.ANY,
        ephemeral=True,
        delete_after=mock.ANY,
    )

    interaction = await click_button(
        other_member, interaction.response.send_message, default_game_name
    )
    interaction.response.edit_message.assert_called_with(
        content=StringContains("Ballot not open"), view=mock.ANY, delete_after=mock.ANY
    )
