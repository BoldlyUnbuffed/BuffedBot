import discord
import json

from discord.ext import commands
from buffedbot.help import CustomHelpCommand
from buffedbot.system import System

with open("config.json") as f:
    config = json.loads(f.read())

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!", intents=intents, help_command=CustomHelpCommand()
)

permissions = discord.Permissions()
permissions.manage_messages = True
permissions.send_messages = True
permissions.read_messages = True
permissions.embed_links = True
permissions.attach_files = True
permissions.read_message_history = True

print(
    f"OAuth URL: {discord.utils.oauth_url(1090857421213282315, permissions=permissions)}"
)

System.run(bot, config)
