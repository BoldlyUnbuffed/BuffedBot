import aiofiles
import pytest
import unittest.mock as mock
from aiopath import AsyncPath
from contextlib import contextmanager
from collections import namedtuple
from buffedbot.extensions.guildstorage import GuildStorage
from discord.ext import commands


def pytest_configure(config):
    # register additional markers
    config.addinivalue_line(
        "markers", "isowner(true_or_false): marks if the author is considered owner of the bot"
    )

def aio_mock_open(file_mock):
    register_aiofiles_mock()

    return mock.patch('aiofiles.threadpool.sync_open', return_value=file_mock)

@contextmanager
def _aio_mock_file():
    file_mock = mock.MagicMock()
    with aio_mock_open(file_mock):
        yield file_mock

@pytest.fixture
def mock_file():
    with _aio_mock_file() as f:
        yield f

@pytest.fixture
def mock_async_path_exists(request):
    marker = request.node.get_closest_marker('asyncpathexists')
    if marker is None:
        value = True
    else:
        value = marker.args[0]
    with mock.patch.object(AsyncPath, 'exists', return_value=value):
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
    aiofiles.threadpool.wrap.register(mock.MagicMock)( # type: ignore
        lambda *args,
        **kwargs: aiofiles.threadpool.AsyncBufferedIOBase( # type: ignore
            *args,
            **kwargs
        )
    )

@pytest.fixture
def mock_guild_storage(create_get_cog_mock):
    gs = mock.Mock(GuildStorage)
    create_get_cog_mock(GuildStorage.__cog_name__, gs)
    gs.get_guild_storage_path.return_value = './guilds/'
    return gs

@pytest.fixture
def create_get_cog_mock(mock_bot):
    def _add_cog(name, cog):
        cogs[name] = cog
    cogs = {}
    mock_bot.get_cog = lambda cog: cogs[cog]
    return _add_cog

def make_guild(id):
    return namedtuple('Guild', ['id'])(id)

def make_context(bot, guild=None):
    return namedtuple(
        'Context',
        ['bot', 'guild', 'reply', 'author']
    )(bot, guild, mock.AsyncMock(), mock.Mock())

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
def mock_bot(request, guilds):
    marker = request.node.get_closest_marker('isowner')
    if marker is None:
        is_owner = True
    else:
        is_owner = marker.args[0]

    bot = mock.Mock()
    bot.is_owner = mock.AsyncMock(return_value=is_owner)
    bot.guilds = guilds
    return bot

@pytest.fixture
def default_guild_context(default_guild, mock_bot):
    return make_context(mock_bot, guild=default_guild)