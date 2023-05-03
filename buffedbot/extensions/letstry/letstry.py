from collections import namedtuple
from datetime import datetime, timedelta, timezone
from discord.ext import commands
from aiopath import PurePath
from buffedbot.checks import is_guild_owner
from buffedbot.strings import SOMETHING_WENT_WRONG
from buffedbot.errors import GameNotFoundError
from buffedbot.extensions.steam import Game as SteamGame
from asyncio import gather
from sqlite3 import IntegrityError
from typing import (
    Literal,
    TypeVar,
    Type,
    Optional,
    cast,
    Mapping,
    Iterable,
)
from dataclasses import dataclass
from contextlib import asynccontextmanager
from pytimeparse import parse as timeparse
from functools import partial
import dataclasses
import discord
import re
import itertools

import aiofiles
import os

STEAM_STORE_URL_PATTERN = r"^(https?://)?store\.steampowered\.com/app/[0-9]+.+$"
URL_PATTERN = r"^https?://.+$"


class InvalidStateError(IntegrityError):
    pass


class DuplicationError(IntegrityError):
    pass


# Indefinite article
def an(thing: str) -> str:
    if not len(thing):
        return thing
    if thing[0].lower() in ["a", "o", "u", "i"]:
        return f"an {thing}"
    return f"a {thing}"


GameState = Literal["submitted", "accepted", "rejected", "elected", "done", "orphaned"]

BallotState = Literal["staging", "open", "closed"]


def to_discord_relative_time(dt: datetime):
    return f"<t:{int(dt.timestamp())}:R>"


def to_discord_datetime(dt: datetime):
    return f"<t:{int(dt.timestamp())}:D>"


def to_datetime_utc(s: str):
    return datetime.fromisoformat(f"{s}+00:00")


def join(items: Iterable[str], sep: str = ",") -> str:
    return sep.join(items)


T = TypeVar("T")


def notnone(v: Optional[T]) -> T:
    if v is None:
        raise ValueError
    return v


