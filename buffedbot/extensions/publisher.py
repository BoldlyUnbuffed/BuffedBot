import asyncio 

from discord.ext import commands
from discord import ChannelType

class Publisher(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auto_publish = True
        self.auto_publish_delay = 5 

    @commands.Cog.listener()
    async def on_message(self, message):
        if not self.auto_publish:
            return
        if message.author.id == self.bot.user.id:
            # Do not auto-publish your own messages
            return
        if message.channel.type != ChannelType.news:
            return 
        reply = await message.reply(
            f'I will auto publish this message in {self.auto_publish_delay} minutes. Delete it to prevent it from being published.'
        )
        async with message.channel.typing():
            await asyncio.sleep(self.auto_publish_delay * 60)
        await message.publish()
        await reply.delete()

async def setup(bot):
    await bot.add_cog(Publisher(bot))

async def teardown(bot):
    await bot.remove_cog('Publisher')
