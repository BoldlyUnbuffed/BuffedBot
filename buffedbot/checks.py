from discord.ext import commands


def is_guild_owner_pred(guild, user):
    return guild is not None and guild.owner == user


def is_guild_owner():
    async def predicate(ctx):
        return is_guild_owner_pred(ctx.guild, ctx.author)

    return commands.check(predicate)


def is_test_guild():
    async def predicate(ctx):
        settings = ctx.bot.get_cog("settings")
        is_test_guild = False
        if settings and ctx.guild:
            is_test_guild = int(settings.get("test_guild", None)) == ctx.guild.id
        return is_test_guild

    return commands.check(predicate)


def unreleased():
    is_owner_p = commands.is_owner().predicate
    is_test_guild_p = is_test_guild().predicate

    async def predicate(ctx):
        return await is_test_guild_p(ctx) or await is_owner_p(ctx)

    return commands.check(predicate)


def always_fails():
    async def predicate(ctx):
        return False

    return commands.check(predicate)
