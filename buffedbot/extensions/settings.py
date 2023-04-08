from discord.ext import commands
from buffedbot.checks import is_guild_owner, unreleased
from buffedbot.strings import SOMETHING_WENT_WRONG
from aiopath import AsyncPath, PurePath
from asyncio import gather
import aiofiles
import json
import logging

SETTINGS_FILENAME = 'settings.json'

UNKNOWN_SETTING = '*Unknown setting*'
SETTING_DELETED = '*Setting deleted*'
SETTING_UPDATED = '*Setting updated*'
SETTING_RESTRICTED = '*Setting restricted*'
SETTING_UNRESTRICTED = '*Setting unrestricted*'
NO_SETTINGS = '*No settings*'
SETTINGS_HEADER = '**Settings**'
SETTING_DOES_NOT_EXIST = 'This setting does not exist'

RESTRICTED_SETTINGS_KEY = '__restricted_settings'
HIDDEN_KEYS = [RESTRICTED_SETTINGS_KEY]

def get_settings_list(settings, restricted_list):
    if not len(settings):
        return NO_SETTINGS
    
    body = '\n'.join([f'{k}{"*" if k in restricted_list else ""} = {settings[k]}' for k in settings if k not in HIDDEN_KEYS])
    return f'{SETTINGS_HEADER}\n' + body