def sqldatarow(
    table_name,
    *,
    primary_key: Optional[tuple[str, ...]] = None,
    view_name: Optional[str] = None,
):
    def wrapper(parent):
        nonlocal primary_key
        if primary_key is None:
            primary_key = (dataclasses.fields(parent)[0].name,)

        class _(parent):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)

            @classmethod
            @property
            def table_name(cls):
                return table_name

            @classmethod
            @property
            def view_name(cls):
                return view_name if view_name is not None else cls.table_name

            @classmethod
            def where_expr(
                cls,
                where: Iterable[str],
                *,
                logic: Literal["OR", "AND"] = "OR",
            ) -> str:
                comparisons = cls.placeholder_compare(where)
                if not len(comparisons):
                    return ""
                return f"""
                    WHERE
                        {join(comparisons, sep=f' {logic} ')}
                """

            def primary_key_match(self):
                return {k: self.__dict__[k] for k in notnone(primary_key)}

            @staticmethod
            def placeholder_compare(names: Iterable[str]) -> list[str]:
                if isinstance(names, Mapping):
                    return [f"{k} = :{names[k]}" for k in names]
                return [f"{v} = :{v}" for v in names]

            @classmethod
            def from_row(cls, cursor, row: tuple):
                data = {k: v for k, v in zip(cls.column_names, row)}
                return cls(**data)

            @classmethod
            def from_partial(cls, partial: dict):
                for k in cls.column_names:
                    if not k in partial:
                        partial[k] = None
                return cls(**partial)

            @classmethod
            @property
            def column_names(cls):
                return (f.name for f in dataclasses.fields(cls))

            @classmethod
            @property
            def non_computed_column_names(cls):
                return (
                    f.name
                    for f in dataclasses.fields(cls)
                    if not "virtual" in f.metadata
                )

            @staticmethod
            def placeholders(names: Iterable[str]):
                return [f":{n}" for n in names]

            @classmethod
            def select_stmt(
                cls, where: Iterable[str] = [], *, logic: Literal["AND", "OR"] = "OR"
            ) -> str:
                return f"""
                    SELECT
                        {join(cls.column_names)}
                    FROM
                        {cls.view_name}
                    {cls.where_expr(where, logic=logic)}
                """

            @classmethod
            @asynccontextmanager
            async def select(
                cls, db, where: Mapping[str, str], logic: Literal["AND", "OR"] = "OR"
            ):
                async with db.execute(
                    cls.select_stmt(where.keys(), logic=logic), where
                ) as cursor:
                    cursor.row_factory = cls.from_row
                    yield cursor

            @classmethod
            async def select_fetchone(
                cls, db, where: Mapping[str, str], logic: Literal["AND", "OR"] = "OR"
            ):
                async with cls.select(db, where, logic) as cursor:
                    return await cursor.fetchone()

            async def refresh(self, db):
                where = self.primary_key_match()
                new = await self.select_fetchone(db, where)
                self.__dict__.update(new.__dict__)
                return self

            @classmethod
            def exists_stmt(
                cls, where: Iterable[str] = [], *, logic: Literal["AND", "OR"] = "OR"
            ) -> str:
                return f"""
                    SELECT
                        COUNT(1)
                    WHERE EXISTS (
                        SELECT
                            1
                        FROM
                            {cls.table_name}
                        {cls.where_expr(where, logic=logic)}
                    )
                """

            @classmethod
            async def exists(
                cls, db, where: Mapping[str, str], *, logic: Literal["AND", "OR"] = "OR"
            ) -> bool:
                async with db.execute(
                    cls.exists_stmt(where.keys(), logic=logic), where
                ) as cursor:
                    result = await cursor.fetchone()
                return result[0]

            @classmethod
            def join_select_stmt(
                cls,
                foreign_key: str,
                where: Iterable[str],
                logic: Literal["OR", "AND"] = "OR",
            ):
                foreign_cls = cls.get_foreign_key_class(foreign_key)

                where = {f"{cls.view_name}.{k}": k for k in where}
                columns = itertools.chain(
                    (f"{cls.view_name}.{c}" for c in cls.column_names),
                    (f"{foreign_cls.view_name}.{c}" for c in foreign_cls.column_names),
                )

                return f"""
                    SELECT
                        {join(columns)}
                    FROM {foreign_cls.view_name}
                    INNER JOIN {cls.table_name} ON {foreign_cls.view_name}.{foreign_key} = {cls.view_name}.{foreign_key}
                    {cls.where_expr(where, logic=logic)}
                """

            @classmethod
            def get_foreign_key_class(cls, key: str) -> Type["_"]:
                field = next(
                    (field for field in dataclasses.fields(cls) if field.name == key),
                    None,
                )
                if field is None or "foreign_key" not in field.metadata:
                    raise ValueError(f"Field {key} is not a foreign key field")
                return field.metadata["foreign_key"]

            @classmethod
            @asynccontextmanager
            async def join_select(
                cls,
                db,
                foreign_key: str,
                where: Iterable[str],
                logic: Literal["OR", "AND"] = "OR",
            ):
                sql = cls.join_select_stmt(foreign_key, where, logic)
                foreign_cls = cls.get_foreign_key_class(foreign_key)
                cls_column_count = sum(1 for _ in cls.column_names)

                async with db.execute(sql, where) as cursor:
                    cursor.row_factory = lambda cursor, row: (
                        cls.from_row(cursor, row[0:cls_column_count]),
                        foreign_cls.from_row(cursor, row[cls_column_count:]),
                    )
                    yield cursor

            async def join_fetchone(self, db, foreign_key):
                where = self.primary_key_match()
                async with self.join_select(db, foreign_key, where) as cursor:
                    return await cursor.fetchone()

            def insert_stmt(self) -> str:
                filtered_columns = [
                    k for k, v in self.placeholder_values.items() if v is not None
                ]
                return f"""
                    INSERT INTO
                        {self.table_name} ({join(filtered_columns)})
                    VALUES
                        ({join(self.placeholders(filtered_columns))})
                """

            async def insert(self, db):
                stmt = self.insert_stmt()
                async with db.execute(
                    self.insert_stmt(), self.placeholder_values
                ) as cursor:
                    await db.commit()
                    if len(notnone(primary_key)) == 1:
                        setattr(self, notnone(primary_key)[0], cursor.lastrowid)
                return self

            @classmethod
            def update_stmt(
                cls,
                where: Iterable[str] = [],
                values: Optional[Mapping[str, str]] = None,
            ):
                if values is None:
                    placeholders = cls.non_computed_column_names
                else:
                    placeholders = values.keys()
                sql = f"""
                    UPDATE
                        {cls.table_name}
                    SET
                        {join(cls.placeholder_compare(placeholders))}
                    {cls.where_expr(where)}
                """
                return sql

            async def update(self, db):
                cursor = await db.execute(
                    self.update_stmt(self.primary_key_match().keys()),
                    self.placeholder_values,
                )
                await db.commit()
                return cursor.rowcount

            async def delete(self, db):
                where = self.primary_key_match()
                sql = self.delete_stmt(where.keys())
                cursor = await db.execute(sql, where)
                await db.commit()
                return cursor.rowcount

            @classmethod
            def delete_stmt(cls, where: Iterable[str]):
                return f"""
                    DELETE FROM
                        {cls.table_name}
                    {cls.where_expr(where)}
                """

            @property
            def placeholder_values(self):
                return {
                    name: getattr(self, name) for name in self.non_computed_column_names
                }

        return _

    return wrapper


def virtual():
    """Marks a sqldatarow field as virtual. Virtual fields can be read, but are not written."""
    return dataclasses.field(metadata={"virtual": True})


def foreign_key(cls):
    """Marks a sqldatarow field as a foreign key and what table/sqldatarow it references."""
    return dataclasses.field(metadata={"foreign_key": cls})


