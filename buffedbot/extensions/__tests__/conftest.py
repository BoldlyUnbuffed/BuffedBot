import aiofiles
import pytest
import unittest.mock as mock
from aiopath import AsyncPath
from contextlib import contextmanager
from collections import namedtuple
from buffedbot.extensions.settings import Settings
from buffedbot.extensions.guildstorage import GuildStorage
from buffedbot.extensions.steam import Steam
from discord.ext import commands
import discord
import inspect


def pytest_configure(config):
    # register additional markers
    config.addinivalue_line(
        "markers",
        "isowner(true_or_false): marks if the author is considered owner of the bot",
    )
    config.addinivalue_line(
        "markers",
        "asyncpathexists(true_or_false): marks AsyncPath exists return value",
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
    # HERE BE DRAGONS
    # Calls a "raw" DiscordPy bot or cog command
    # There really should be an easier way to call a command callback
    # But because of all the trickery associated with how DiscordPy
    # handles kw-only arguments in commands, this is rather complicated
    async def call_dpy_command(func, cog, ctx, *args, **kwargs):
        func = func.callback
        catch_all_param = None
        signature = inspect.signature(func)
        for param in signature.parameters.values():
            # Find kw-only argument
            if param.kind == param.KEYWORD_ONLY:
                # DiscordPy treats the kw-only argument as a catch all/"rest" argument
                catch_all_param = param
                # DiscordPy requires only allows for a single kw-only argument
                break
        # Get positional args
        positional_func_args = list(
            filter(
                lambda p: p.kind == param.POSITIONAL_OR_KEYWORD,
                signature.parameters.values(),
            )
        )
        # Remove self and ctx
        positional_func_args = positional_func_args[2:]

        func_arg_count = len(positional_func_args)

        # Trim any arguments to this function beyond the number
        # of arguments expected in the command func
        remainders = args[func_arg_count:]
        args = args[:func_arg_count]

        if catch_all_param is not None:
            # Use the defult value of catch_all_param if we have no arguments
            # for it
            if len(remainders) == 0:
                remainders = catch_all_param.default.default
            else:
                # We'll take a string or list of strings
                remainders = " ".join(remainders)

            # Assign the remainder args to the catch all kw argument
            # Like DiscordPy would do it
            kwargs[catch_all_param.name] = remainders
        elif len(remainders) != 0:
            # If we don't have a catch all we can't deal with additional arguments
            raise ValueError("Too many arguments")

        # If we have gotten less arguments in this call than the command func
        # expects, we need to fill the arguments with default values from the
        # command func's native (p.default) or -- if present -- commands.parameter
        # object's (p.default.default) default value.
        if len(args) < func_arg_count:
            args += tuple(
                map(
                    lambda p: getattr(p.default, "default", p.default),
                    positional_func_args[len(args) :],
                )
            )

        return await func(cog, ctx, *args, **kwargs)

    async def invoke(cog, command: str, ctx, *args, **kwargs):
        subcommands = command.split(" ")
        cog_commands = cog.get_commands()
        for c in cog_commands:
            if c.name != subcommands[0]:
                continue

            rest = " ".join(subcommands[1:])
            if type(c) != commands.core.Group:
                return await call_dpy_command(c, cog, ctx, *args, **kwargs)
                return await c(cog, ctx, *args, **kwargs)

            cmd = c.get_command(rest)
            if cmd is None:
                raise RuntimeError()
            return await call_dpy_command(cmd, cog, ctx, *args, **kwargs)
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
def mock_settings(create_get_cog_mock, request):
    s = mock.Mock(Settings)
    create_get_cog_mock(Settings.__cog_name__, s)
    marker = request.node.get_closest_marker("guildget")
    if marker is None:
        s.guild_get = mock.Mock(side_effect=lambda g, k, d: d)
    else:
        s.guild_get = mock.Mock(return_value=marker.args[0])
    return s


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


def make_channel(guild, spawned_thread=None):
    return namedtuple("Channel", ["reply", "create_thread", "guild", "send"])(
        mock.AsyncMock(),
        mock.AsyncMock(return_value=spawned_thread),
        guild,
        mock.AsyncMock(),
    )


def make_guild(id):
    return namedtuple("Guild", ["id", "get_channel_or_thread", "fetch_channel"])(
        id, mock.Mock(), mock.AsyncMock()
    )


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
    return namedtuple("Thread", ["id", "guild", "send", "edit"])(
        8967452310, default_guild, mock.AsyncMock(), mock.AsyncMock()
    )


@pytest.fixture
def mock_bot(request, default_guild):
    marker = request.node.get_closest_marker("isowner")
    if marker is None:
        is_owner = True
    else:
        is_owner = marker.args[0]

    bot = mock.Mock()
    bot.is_owner = mock.AsyncMock(return_value=is_owner)
    bot.guilds = [default_guild]
    return bot


@pytest.fixture
def default_channel(default_thread, default_guild):
    return make_channel(default_guild, default_thread)


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


def make_interaction(user):
    interaction = mock.AsyncMock()
    interaction.user = user
    return interaction


@pytest.fixture
def click_button():
    async def click(member, mock, label):
        view = mock.call_args.kwargs["view"]
        interaction = make_interaction(member)
        for component in view.children:
            if not isinstance(component, discord.ui.Button):
                continue
            if component.label is None:
                continue
            if label not in component.label:
                continue
            await component.callback(interaction)
            return interaction
        raise RuntimeError(f"Button with label {label} not found.")

    return click
