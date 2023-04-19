import aiofiles
import pytest
import unittest.mock as mock
from aiopath import AsyncPath
from contextlib import contextmanager
from collections import namedtuple
from buffedbot.extensions.guildstorage import GuildStorage
from buffedbot.extensions.steam import Steam
from discord.ext import commands


def pytest_configure(config):
    # register additional markers
    config.addinivalue_line(
        "markers",
        "isowner(true_or_false): marks if the author is considered owner of the bot",
    )


def aio_mock_open(file_mock):
    register_aiofiles_mock()

    return mock.patch("aiofiles.threadpool.sync_open", return_value=file_mock)


@contextmanager
def _aio_mock_file():
    file_mock = mock.MagicMock()
    with aio_mock_open(file_mock):
        yield file_mock


@pytest.fixture
def invoke_command():
    async def invoke(cog, command: str, ctx, *args, **kwargs):
        subcommands = command.split(" ")
        print(subcommands)
        cog_commands = cog.get_commands()
        for c in cog_commands:
            if c.name != subcommands[0]:
                continue

            rest = " ".join(subcommands[1:])
            if type(c) != commands.core.Group:
                return await c(cog, ctx, *args, **kwargs)

            cmd = c.get_command(rest)
            if cmd is None:
                raise RuntimeError()
            return await cmd(cog, ctx, *args, **kwargs)
        else:
            raise RuntimeError()

    return invoke


@pytest.fixture
def mock_file():
    with _aio_mock_file() as f:
        yield f


@pytest.fixture
def mock_async_path_exists(request):
    marker = request.node.get_closest_marker("asyncpathexists")
    if marker is None:
        value = True
    else:
        value = marker.args[0]
    with mock.patch.object(AsyncPath, "exists", return_value=value):
        yield


@pytest.fixture
def inject_mock_file_read_data(mock_file):
    def _inject_read_data(data):
        mock_file.read.return_value = data

    return _inject_read_data


def once(f):
    called = False

    def wrapper():
        nonlocal called
        if called:
            return
        called = True
        f()

    return wrapper


@once
def register_aiofiles_mock():
    aiofiles.threadpool.wrap.register(mock.MagicMock)(  # type: ignore
        lambda *args, **kwargs: aiofiles.threadpool.AsyncBufferedIOBase(  # type: ignore
            *args, **kwargs
        )
    )


@pytest.fixture
def mock_guild_storage(create_get_cog_mock):
    gs = mock.Mock(GuildStorage)
    create_get_cog_mock(GuildStorage.__cog_name__, gs)
    gs.get_guild_storage_path.return_value = "./guilds/"
    return gs


@pytest.fixture
def mock_steam(create_get_cog_mock):
    steam = mock.Mock(Steam)
    create_get_cog_mock(Steam.__cog_name__, steam)
    return steam


@pytest.fixture
def create_get_cog_mock(mock_bot):
    def _add_cog(name, cog):
        cogs[name] = cog

    cogs = {}
    mock_bot.get_cog = lambda cog: cogs[cog]
    return _add_cog


def make_channel(spawned_thread=None):
    return namedtuple("Channel", ["reply", "create_thread"])(
        mock.AsyncMock(),
        mock.AsyncMock(return_value=spawned_thread),
    )


def make_guild(id):
    return namedtuple("Guild", ["id"])(id)


def make_user(id):
    return namedtuple("User", ["id"])(id)


def make_context(bot, guild=mock.Mock(), author=mock.Mock(), channel=mock.Mock()):
    return namedtuple(
        "Context", ["bot", "guild", "reply", "author", "channel", "message"]
    )(bot, guild, mock.AsyncMock(), author, channel, mock.Mock())


@pytest.fixture
def default_member():
    return make_user(6789012345)


@pytest.fixture
def other_member():
    return make_user(5432106789)


@pytest.fixture
def default_guild():
    return make_guild(123456789)


@pytest.fixture
def other_guild():
    return make_guild(987654321)


@pytest.fixture
def guilds(default_guild):
    return [default_guild]


@pytest.fixture
def default_thread(default_guild):
    return namedtuple("Thread", ["id", "guild", "reply"])(
        8967452310, default_guild, mock.AsyncMock()
    )


@pytest.fixture
def mock_bot(request, guilds):
    marker = request.node.get_closest_marker("isowner")
    if marker is None:
        is_owner = True
    else:
        is_owner = marker.args[0]

    bot = mock.Mock()
    bot.is_owner = mock.AsyncMock(return_value=is_owner)
    bot.guilds = guilds
    return bot


@pytest.fixture
def default_channel(default_thread):
    return make_channel(default_thread)


@pytest.fixture
def default_guild_context(default_guild, mock_bot, default_channel, default_member):
    return make_context(
        mock_bot, guild=default_guild, author=default_member, channel=default_channel
    )


@pytest.fixture
def other_member_context(default_guild, mock_bot, default_channel, other_member):
    return make_context(
        mock_bot, guild=default_guild, author=other_member, channel=default_channel
    )


@pytest.fixture
def default_thread_context(default_guild, default_thread):
    return make_context(mock_bot, guild=default_guild, channel=default_thread)