def make_interaction_context(interaction):
    return namedtuple("Context", ["author", "guild", "channel", "bot"])(
        interaction.user, interaction.guild, interaction.channel, interaction.client
    )


class LetsTryBallotVoteView(discord.ui.View):
    def __init__(self, db, ballot: "LetsTryBallot", embed_message, *, timeout=180):
        self.db = db
        self.ballot = ballot
        self.embed_message = embed_message
        super().__init__(timeout=timeout)

    async def on_vote_cast(self, button, game_id, interaction):
        vote = LetsTryBallotVotes(
            game_id=game_id,
            ballot_id=self.ballot.ballot_id,
            discord_user_id=interaction.user.id,
        )
        try:
            await vote.insert(self.db)
        except IntegrityError as ie:
            if "ballot not open" in str(ie):
                return await interaction.response.edit_message(
                    content=f"*{SOMETHING_WENT_WRONG}: Ballot not open.*",
                    view=None,
                    delete_after=3,
                )

        await interaction.response.edit_message(
            content=f"*☑️ Vote recorded.*", view=None, delete_after=3
        )

        if self.embed_message is not None:
            embed = await LetsTryBallotGame.as_embed(self.db, self.ballot)
            await self.embed_message.edit(embed=embed)

    def add(self, ballot_game: "LetsTryBallotGame", game: "LetsTryGame"):
        button = discord.ui.Button(
            label=game.name,
            style=discord.ButtonStyle.primary,
        )
        button.callback = partial(self.on_vote_cast, button, game.game_id)
        self.add_item(button)

    async def on_timeout(self):
        self.embed_message = None

    async def interaction_check(self, interaction):
        return await can_vote_ballots().predicate(make_interaction_context(interaction))

    async def on_error(self, interaction, error, item):
        verbose_exceptions = [commands.CheckFailure, IntegrityError]
        if any([isinstance(error, E) for E in verbose_exceptions]):
            return await interaction.response.send_message(
                f"*{SOMETHING_WENT_WRONG}: {str(error)}*", ephemeral=True
            )
        await gather(
            interaction.response.send_message(
                f"*{SOMETHING_WENT_WRONG}*", ephemeral=True
            ),
            super().on_error(interaction, error, item),
        )