class Settings(commands.Cog, name='settings'):
    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def cog_load(self):
        self.settings = dict()

        guilds = self.bot.guilds
        self.guild_settings = dict([(guild.id, dict()) for guild in guilds])

        loaders = [self.guild_load(guild) for guild in guilds]
        loaders.append(self.load())

        await gather(*loaders)

    @commands.group(name='settings')
    @unreleased()
    @commands.check_any(is_guild_owner(), commands.is_owner())
    async def command_settings(self, ctx):
        pass

    @command_settings.command(name='coalesce')
    async def command_coalesce(self, ctx, setting):
        await ctx.reply(self.coalesce(ctx.guild, setting, None))

    @command_settings.command(name='load')
    @commands.is_owner()
    async def command_load(self, ctx):
        await self.load()

    @command_settings.command(name='delete')
    @commands.is_owner()
    async def command_delete(self, ctx, setting):
        self.check_is_hidden(ctx, setting)
        if not await self.delete(setting):
            raise commands.BadArgument(SETTING_DOES_NOT_EXIST)
        await ctx.reply(SETTING_DELETED)

    @command_settings.command(name='store')
    @commands.is_owner()
    async def command_store(self, ctx):
        pass

    @command_settings.command(name='list')
    @commands.is_owner()
    async def command_list(self, ctx):
        restricted_settings = self.get_restricted_settings()
        await ctx.reply(get_settings_list(self.settings, restricted_settings))

    @command_settings.command(name='get')
    @commands.is_owner()
    async def command_get(self, ctx, setting):
        self.check_is_hidden(ctx, setting)
        await ctx.reply(self.get(setting, UNKNOWN_SETTING))

    @command_settings.command(name='set')
    @commands.is_owner()
    async def command_set(self, ctx, setting, value):
        self.check_is_hidden(ctx, setting)
        await self.set(setting, value)
        await ctx.reply(SETTING_UPDATED)

    @command_settings.command(name='restrict')
    @commands.is_owner()
    async def command_restrict(self, ctx, setting):
        async with ctx.typing():
            await self.restrict(setting)
            await ctx.reply(SETTING_RESTRICTED)
    
    @command_settings.command(name='unrestrict')
    @commands.is_owner()
    async def command_unrestrict(self, ctx, setting):
        async with ctx.typing():
            await self.unrestrict(setting)
            await ctx.reply(SETTING_UNRESTRICTED)


    async def load(self):
        if not await AsyncPath(SETTINGS_FILENAME).exists():
            return
        async with aiofiles.open(SETTINGS_FILENAME, 'r') as f:
            self.settings = json.loads(await f.read())

    async def store(self):
        async with aiofiles.open(SETTINGS_FILENAME, 'w') as f:
            await f.write(json.dumps(self.settings))

    async def delete(self, setting):
        if not setting in self.settings:
            return False
        del self.settings[setting]
        await self.store()
        return True

    def get(self, setting, default):
        if not setting in self.settings:
            return default
        return self.settings[setting]

    async def set(self, setting, value):
        self.settings[setting] = value
        await self.store()

    def get_restricted_settings(self):
        return self.get(RESTRICTED_SETTINGS_KEY, [])

    def is_restricted_setting(self, setting):
        return setting in self.get_restricted_settings()

    async def restrict(self, setting):
        restricted_settings = set(self.get(RESTRICTED_SETTINGS_KEY, []))
        restricted_settings.add(setting)
        await self.set(RESTRICTED_SETTINGS_KEY, list(restricted_settings))

        deletes = [self.guild_delete(guild, setting) for guild in self.bot.guilds if self.guild_get(guild, setting, None) != None]
        await gather(*deletes)

    async def unrestrict(self, setting):
        restricted_settings = self.get(RESTRICTED_SETTINGS_KEY, [])
        restricted_settings.remove(setting)

        await self.set(RESTRICTED_SETTINGS_KEY, restricted_settings)

    @command_settings.group(name='server', aliases=['guild'])
    async def guild_command(self, ctx):
        pass

    @guild_command.command(name='store')
    @commands.is_owner()
    async def command_guild_store(self, ctx):
        await self.guild_store(ctx.guild)

    @guild_command.command(name='load')
    @commands.is_owner()
    async def command_guild_load(self, ctx):
        await self.guild_load(ctx.guild)

    @guild_command.command(name='set')
    async def command_guild_set(self, ctx, setting, value):
        self.check_is_hidden(ctx, setting)

        await self.check_is_restricted(ctx, setting)

        await self.guild_set(ctx.guild, setting, value)
        await ctx.reply(SETTING_UPDATED)

    @guild_command.command(name='delete')
    async def command_guild_delete(self, ctx, setting):
        self.check_is_hidden(ctx, setting)

        await self.check_is_restricted(ctx, setting)

        if not await self.guild_delete(ctx.guild, setting):
            raise commands.BadArgument(SETTING_DOES_NOT_EXIST)
        await ctx.reply(SETTING_DELETED)

    @guild_command.command(name='get')
    async def command_guild_get(self, ctx, setting):
        self.check_is_hidden(ctx, setting)
        await ctx.reply(self.guild_get(ctx.guild, setting, UNKNOWN_SETTING))

    @guild_command.command(name='list')
    async def command_guild_list(self, ctx):
        settings = self.get_guild_settings(ctx.guild)
        restricted_settings = self.get_guild_restricted_settings(ctx.guild)
        await ctx.reply(get_settings_list(settings, restricted_settings))

    def get_guild_restricted_settings(self, guild):
        return self.guild_get(guild, RESTRICTED_SETTINGS_KEY, [])

    def is_guild_restricted_setting(self, guild, setting):
        return setting in self.get_guild_restricted_settings(guild)

    # TODO: Look into turning this into a decorator check?
    async def check_is_restricted(self, ctx, setting):
        is_guild_restricted_setting = self.is_guild_restricted_setting(
            ctx.guild,
            setting
        )
        is_restricted_setting = self.is_restricted_setting(setting)
        is_owner = await commands.is_owner().predicate(ctx)
        if is_restricted_setting and not is_owner:
            raise commands.NotOwner('This setting has been restricted from beeing overridden. Please contact the bot owner.')
        if is_guild_restricted_setting and not is_owner:
            raise commands.NotOwner('Your server has been restricted from changing this setting. Please contact the bot owner.')

    def check_is_hidden(self, ctx, setting):
        if setting in HIDDEN_KEYS:
            raise commands.BadArgument(SETTING_DOES_NOT_EXIST)

    async def guild_restrict(self, guild, setting):
        restricted_settings = set(self.guild_get(
            guild, 
            RESTRICTED_SETTINGS_KEY,
            [])
        )
        restricted_settings.add(setting)
        await self.guild_set(guild, RESTRICTED_SETTINGS_KEY, list(restricted_settings))

    async def guild_unrestrict(self, guild, setting):
        restricted_settings = set(self.guild_get(
            guild, 
            RESTRICTED_SETTINGS_KEY,
            [])
        )
        restricted_settings.remove(setting)
        await self.guild_set(guild, RESTRICTED_SETTINGS_KEY, list(restricted_settings))
    
    async def guild_set(self, guild, setting, value):
        settings = self.get_guild_settings(guild)
        settings[setting] = value
        await self.guild_store(guild)

    def guild_get(self, guild, setting, default):
        settings = self.get_guild_settings(guild)
        if not setting in settings:
            return default
        return settings[setting]

    async def guild_delete(self, guild, setting):
        settings = self.get_guild_settings(guild)
        if not setting in settings:
            return False
        del settings[setting]
        await self.guild_store(guild)
        return True

    async def guild_load(self, guild):
        if not guild:
            raise commands.NoPrivateMessage()
        if not guild.id:
            raise commands.GuildNotFound(guild)
        filepath = self.get_guild_settings_filepath(guild)

        if not await AsyncPath(filepath).exists():
            return
        async with aiofiles.open(filepath, 'r') as f:
            self.guild_settings[guild.id] = json.loads(await f.read())

    async def guild_store(self, guild):
        settings = self.get_guild_settings(guild)
        filepath = self.get_guild_settings_filepath(guild)
        async with aiofiles.open(filepath, 'w') as f:
            await f.write(json.dumps(settings))

    def get_guild_settings(self, guild):
        if not guild:
            raise commands.NoPrivateMessage()
        if not guild.id in self.guild_settings:
            raise commands.GuildNotFound(guild)
        return self.guild_settings[guild.id]

    def get_guild_settings_filepath(self, guild):
        storage = self.bot.get_cog('guildstorage')
        guild_storage = storage.get_guild_storage_path(guild)
        guild_settings_path = PurePath(guild_storage, SETTINGS_FILENAME)
        return str(guild_settings_path)
    
    def coalesce(self, guild, setting, default):
        return self.guild_get(guild, setting, self.get(setting, default))
    
    async def cog_command_error(self, ctx, error):
        # TODO: Better exception translation
        verbose_exceptions = [commands.UserInputError, commands.CheckFailure]
        if any([isinstance(error, E) for E in verbose_exceptions]):
            await ctx.reply(f'*{SOMETHING_WENT_WRONG}: {str(error)}*')
        elif isinstance(error, commands.CommandError):
            await ctx.reply(f'*{SOMETHING_WENT_WRONG}*')
        raise error
    
async def setup(bot):
    parent = bot
    await bot.get_cog('system').load_extension('guildstorage')
    await bot.add_cog(Settings(bot))

async def teardown(bot):
    await bot.remove_cog('Settings')