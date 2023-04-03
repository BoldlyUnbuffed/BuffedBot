from discord.ext import commands

def is_collapseable_cog(cog, get_commands): 
    if not hasattr(cog, 'qualified_name'):
        return False
    if len(get_commands(cog)) != 1:
        return False
    if cog.qualified_name != get_commands(cog)[0].name:
        return False
    if not isinstance(get_commands(cog)[0], commands.Group):
        return False

    return True

# Implements a better help command based on the DefaultHelpCommand
# The more I am working with Discord.py, the more I hate how Cogs
# intermingle UI and programming paradigms. 
# On the one hand, Cogs are a great way to organize code, share it
# between bots and between different cogs, but on the other hand
# they are tightly coupled with the UI through the DefaultHelpCommand
# The fact that the cog name is both used as a key to access a cog
# in code and used as the heading in the help menu makes me a little
# sick.
# This help system will look for cogs that have the same name as the
# lone group command in them and "unroll" the group command.
# Queries for cogs that match these conditions will redirect to the
# group help.
# Depends on PR https://github.com/Rapptz/discord.py/pull/9330
class CustomHelpCommand(commands.DefaultHelpCommand):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_bot_mapping(self):
        mapping = super().get_bot_mapping()

        for cog in mapping:
            if not is_collapseable_cog(cog, lambda c: mapping[c]):
                continue
            mapping[cog] = list(mapping[cog][0].commands)

        return mapping

    async def send_cog_help(self, cog, /): 
        if is_collapseable_cog(cog, lambda c: c.get_commands()):
            return await super().send_group_help(cog.get_commands()[0])
        return await super().send_cog_help(cog)