class LetsTryBallotEditView(discord.ui.View):
    def __init__(self, db, ballot, *, timeout=180):
        super().__init__(timeout=timeout)

        self.db = db
        self.ballot = ballot

        match ballot.state:
            case "open":
                button = discord.ui.Button(
                    label="Close now", style=discord.ButtonStyle.danger
                )
                button.callback = partial(self.on_close_button_click, button)
                self.add_item(button)
            case "staging":
                button = discord.ui.Button(
                    label="Submit", style=discord.ButtonStyle.success
                )
                button.callback = partial(self.on_submit_button_click, button)
                self.add_item(button)
            case "submitted":
                button = discord.ui.Button(
                    label="Open now", style=discord.ButtonStyle.success
                )
                button.callback = partial(self.on_open_button_click, button)
                self.add_item(button)

    async def on_submit_button_click(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        pass

    async def on_close_button_click(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        pass

    async def on_open_button_click(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        pass

    async def interaction_check(self, interaction):
        return await can_manage_ballots().predicate(
            make_interaction_context(interaction)
        )

    def setMessage(self, message):
        self.message = message

    async def on_error(self, interaction, error, item):
        verbose_exceptions = [commands.CheckFailure, IntegrityError]
        if any([isinstance(error, E) for E in verbose_exceptions]):
            return await interaction.response.send_message(
                f"*{SOMETHING_WENT_WRONG}: {str(error)}*", ephemeral=True
            )
        await gather(
            interaction.response.send_message(
                f"*{SOMETHING_WENT_WRONG}*", ephemeral=True
            ),
            super().on_error(interaction, error, item),
        )

    async def on_timeout(self):
        if self.message:
            await self.message.edit(view=None)
            self.message = None
        return await super().on_timeout()


class LetsTryBallotVoteNowView(discord.ui.View):
    def __init__(self, db, ballot, *, timeout=180):
        super().__init__(timeout=timeout)
        self.db = db
        self.ballot = ballot

    @discord.ui.button(label="Vote now!", style=discord.ButtonStyle.primary, emoji="🗳️")
    async def vote_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        where = {
            "ballot_id": self.ballot.ballot_id,
            "discord_user_id": interaction.user.id,
        }
        async with LetsTryBallotVotes.join_select(
            self.db, "game_id", where, "AND"
        ) as cursor:
            async for _, game in cursor:
                return await interaction.response.send_message(
                    f'*❌ You have already voted for "{game.name}".*',
                    ephemeral=True,
                    delete_after=10,
                )

        where = self.ballot.primary_key_match()
        ballot = await LetsTryBallot.select_fetchone(self.db, where)

        view = LetsTryBallotVoteView(self.db, ballot, interaction.message)

        async with LetsTryBallotGame.join_select(self.db, "game_id", where) as cursor:
            async for ballot_game, game in cursor:
                view.add(ballot_game, game)

        await interaction.response.send_message(
            "Which game would you like to vote for?",
            view=view,
            ephemeral=True,
            delete_after=view.timeout,
        )

    def setMessage(self, message: discord.Message):
        self.message = message

    async def on_timeout(self):
        if self.message is not None:
            await self.message.edit(view=None)
        self.message = None
        return await super().on_timeout()


@sqldatarow("letstry_ballots", view_name="letstry_ballots_view")
@dataclass
class LetsTryBallot:
    ballot_id: int
    discord_thread_id: int
    date_created: str
    date_open: str
    date_close: str
    staging: int
    state: BallotState = virtual()

    def as_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=f"Lets Try Ballot", timestamp=to_datetime_utc(self.date_created)
        )
        embed.add_field(name="State", value=f"{self.state}")
        embed.add_field(
            name="Opens"
            if datetime.fromisoformat(self.date_open) > datetime.now()
            else "Opened",
            value=to_discord_relative_time(to_datetime_utc(self.date_open)),
        )
        embed.add_field(
            name="Closes"
            if datetime.fromisoformat(self.date_close) > datetime.now()
            else "Closed",
            value=to_discord_relative_time(to_datetime_utc(self.date_close)),
        )
        embed.add_field(name=" ", value=" ")
        return embed


@sqldatarow("letstry_games")
@dataclass
class LetsTryGame:
    game_id: int
    name: str
    url: str
    state: GameState

    def as_embed(self) -> discord.Embed:
        embed = discord.Embed(title=self.name, url=self.url)
        embed.add_field(
            name="Platform",
            value=f'{"Steam" if re.match(STEAM_STORE_URL_PATTERN, self.url) else "Other"}',
        )
        embed.add_field(name="State", value=self.state)
        return embed


@sqldatarow("letstry_ballot_games", primary_key=("ballot_id", "game_id"))
@dataclass
class LetsTryBallotGame:
    votes: int
    ballot_id: int = foreign_key(LetsTryBallot)
    game_id: int = foreign_key(LetsTryGame)

    @asynccontextmanager
    @staticmethod
    async def select_ballot_games(db, ballot: LetsTryBallot):
        where = ballot.primary_key_match()
        async with LetsTryBallotGame.join_select(db, "game_id", where) as cursor:
            yield cursor

    @staticmethod
    def add_to_embed(embed, edge: "LetsTryBallotGame", game: LetsTryGame):
        embed.add_field(
            name=game.name,
            value=f"[Link]({game.url})\n{edge.votes} votes",
            inline=False,
        )
        return embed

    @classmethod
    async def as_embed(cls, db, ballot: LetsTryBallot):
        embed = ballot.as_embed()
        async with cls.select_ballot_games(db, ballot) as cursor:
            async for edge, game in cursor:
                cls.add_to_embed(embed, edge, game)
        return embed

    @staticmethod
    async def create_edge(
        db, ballot: LetsTryBallot, game: LetsTryGame
    ) -> "LetsTryBallotGame":
        edge = LetsTryBallotGame.from_partial(
            {"game_id": game.game_id, "ballot_id": ballot.ballot_id}
        )
        try:
            return await edge.insert(db)
        except IntegrityError as ie:
            message = str(ie)
            if "game not open for ballots" in message:
                raise InvalidStateError(ie)
            elif "UNIQUE" in message:
                raise DuplicationError(ie)
            else:
                raise ie


@sqldatarow("letstry_ballot_votes", primary_key=("ballot_id", "discord_user_id"))
@dataclass
class LetsTryBallotVotes:
    discord_user_id: int
    ballot_id: int = foreign_key(LetsTryBallot)
    game_id: int = foreign_key(LetsTryGame)


@sqldatarow("letstry_proposals")
@dataclass
class LetsTryProposal:
    discord_user_id: int
    date_created: str
    game_id: int = foreign_key(LetsTryGame)


def split_url(input: str):
    arr = input.split(" ")
    url = None
    if len(arr) > 0 and re.match(URL_PATTERN, arr[-1]):
        url = arr[-1]
        arr = arr[:-1]
    return (url, " ".join(arr))


class NotBallotThread(commands.CheckFailure):
    pass


class CantManageBallots(commands.CheckFailure):
    pass


class CantVoteBallots(commands.CheckFailure):
    pass


def is_ballot_thread():
    async def predicate(ctx):
        db = ctx.bot.get_cog("letstry").get_guild_db(ctx.guild)
        if not await LetsTryBallot.exists(db, {"discord_thread_id": ctx.channel.id}):
            raise NotBallotThread(
                f"The command {ctx.command} can only be run from within a ballot thread."
            )
        return True

    return commands.check(predicate)


def can_manage_ballots():
    async def predicate(ctx):
        if not await is_guild_owner().predicate(ctx):
            raise CantVoteBallots("You do not have permission to manage ballots.")
        return True

    return commands.check(predicate)


def can_vote_ballots():
    async def predicate(ctx):
        voter = ctx.bot.get_cog("settings").guild_get(
            ctx.guild, "letstry-proposer-role", "@everyone"
        )
        if not await commands.has_role(voter).predicate(ctx):
            raise CantManageBallots("You do not have permission to vote ballots.")
        return True

    return commands.check(predicate)


def can_propose():
    async def predicate(ctx):
        proposer = ctx.bot.get_cog("settings").guild_get(
            ctx.guild, "letstry-proposer-role", "@everyone"
        )
        return await commands.has_role(proposer).predicate(ctx)

    return commands.check(predicate)


class LetsTry(
    commands.Cog,
    name="letstry",
    description="Lets Try is my short-form video series in which summarize my first hour of gameplay into a less than one minute video.",
):
    """Commands related to Lets Try voting"""

    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        return await commands.guild_only().predicate(ctx)

    @commands.group(name="letstry")
    async def letstry(self, ctx):
        """Commands to propose, vote on and manage Lets Try games"""
        pass

    @letstry.group(name="games")
    async def games(self, ctx):
        """Commands for proposing and managing Lets Try games."""
        pass

    @letstry.command(name="list")
    async def list(self, ctx, state: Optional[str]):
        """Shorthand for !letstry games list"""
        return await ctx.invoke(self.bot.get_command("letstry games list"), state=state)

    @letstry.command(name="ballots")
    async def ballots(self, ctx):
        """Lists ballots open for votes."""
        db = self.get_guild_db(ctx.guild)
        sql = f"""{LetsTryBallot.select_stmt()} WHERE state in ("open", "submitted")"""
        async with db.execute(sql) as cursor:
            cursor.row_factory = LetsTryBallot.from_row
            ballot = None
            async for ballot in cursor:
                view = LetsTryBallotVoteNowView(db, ballot)
                embed = ballot.as_embed()

                async with LetsTryBallotGame.join_select(
                    db, "game_id", ballot.primary_key_match()
                ) as cursor:
                    async for ballot_game, game in cursor:
                        LetsTryBallotGame.add_to_embed(embed, ballot_game, game)

                message = await ctx.reply(embed=embed, view=view, silent=True)
                view.setMessage(message)
            if ballot is None:
                await ctx.reply("*No ballots found.*")

    @can_propose()
    @letstry.command(name="propose")
    async def propose(
        self,
        ctx,
        *,
        name=commands.parameter(description="Name of the game to propose."),
    ):
        """Shorthand for !letstry games propose.

        See !help letstry games propose for details.

        """
        return await ctx.invoke(
            self.bot.get_command("letstry games propose"), name=name
        )

    @letstry.command(name="retract")
    async def retract(self, ctx):
        """Shorthand for !letstry games retract.

        See !help letstry games retract for details."""
        await ctx.invoke(
            self.bot.get_command("letstry games retract"),
        )

    @games.command(name="retract")
    async def games_retract(self, ctx):
        """Retracts your current proposal."""
        await self.remove_proposal(ctx.guild, ctx.author)
        return await ctx.reply("*Removed proposal.*")

    @can_manage_ballots()
    @games.command(name="accept")
    async def games_accept(self, ctx, *game_name):
        game_name = " ".join(game_name)
        game = await self.get_game(ctx.guild, game_name)

        if game is None:
            return await ctx.reply(f'*Game "{game_name}" not found.*')

        db = self.get_guild_db(ctx.guild)

        game.state = "accepted"
        if not await game.update(db):
            return await ctx.reply(f"*{SOMETHING_WENT_WRONG}*")

        # TODO: Notify proposers of the accept

        await ctx.reply(f'*Updated state to "accepted".*')

    # TODO: Add a reject command

    @can_manage_ballots()
    @games.command(name="done")
    async def games_done(self, ctx, *game_name):
        game_name = " ".join(game_name)
        game = await self.get_game(ctx.guild, game_name)

        if game is None:
            return await ctx.reply(f'*Game "{game_name}" not found.*')

        db = self.get_guild_db(ctx.guild)

        game.state = "done"
        if not await game.update(db):
            return await ctx.reply(f"*{SOMETHING_WENT_WRONG}*")

        await ctx.reply(f'*Updated state to "done".*')

    @games.command(name="list")
    async def games_list(
        self,
        ctx,
        state=commands.parameter(
            default=None, description="Optional. Filter listed games by given state."
        ),
    ):
        """Lists Lets Try games.

        This command lists all games that are in the Lets Try system. Note: you can propose Games that are not in the system, too. See the propose command for details.

        If no state argument is provided then the list includes all games except those that are "rejected", "done" or "orphaned", i.e. all games that have an expressed interest and might come up for Lets Try.

        Valid values for state are "orphaned", "submitted", "rejected", "accepted", "elected" and "done".
        """
        db = self.get_guild_db(ctx.guild)
        cur = await db.cursor()
        if not state:
            cursor_awaitable = db.execute(
                f"""{LetsTryGame.select_stmt()}
                    WHERE
                        state NOT IN ('rejected', 'done', 'orphaned')
                    LIMIT 10
                """
            )
        else:
            where = {"state": state}
            cursor_awaitable = db.execute(
                f"{LetsTryGame.select_stmt(where.keys())} LIMIT 10", where
            )
        embeds = []
        async with cursor_awaitable as cursor:
            cursor.row_factory = LetsTryGame.from_row
            async for game in cursor:
                embeds.append(game.as_embed())
        if not len(embeds):
            return await ctx.reply("*No results.*")
        await ctx.reply(embeds=embeds)

    async def remove_proposal(self, guild, user):
        db = self.get_guild_db(guild)
        proposal = LetsTryProposal.from_partial({"discord_user_id": user.id})
        await proposal.delete(db)

    async def add_proposal(self, guild, user, game_id):
        partial = {"discord_user_id": user.id, "game_id": game_id}
        proposal = LetsTryProposal.from_partial(partial)
        db = self.get_guild_db(guild)
        await proposal.insert(db)

    @can_propose()
    @games.command(name="propose")
    async def games_propose(
        self,
        ctx,
        *,
        name=commands.parameter(description="The name of the game being proposed."),
    ):
        """Propose a game for the Lets Try series. Requires proposal privileges.

        You can propose any game already in the Lets Try games list (!letstry games list) or available on Steam (!steam game <name> by simply providing the name.

        It is possible to propose games not available on Steam. To do so, please provide a URL to the games website or a alternative store as the first argument and the name of the game second, e.g. !letstry game propose <url> <name of game>.
        """
        url, name = split_url(name)
        try:
            game = await self.get_or_add_game(ctx.guild, name, url)
        except GameNotFoundError as e:
            if e.suggestion is not None:
                return await ctx.reply(f"*{str(e)}*")
            return await ctx.reply(
                f'*"{url or name}" not found. Please provide name and URL to propose non-Steam games.*'
            )

        if game is None:
            return await ctx.reply(
                f'*"{name}" wasn\'t found. For non-Steam games, also provide a URL.*'
            )

        try:
            await self.add_proposal(ctx.guild, ctx.author, game.game_id)
        except IntegrityError as e:
            s = str(e)
            if "UNIQUE constraint failed" in s:
                return await ctx.reply(
                    f"*You have an active proposal. Retract your current proposal to submit a new one.*"
                )

            if s == "game not open for proposal":
                return await ctx.reply(
                    f'*The game "{game.name}" is {game.state} and not taking any more proposals.*'
                )

        await ctx.reply(f'Added your proposal of "{game.name}"')

    @games.command(name="delete")
    @is_guild_owner()
    async def games_delete(self, ctx, *, name):
        db = self.get_guild_db(ctx.guild)
        game = await self.get_game(ctx.guild, name)
        if game is None:
            return await ctx.reply(f'Game "{name}" does not exist.')
        result = await game.delete(db)
        if not result > 0:
            return await ctx.reply(f"*{SOMETHING_WENT_WRONG}*")
        await ctx.reply(f'*Game "{name}" deleted.*')

    def get_steam(self):
        return self.bot.get_cog("steam")

    async def add_game(self, guild, name: str, url: str):
        db = self.get_guild_db(guild)

        game = LetsTryGame.from_partial({"name": name, "url": url})

        return await game.insert(db)

    async def finalize_ballot(self, guild, ballot):
        db = self.get_guild_db(guild)
        # Move game with highest votes to elected
        sql = """
            UPDATE
                letstry_games
            SET
                state = 'elected'
            WHERE
                game_id = (
                    SELECT
                        game_id
                    FROM
                        letstry_ballot_games
                        INNER JOIN
                            letstry_ballots_view
                        ON
                            letstry_ballots_view.ballot_id = letstry_ballot_games.ballot_id AND
                            letstry_ballots_view.state = 'closed'
                    WHERE
                        letstry_ballot_games.ballot_id = :ballot_id
                    ORDER BY
                        votes DESC
                    LIMIT 1
                )
        """
        async with db.execute(sql, {"ballot_id": ballot.ballot_id}) as cursor:
            if not cursor.rowcount:
                raise IntegrityError("Failed finalzing ballot")

        embed = await LetsTryBallotGame.as_embed(db, ballot)
        # Notify announcement channel about finished ballot
        channel = await self.get_announcement_channel(guild)
        if channel is None:
            return
        await channel.send(
            "A ballot just completed! Congratulations to the winner!", embed=embed
        )

        # TODO: Notify proposers about election (mention on annoucement?)

    async def get_announcement_channel(self, guild):
        channel_id = self.bot.get_cog("settings").guild_get(
            guild, "letstry-announcement-channel", None
        )
        channel_id = channel_id and int(channel_id)
        if channel_id is None:
            return None

        channel = guild.get_channel_or_thread(channel_id) or await guild.fetch_channel(
            channel_id
        )
        if channel is None:
            return None

        assert (
            getattr(channel, "guild", None) == guild
        ), "Can't announce to channels of a different server"

        return channel

    async def get_game(
        self, guild, name: str, url: Optional[str] = None
    ) -> Optional[LetsTryGame]:
        db = self.get_guild_db(guild)

        where = {"name": name, "url": url}
        return await LetsTryGame.select_fetchone(db, where)

    async def get_or_add_game(
        self, guild, name: str, url: Optional[str]
    ) -> LetsTryGame:
        game = await self.get_game(guild, name, url)

        if game is not None:
            return game

        try:
            steam_game = await self.get_steam_game(url or name)
            url = cast(str, steam_game["url"])
            name = cast(str, steam_game["name"])
        except GameNotFoundError as e:
            if url is None or name is None:
                raise e

        assert name is not None
        assert url is not None

        return await self.add_game(guild, name, url)

    async def get_steam_game(self, identifier: str) -> SteamGame:
        steam = self.get_steam()
        if steam.is_steam_url(identifier):
            url = identifier
        elif steam.is_steam_appid(identifier):
            url = steam.get_game_url_by_appid(identifier)
        else:
            url = await steam.get_game_url_by_name(identifier)
        return await steam.get_game(url)

    @games.command(name="add")
    @is_guild_owner()
    async def games_add(self, ctx, *, name):
        url, name = split_url(name)

        if url is None or name is None:
            try:
                game = await self.get_steam_game(url or name)
            except GameNotFoundError as e:
                return await ctx.reply(f"*{str(e)}*")
            else:
                name = cast(str, game["name"])
                url = cast(str, game["url"])

        db = self.get_guild_db(ctx.guild)
        try:
            await self.add_game(ctx.guild, name, url)
        except IntegrityError as e:
            pass
        else:
            return await ctx.reply(f'Added "{name}" to proposed games.')

        game = await self.get_game(ctx.guild, name, url)
        if game is None:
            return await ctx.reply(f"*{SOMETHING_WENT_WRONG}*")

        return await ctx.reply(
            f'*{an(game.state).capitalize()} game "{name or url}" already exists.*',
            suppress_embeds=True,
        )

    def get_guild_db(self, guild):
        return self.bot.get_cog("sqlite").get_guild_db(guild)

    def get_db(self):
        return self.bot.get_cog("sqlite").db

    @can_manage_ballots()
    @letstry.group(name="ballot")
    async def ballot(self, ctx):
        pass

    @ballot.command(name="create")
    async def ballot_create(self, ctx):
        thread = await ctx.channel.create_thread(
            name="Creating ballot...", message=ctx.message
        )
        db = self.get_guild_db(thread.guild)
        ballot = LetsTryBallot.from_partial({"discord_thread_id": thread.id})
        await ballot.insert(db)
        await thread.send(
            "*Ballot created. Please add games and set a start date and time.*"
        )

    @ballot.command(name="finalize")
    @is_ballot_thread()
    async def ballot_finalize(self, ctx):
        ballot = await self.get_ballot(ctx.channel)
        await self.finalize_ballot(ctx.guild, ballot)
        await ctx.reply(f"*Ballot finalized.*")

    @is_ballot_thread()
    @ballot.command(name="add")
    async def ballot_add(self, ctx, *, game):
        url, name = split_url(game)
        db = self.get_guild_db(ctx.guild)

        game, ballot = await gather(
            self.get_game(ctx.guild, name, url),
            self.get_ballot(ctx.channel),
        )

        if game is None:
            return await ctx.reply(f'*Game "{name or url}" not found.*')
        if ballot is None:
            return await ctx.reply(f"*{SOMETHING_WENT_WRONG}*")

        try:
            await LetsTryBallotGame.create_edge(db, ballot, game)
        except DuplicationError as e:
            return await ctx.reply(f'*Game "{game.name}" already in the ballot.*')
        except InvalidStateError as e:
            return await ctx.reply(
                f'*Game "{game.name}" is already {game.state} and cannot be added to a ballot.*'
            )

        return await ctx.reply(f'*Game "{game.name}" added to ballot.*')

    @is_ballot_thread()
    @ballot.command(name="submit")
    async def ballot_submit(self, ctx):
        ballot = await self.get_ballot(ctx.channel)

        db = self.get_guild_db(ctx.guild)
        ballot.staging = False
        try:
            await ballot.update(db)
        except IntegrityError as e:
            if "no games in ballot" in str(e):
                return await ctx.reply(
                    "Please add games to the ballot before submitting."
                )
            raise e

        # TODO: Notify proposers of the ballot containing their proposal

        await ctx.channel.edit(
            name=f'Ballot {datetime.fromisoformat(ballot.date_created).strftime("%Y-%m-%d")}'
        )
        await ctx.reply(f"Ballot submitted.")

    @is_ballot_thread()
    @ballot.command(name="duration")
    async def ballot_duration(self, ctx, *, duration):
        seconds = timeparse(duration)
        if seconds is None:
            return ctx.reply(
                f'"{duration}" is not a valid time duraion. Valid durations are e.g. "3 days" or "1 week"'
            )

        ballot = await self.get_ballot(ctx.channel)

        td = timedelta(seconds=seconds)
        open = datetime.fromisoformat(ballot.date_open)
        ballot.date_close = str(open + td)

        db = self.get_guild_db(ctx.guild)
        if not await ballot.update(db) > 0:
            return await ctx.reply(f"*{SOMETHING_WENT_WRONG}*")

        await ctx.reply(f"*Updated end date to {ballot.date_close}*")

    @is_ballot_thread()
    @ballot.command(name="show")
    async def ballot_show(self, ctx):
        db = self.get_guild_db(ctx.guild)
        ballot = await self.get_ballot(ctx.channel)
        if ballot is None:
            return await ctx.reply(f"{SOMETHING_WENT_WRONG}")
        embed = ballot.as_embed()
        async with LetsTryBallotGame.join_select(
            db, "game_id", ballot.primary_key_match()
        ) as cursor:
            async for ballot_game, game in cursor:
                LetsTryBallotGame.add_to_embed(embed, ballot_game, game)

        edit_view = LetsTryBallotEditView(db, ballot)

        message = await ctx.reply(embed=embed, view=edit_view)

        edit_view.setMessage(message)

    @is_ballot_thread()
    @ballot.command(name="open")
    async def ballot_open(self, ctx, *, duration_or_dt):
        dt = datetime.now(tz=timezone.utc)
        if duration_or_dt == "now":
            seconds = 0
        else:
            seconds = timeparse(duration_or_dt)

        if seconds is None:
            try:
                seconds = 0
                dt = datetime.fromisoformat(duration_or_dt)
            except:
                return await ctx.reply(
                    f'"{duration_or_dt}" is not a valid ISO timestamp or time duraion. Valid values are e.g. "3 days" or "2023-06-03 23:00:00"'
                )

        dt += timedelta(seconds=seconds)

        ballot = await self.get_ballot(ctx.channel)

        ballot.date_open = dt.strftime("%Y-%m-%d %H:%M:%S")

        db = self.get_guild_db(ctx.guild)
        if not await ballot.update(db) > 0:
            return await ctx.reply(f"*{SOMETHING_WENT_WRONG}*")

        await ctx.reply(f"*Updated open date to {ballot.date_open}*")

    @is_ballot_thread()
    @ballot.command(name="remove")
    async def ballot_remove(self, ctx, *, game):
        url, name = split_url(game)
        db = self.get_guild_db(ctx.guild)

        game, ballot = await gather(
            self.get_game(ctx.guild, name, url),
            self.get_ballot(ctx.channel),
        )

        if game is None:
            return await ctx.reply(f'*Game "{name or url}" not found.*')
        if ballot is None:
            return await ctx.reply(f"*{SOMETHING_WENT_WRONG}*")

        where = {"game_id": game.game_id, "ballot_id": ballot.ballot_id}
        edge = await LetsTryBallotGame.select_fetchone(db, where, "AND")

        if edge is None:
            return await ctx.reply(f'*Game "{game.name}" is not in the ballot.*')

        if not await edge.delete(db) > 0:
            return await ctx.reply(f"*{SOMETHING_WENT_WRONG}*")

        return await ctx.reply(f'*Game "{game.name}" removed.*')

    async def get_ballot(self, thread):
        db = self.get_guild_db(thread.guild)

        where = {"discord_thread_id": thread.id}
        return await LetsTryBallot.select_fetchone(db, where)

    @property
    def db(self):
        return self.get_db()

    async def cog_command_error(self, ctx, error):
        verbose_exceptions = [commands.UserInputError, commands.CheckFailure]
        if any([isinstance(error, E) for E in verbose_exceptions]):
            return await ctx.reply(f"*{SOMETHING_WENT_WRONG}: {str(error)}*")
        await ctx.reply(f"*{SOMETHING_WENT_WRONG}*")
        raise error

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.bootstrap_guild(guild)

    async def bootstrap_guild(self, guild):
        path = PurePath(os.path.dirname(__file__), "bootstrap.sql")
        async with aiofiles.open(path, mode="r") as file:
            sql = await file.read()
        db = self.get_guild_db(guild)
        await db.executescript(sql)
        await db.commit()

    async def cog_load(self):
        await gather(*[self.bootstrap_guild(guild) for guild in self.bot.guilds])


async def setup(bot):
    system = bot.get_cog("system")
    await system.load_extension("sqlite")
    await system.load_extension("steam")
    await bot.add_cog(LetsTry(bot))


async def teardown(bot):
    await bot.remove_cog("LetsTry")
