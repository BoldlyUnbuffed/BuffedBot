# Buffed Bot
A custom Discord bot for the Boldly Unbuffed community server. Come join our community to see it in action!

## Running the bot
If you would like to run your own instance of Buffed Bot, follow these simple steps:

1. Clone the Buffed Bot source code:

   ```git clone https://github.com/BoldlyUnbuffed/buffed-bot.git```

2. Install it's dependencies:

   ```pip install -r requirements.txt```

3. Follow the steps outlined in [this guide](https://discord.com/developers/docs/getting-started) to create a Discord application and retrieve a bot token. Create a config.json file and set the token as the value on the "token" key:

   ```echo '{"token": "YOUR_BOT_TOKEN_HERE"}' > config.json```

5. Run your bot.

   ```python buffed-bot.py```

6. Copy and paste the OAuth URL into your browser to invite the bot to your server and provide it the required permissions.

## Running unit tests
To make changes and validate them, follow these simple steps:

1. Clone the Buffed Bot source code:

   ```git clone https://github.com/BoldlyUnbuffed/buffed-bot.git```

2. Install it's development dependencies:

   ```pip install -r requirements_dev.txt```

3. Make changes

4. Run tests

   ```python -m pytest```

## Join Our Community!
Buffed Bot is being developed as a tool for the Boldly Unbuffed community. [Boldly Unbuffed](https://boldlyunbuffed.com/yt) is a YouTube gaming channel focusing on a technical and engineering approach to games. Currently we are playing Space Engineers mixed in with some scripting and programming in the Space Engineers scripting and modding API.

If you would like to support this or any other of the Boldly Unbuffed projects, please checkout our [Patreon](https://boldlyunbuffed.com/patreon) or [Buy Me A Coffe](https://boldlyunbuffed.com/coffee)!