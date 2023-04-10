import sys
import os
import asyncio
import logging
import discord

from aiopath import AsyncPath, PurePath
from discord.ext import commands
from watchfiles import awatch, Change

class System(commands.Cog, name='system'):
    def __init__(self, bot):
        self.bot = bot
        ext_dir = get_ext_dir()
        if not ext_dir in sys.path:
            sys.path.append(ext_dir)

    async def cog_check(self, ctx):
        return await commands.is_owner().predicate(ctx)

    async def load_extension(self, ext):
        if ext not in self.bot.extensions:
            print(f'+ Loading {ext}')
            await self.bot.load_extension(ext)

    async def unload_extension(self, ext):
        if ext in self.bot.extensions:
            print(f'- Unloading {ext}')
            await self.bot.unload_extension(ext)

    async def reload_extension(self, ext):
        if ext in self.bot.extensions:
            print(f'o Reloading {ext}')
            await self.bot.reload_extension(ext)


    @commands.group(name='system')
    async def system(self, ctx):
        pass

    @system.command(name='unload')
    async def extensions_unload(self, ctx, ext):
        async with ctx.typing():
            await self.unload_extension(ext)
            await ctx.reply(f'Unloaded {ext}.')

    @system.command(name='load')
    async def extensions_load(self, ctx, ext):
        async with ctx.typing():
            await self.load_extension(ext)
            await ctx.reply(f'Loaded {ext}.')

    @system.command(name='reload')
    async def extensions_reload(self, ctx, ext):
        async with ctx.typing():
            await self.reload_extension(ext)
            await ctx.reply(f'Reloaded {ext}.')

    async def load_extensions(self):
        print('Loading extensions...')
        exts = await get_extensions()
        for ext in exts:
            await self.load_extension(ext)
        print('Done.')

    async def unload_extensions(self):
        print('Unloading extensions...')
        exts = await get_extensions()
        exts.reverse()
        for ext in exts:
            # We are awaiting each extension at a time to maintain order
            await self.unload_extension(ext)
        print('Done unloading extensions.')

    @staticmethod
    async def start(bot, config):
        discord.utils.setup_logging()
        
        @bot.event
        async def on_ready():
            print(f'We have logged in as {bot.user}')
            await bot.add_cog(System(bot))
            await bot.get_cog('system').load_extensions()

        async def watch():
            ext_dir = get_ext_dir()
            if not await AsyncPath(ext_dir).exists():
                return

            async for changes in awatch(ext_dir, recursive=True):
                for change in changes:
                    if not change[0] == Change.modified:
                        continue
                    ext = to_extension_name(change[1])
                    print(f'Change detected in {change[1]} ({ext}).') 
                    if not ext in bot.extensions:
                        continue
                    print(f'-> Reloading extension {ext}...', end='')
                    try:
                        await bot.reload_extension(ext)
                        print(f' done.')
                    except Exception as e:
                        print(f'-> Failed.')
                        logging.exception(f'Failed to reload extensions {ext}')

        await asyncio.gather(*[bot.start(config['token']), watch()])

    @staticmethod
    def run(bot, config):
        asyncio.run(System.start(bot, config))

def get_basedir():
    # This must remain in sync with the actual system.py location
    return os.path.dirname(PurePath(__file__).parent)

def to_extension_name(path):
    return str(PurePath(path).relative_to(get_ext_dir())).replace(os.sep, '.').removesuffix('.__init__.py').removesuffix('.py')

def get_ext_dir():
    return str(PurePath(get_basedir(), 'buffedbot', 'extensions'))

async def get_extensions() -> list[str]:
    extensions = []
    dir = AsyncPath(get_ext_dir())
    async for f in dir.iterdir():
        if await f.is_dir():
            if f.name.startswith('__'):
                continue
            if not await f.joinpath('__init__.py').exists():
                continue
        elif not f.match('*.py'):
            continue
        extensions.append(to_extension_name(f))
    extensions.sort()
    return extensions