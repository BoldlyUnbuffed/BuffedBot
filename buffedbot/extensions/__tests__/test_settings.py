from buffedbot.extensions.settings import Settings, RESTRICTED_SETTINGS_KEY
from discord.ext import commands
import json

import pytest
import pytest_asyncio


def legacy_invoke_command(cog, command, *args, **kwargs):
    c = getattr(cog, command)
    return c(cog, *args, **kwargs)


@pytest_asyncio.fixture
async def settings(
    mock_bot,
    mock_guild_storage,
    mock_file_inject_empty_settings_data,
    mock_async_path_exists,
):
    settings = Settings(mock_bot)
    await settings.cog_load()
    return settings


@pytest.fixture
def hidden_key():
    return RESTRICTED_SETTINGS_KEY


@pytest.fixture
def invalid_key():
    return "invalid key"


@pytest.fixture
def mock_file_inject_empty_settings_data(
    empty_settings_data, inject_mock_file_read_data
):
    inject_mock_file_read_data(json.dumps(empty_settings_data))


@pytest.fixture(
    params=[
        {"key": "value"},
        {"key": "value", "another": "value"},
        {"complex": {"data": "here"}},
    ]
)
def settings_data(request, invalid_key):
    assert invalid_key not in request.param
    return request.param


@pytest.fixture
def empty_settings_data():
    return {}


@pytest.mark.asyncio
async def test_create_settings(settings: Settings):
    assert settings is not None
    assert settings.settings is not None
    assert len(settings.settings) == 0

@pytest.mark.asyncpathexists(False)
@pytest.mark.asyncio
async def test_create_settings_without_file(settings: Settings):
    assert settings is not None
    assert settings.settings is not None
    assert len(settings.settings) == 0


@pytest.mark.asyncio
async def test_load(settings: Settings, settings_data, inject_mock_file_read_data):
    inject_mock_file_read_data(json.dumps(settings_data))

    await settings.load()
    for k, v in settings_data.items():
        assert settings.get(k, None) == v


@pytest.mark.asyncio
async def test_set(settings: Settings, mock_file, settings_data):
    for k, v in settings_data.items():
        await settings.set(k, v)

    mock_file.write.assert_called_with(json.dumps(settings_data))


@pytest.mark.asyncio
async def test_get(settings: Settings, mock_file, settings_data):
    for k, v in settings_data.items():
        await settings.set(k, v)

    for k, v in settings_data.items():
        assert settings.get(k, None) == v


@pytest.mark.asyncio
async def test_store(settings: Settings, mock_file, settings_data):
    for k, v in settings_data.items():
        await settings.set(k, v)

    mock_file.write.reset_mock()

    await settings.store()

    mock_file.write.assert_called_with(json.dumps(settings_data))


@pytest.mark.asyncio
async def test_guild_load(
    settings: Settings, settings_data, inject_mock_file_read_data, default_guild
):
    inject_mock_file_read_data(json.dumps(settings_data))
    await settings.guild_load(default_guild)

    for k, v in settings_data.items():
        assert settings.guild_get(default_guild, k, None) == v


@pytest.mark.asyncio
async def test_guild_set(settings: Settings, mock_file, settings_data, default_guild):
    for k, v in settings_data.items():
        await settings.guild_set(default_guild, k, v)

    mock_file.write.assert_called_with(json.dumps(settings_data))


@pytest.mark.asyncio
async def test_guild_get(settings: Settings, mock_file, settings_data, default_guild):
    for k, v in settings_data.items():
        await settings.guild_set(default_guild, k, v)

    for k, v in settings_data.items():
        assert settings.guild_get(default_guild, k, None) == v


@pytest.mark.asyncio
async def test_guild_store(settings: Settings, mock_file, settings_data, default_guild):
    for k, v in settings_data.items():
        await settings.guild_set(default_guild, k, v)

    mock_file.write.reset_mock()

    await settings.guild_store(default_guild)

    mock_file.write.assert_called_with(json.dumps(settings_data))


@pytest.mark.asyncio
async def test_delete(
    settings: Settings, mock_file, settings_data, inject_mock_file_read_data
):
    inject_mock_file_read_data(json.dumps(settings_data))
    await settings.load()

    key = next(iter(settings_data))

    await settings.delete(key)

    mock_file.write.assert_called_with(
        json.dumps({k: settings_data[k] for k in settings_data if k != key})
    )


@pytest.mark.asyncio
async def test_guild_delete(
    settings: Settings,
    mock_file,
    settings_data,
    inject_mock_file_read_data,
    default_guild,
):
    inject_mock_file_read_data(json.dumps(settings_data))
    await settings.guild_load(default_guild)

    key = next(iter(settings_data))

    await settings.guild_delete(default_guild, key)

    mock_file.write.assert_called_with(
        json.dumps({k: settings_data[k] for k in settings_data if k != key})
    )


@pytest.mark.asyncio
async def test_missing_guild(
    settings: Settings,
):
    with pytest.raises(commands.NoPrivateMessage):
        settings.guild_get(None, "key", None)


@pytest.mark.asyncio
async def test_invalid_guild(
    settings: Settings,
    other_guild,
):
    with pytest.raises(commands.GuildNotFound):
        settings.guild_get(other_guild, "key", None)


@pytest.mark.asyncio
async def test_coalesce(
    settings: Settings,
    settings_data,
    inject_mock_file_read_data,
    default_guild,
):
    inject_mock_file_read_data(json.dumps(settings_data))
    await settings.load()

    key = next(iter(settings_data))
    different_value = "different value"
    original_value = settings_data[key]

    assert settings.get(key, None) == original_value
    assert settings.guild_get(default_guild, key, None) is None
    assert settings.coalesce(default_guild, key, None) == original_value

    settings_data[key] = different_value

    inject_mock_file_read_data(json.dumps(settings_data))
    await settings.guild_load(default_guild)

    assert settings.get(key, None) == original_value
    assert settings.guild_get(default_guild, key, None) == different_value
    assert settings.coalesce(default_guild, key, None) == different_value


@pytest.mark.asyncio
@pytest.mark.isowner(False)
async def test_hidden_keys(settings: Settings, hidden_key, default_guild_context):
    with pytest.raises(commands.BadArgument):
        await legacy_invoke_command(
            settings, "command_get", default_guild_context, hidden_key
        )
    with pytest.raises(commands.BadArgument):
        await legacy_invoke_command(
            settings, "command_set", default_guild_context, hidden_key, "value"
        )


@pytest.mark.asyncio
@pytest.mark.isowner(False)
async def test_restrict(
    settings: Settings, settings_data, inject_mock_file_read_data, default_guild_context
):
    inject_mock_file_read_data(json.dumps(settings_data))
    await settings.load()

    key = next(iter(settings_data))

    await settings.restrict(key)

    with pytest.raises(commands.NotOwner):
        await legacy_invoke_command(
            settings, "command_guild_set", default_guild_context, key, "some value"
        )
