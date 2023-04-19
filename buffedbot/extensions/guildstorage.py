from discord.ext import commands
from aiopath import AsyncPath
import os

GUILD_STORAGE_ROOT = f"guilds{os.sep}"
GUILD_ID_TOKEN = "{guild_id}"
GUILD_STORAGE_PATTERN = f"{GUILD_STORAGE_ROOT}{GUILD_ID_TOKEN}{os.sep}"


async def rmtree(name):
    f = AsyncPath(name)
    if not await f.is_dir():
        return await f.unlink(missing_ok=True)

    async for i in f.iterdir():
        await rmtree(i)

    await f.rmdir()


class GuildStorage(commands.Cog, name="guildstorage"):
    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await GuildStorageCog.create_guild_storage(guild)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        await GuildStorageCog.delete_guild_storage(guild)

    @staticmethod
    def get_guild_storage_path(guild):
        if not guild:
            raise commands.NoPrivateMessage()
        assert hasattr(
            guild, "id"
        ), "Object has no id attribute and is not a valid guild"
        return GUILD_STORAGE_PATTERN.replace(GUILD_ID_TOKEN, str(guild.id))

    @staticmethod
    async def delete_guild_storage(guild):
        path = GuildStorageCog.get_guild_storage_path(guild)
        return await rmtree(path)

    @staticmethod
    async def create_guild_storage(guild):
        path = GuildStorageCog.get_guild_storage_path(guild)
        await AsyncPath(path).mkdir(parents=True, exist_ok=True)
        return path


async def setup(bot):
    await bot.add_cog(GuildStorage(bot))


async def teardown(bot):
    await bot.remove_cog("GuildStorage")
