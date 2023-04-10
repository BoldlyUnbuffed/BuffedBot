from buffedbot.extensions.settings import Settings
import json

import pytest
import pytest_asyncio

@pytest_asyncio.fixture
async def settings(
    mock_bot,
    mock_guild_storage, 
    mock_file_inject_empty_settings_data, 
    mock_async_path_exists
):
    settings = Settings(mock_bot)
    await settings.cog_load()
    return settings

@pytest.fixture
def mock_file_inject_empty_settings_data(
    empty_settings_data, 
    inject_mock_file_read_data
):
    inject_mock_file_read_data(json.dumps(empty_settings_data))

@pytest.fixture(params=[
    {"key":"value"},
    {"key":"value", "another":"value"}, 
    {"complex":{"data":"here"}}
])
def settings_data(request):
    return request.param

@pytest.fixture
def empty_settings_data():
    return {}
    
@pytest.mark.asyncio
async def test_create_settings(settings: Settings):
    assert settings is not None
    assert settings.settings is not None
    assert len(settings.settings) == 0

@pytest.mark.asyncio
async def test_load(
    settings: Settings, 
    settings_data, 
    inject_mock_file_read_data
):
    inject_mock_file_read_data(json.dumps(settings_data))

    await settings.load()
    for k,v in settings_data.items():
        assert settings.get(k, None) == v

@pytest.mark.asyncio
async def test_set(settings: Settings, mock_file, settings_data):
    for k,v in settings_data.items():
        await settings.set(k, v)

    mock_file.write.assert_called_with(json.dumps(settings_data))

@pytest.mark.asyncio
async def test_get(settings: Settings, mock_file, settings_data):
    for k,v in settings_data.items():
        await settings.set(k, v)

    for k,v in settings_data.items():
        assert settings.get(k, None) == v

@pytest.mark.asyncio
async def test_store(settings: Settings, mock_file, settings_data):
    for k,v in settings_data.items():
        await settings.set(k, v)

    mock_file.write.reset_mock()

    await settings.store()

    mock_file.write.assert_called_with(json.dumps(settings_data))

@pytest.mark.asyncio
async def test_guild_load(
    settings: 
    Settings, 
    settings_data, 
    inject_mock_file_read_data, 
    default_guild
):
    inject_mock_file_read_data(json.dumps(settings_data))
    await settings.guild_load(default_guild)

    for k,v in settings_data.items():
        assert settings.guild_get(default_guild, k, None) == v

@pytest.mark.asyncio
async def test_guild_set(
    settings: Settings, 
    mock_file, 
    settings_data, 
    default_guild
):
    for k,v in settings_data.items():
        await settings.guild_set(default_guild, k, v)

    mock_file.write.assert_called_with(json.dumps(settings_data))

@pytest.mark.asyncio
async def test_guild_get(
    settings: Settings, 
    mock_file, 
    settings_data, 
    default_guild
):
    for k,v in settings_data.items():
        await settings.guild_set(default_guild, k, v)

    for k,v in settings_data.items():
        assert settings.guild_get(default_guild, k, None) == v

@pytest.mark.asyncio
async def test_guild_store(
    settings: Settings, 
    mock_file,  
    settings_data, 
    default_guild
):
    for k,v in settings_data.items():
        await settings.guild_set(default_guild, k, v)

    mock_file.write.reset_mock()

    await settings.guild_store(default_guild)

    mock_file.write.assert_called_with(json.dumps(settings_data))