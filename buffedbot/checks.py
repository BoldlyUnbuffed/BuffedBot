from discord.ext import commands

def is_guild_owner():
    async def predicate(ctx):
        return ctx.guild and ctx.guild.owner == ctx.author
    return commands.check(predicate)

def always_fails():
    async def predicate(ctx):
        return False
    return commands.check(predicate)