from datetime import datetime
from http.cookies import Morsel, SimpleCookie
import re
from typing import TypedDict
from aiopath import PurePath
import aiofiles
from discord.ext import commands
from discord import Embed
from aiohttp import ClientSession
from bs4 import BeautifulSoup, Tag
from buffedbot.extensions.sqlite import dict_compact, get_column_names, get_placeholder_names, get_placeholder_values
from urllib.parse import urlencode, urljoin, urlparse, urlunparse
from . import GameNotFoundError, AttributeNotFoundError, ElementNotFoundError

from yarl import URL

class Game(TypedDict):
    name: str
    url: str
    description: str
    image: str
    price: float
    review_count: int
    review_summary: str
    date_created: str

class SearchResult(TypedDict):
    name: str
    url: str
    price: float

def game_to_discord_embed(game: Game) -> Embed:
    return Embed(
        title=game['name'],
        description=game['description'],
        url=game['url']
    ).set_image(
        url=game['image']
    ).add_field(
        name='Price',
        value=f'${game["price"]}',
        inline=True
    ).add_field(
        name='Reviews',
        value=f'{game["review_summary"]} ({game["review_count"]:,})'
    )

class ResultsEmbed(Embed):
    def add_result(self, result: SearchResult) -> 'ResultsEmbed':
        return self.add_field(
            name=result['name'],
            value=f'{"$"+str(result["price"]) if result["price"] else "Free to Play"}\n{result["url"]}',
            inline=False
        )

class SteamSearchResultsSoup():
    def __init__(self, bs: BeautifulSoup):
        self.bs = bs

    def get_result_anchors(self):
        return self.bs.select('a.search_result_row')

    def get_result_title_spans(self):
        return self.bs.select('a.search_result_row span.title')

    def get_result_price_elements(self):
        return self.bs.select('a.search_result_row [data-price-final]')

    def get_search_results(self) -> list[SearchResult]:
        anchors = self.get_result_anchors()
        spans = self.get_result_title_spans()
        price_elements = self.get_result_price_elements()
        if len(spans) != len(anchors):
            raise RuntimeError()

        return [SearchResult(
            name=str(span.string),
            url=urljoin(anchor.attrs['href'], urlparse(anchor.attrs['href']).path),
            price=int(price_element.attrs['data-price-final'])/100.0
        ) for (anchor, span, price_element) in zip(
            anchors, spans, price_elements
        )]

class SteamGameSoup():
    def __init__(self, bs: BeautifulSoup):
        self.bs = bs

    def get_element(self, selector: str) -> Tag:
        element = self.bs.select_one(selector)
        if element is None:
            raise ElementNotFoundError(f'Element for query "{selector}" not found')
        return element


    def get_content_attr(self, selector: str) -> str:
        element = self.get_element(selector)

        if not 'content' in element.attrs:
            raise AttributeNotFoundError('Attribute "content" missing')

        content_attr = element['content']
        if isinstance(content_attr, list):
            raise AttributeNotFoundError('Attribute "content" is a list')

        return content_attr

    def get_text(self, selector: str) -> str:
        element = self.get_element(selector)

        if element.string is None:
            raise ElementNotFoundError(
                f'Element for query "{selector}" does not contain a text node.'
            )

        # Typing says element.string is NavigableString which retains a reference
        # to the BS parse tree. Casting to string to strip that stuff off
        return str(element.string)

    def get_price(self) -> float:
        return float(
            self.get_content_attr('[itemprop=offers] [itemprop=price]')
        )

    def get_review_count(self) -> int:
        return int(self.get_content_attr(
            '[itemprop=aggregateRating] [itemprop=reviewCount]'
        ))

    def get_review_summary(self) -> str:
        return self.get_text(
            '[itemprop=aggregateRating] span[itemprop=description]'
        )

    def get_url(self) -> str:
        return self.get_content_attr('meta[property="og:url"]')

    def get_description(self) -> str:
        return self.get_content_attr('meta[property="og:description"]')

    def get_image(self) -> str:
        return self.get_content_attr('meta[property="og:image"]')

    def get_name(self) -> str:
        return self.get_text(('span[itemprop=name]'))

class Steam(commands.Cog, name='steam'):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def get_db(self):
        return self.bot.get_cog('sqlite').db # type: ignore

    @property
    def db(self):
        return self.get_db()

    @staticmethod
    def get_bootstrap_file_path():
        return PurePath(PurePath(__file__).parent, 'bootstrap.sql')

    async def cog_load(self):
        self.session = ClientSession()
        async with aiofiles.open(__class__.get_bootstrap_file_path(), 'r') as f:
            sql = await f.read()
        await self.db.executescript(sql)

    async def cog_unload(self):
        await self.session.close()

    @commands.group()
    async def steam(self, ctx):
        """Commands to interface with the Steam store and database"""
        pass

    @steam.command()
    async def search(self, ctx, *terms):
        """Searches the Steam store database"""
        async with ctx.typing():
            term = ' '.join(terms)
            limit = 5
            results = await self.get_search_results(term)
            embed = ResultsEmbed(
                title=f'Results for "{term}"',
                url=__class__.get_search_url(term),
            )
            for result in results[:limit]:
                embed.add_result(result)
            embed.set_footer(
                text=f'Limited to {limit} results. Click title for more.'
            )
            await ctx.reply(embed=embed)

    steam_app_url_re = re.compile(r'https?://store\.steampowered\.com/app/([0-9]+).*$')
    @staticmethod
    def is_steam_url(maybe_url: str) -> bool:
        return __class__.steam_app_url_re.match(maybe_url) is not None

    steam_appid_re = re.compile(r'^[0-9]+$')
    @staticmethod
    def is_steam_appid(maybe_appid: str) -> bool:
        return __class__.steam_appid_re.match(maybe_appid) is not None

    @staticmethod
    def get_game_url_by_appid(appid: str) -> str:
        return f'https://store.steampowered.com/app/{appid}/'

    async def get_game_url_by_name(self, name):
        url_from_cache = await self.get_game_url_from_cache(name)
        if url_from_cache is not None:
            return url_from_cache
        search_results = await self.get_search_results(name)
        if len(search_results) == 0:
            raise GameNotFoundError(name)
        top_result = search_results[0]
        if top_result['name'].lower() != name.lower():
            raise GameNotFoundError(name, suggestion=top_result['name'])
        return top_result['url']

    @steam.command()
    async def game(self, ctx, *message):
        """Retrieves information about the game from the Steam store"""
        async with ctx.typing():
            game_name = " ".join(message)
            try:
                url = await self.get_game_url_by_name(game_name)
            except GameNotFoundError as e:
                return await ctx.reply(
                    f'*{str(e)}*'
                )
            embed = game_to_discord_embed(
                await self.get_game(url)
            )
            await ctx.reply(embed=embed)

    @staticmethod
    def get_search_url(term) -> str:
        query = urlencode({'term':term})
        return f'https://store.steampowered.com/search/?{query}'

    async def get_search_results(self, term: str) -> list[SearchResult]:
        request = await self.session.get(__class__.get_search_url(term))
        markup = await request.read()

        bs = BeautifulSoup(markup, 'html.parser')
        search_results = SteamSearchResultsSoup(bs)

        return search_results.get_search_results()

    normalize_re = re.compile('^(/app/[0-9]+).*$')
    @staticmethod
    def normalize_game_url(url: str) -> str:
        parsed = urlparse(url)
        path = __class__.normalize_re.sub('\\1', parsed.path)
        normalized = [
            'https',
            parsed.netloc,
            path,
            '', # params
            '', # query
            ''  # fragment
        ]
        return urlunparse(normalized)

    async def get_game_url_from_cache(self, name: str) -> str|None:
        sql = f'''SELECT url FROM steam_games_cache WHERE name = ?'''

        async with await self.db.execute(sql, (name,)) as cursor:
            async for row in cursor:
                return row[0]

    async def get_game_from_cache(self, normalized_url: str) -> Game|None:
        app_id = __class__.get_app_id_from_url(normalized_url)
        sql = f'''
            SELECT
                {get_column_names(Game.__annotations__, wrap_brackets=False)}
            FROM
                steam_games_cache
            WHERE
                app_id = ? AND DATETIME(date_created, '+1 days') > DATETIME('now')
        '''
        async with await self.db.execute(sql, (app_id,)) as cursor:
            async for row in cursor:
                return Game(
                    name=row[0],
                    url=row[1],
                    description=row[2],
                    image=row[3],
                    price=row[4],
                    review_count=row[5],
                    review_summary=row[6],
                    date_created=row[7]
                )

    app_id_from_path_re = re.compile('^/app/([0-9]+).*$')
    @staticmethod
    def get_app_id_from_url(url: str) -> str:
        parsed = urlparse(url)
        match = __class__.app_id_from_path_re.match(parsed.path)
        if not match:
            raise RuntimeError()
        return match.group(1)

    async def store_game_in_cache(self, game: Game):
        game_with_app_id = game | {
            'app_id': __class__.get_app_id_from_url(game['url'])
        }
        sql = f'''
            INSERT INTO
                steam_games_cache {get_column_names(game_with_app_id)}
            VALUES
                {get_placeholder_names(game_with_app_id)}
            ON CONFLICT
                (app_id)
            DO UPDATE SET
                name = excluded.name,
                url = excluded.url,
                description = excluded.description,
                price = excluded.price,
                review_count = excluded.review_count,
                review_summary = excluded.review_summary,
                date_created = DATETIME(excluded.date_created)
            WHERE
                date_created < excluded.date_created
        '''

        await self.db.execute(sql, get_placeholder_values(game_with_app_id))
        await self.db.commit()

    async def get_game(self, url: str) -> Game:
        url = __class__.normalize_game_url(url)

        cached = await self.get_game_from_cache(url)
        if cached:
            return cached

        # We should do a mutex lock on the cache key here until the fetch has
        # completed and the cache is populated to avoid thunderin herds

        # We might only need to explicitly add this cookie once per session
        additional_cookies = SimpleCookie()
        JAN_1_1980_UNIX_EPOCH_TIME = 315561600
        # required to avoid age verification interstitial
        additional_cookies['birthtime'] = str(JAN_1_1980_UNIX_EPOCH_TIME)
        self.session.cookie_jar.update_cookies(cookies=additional_cookies)

        response = await self.session.get(url)
        markup = await response.read()
        bs = BeautifulSoup(markup, 'html.parser')
        game_soup = SteamGameSoup(bs)

        date_as_iso = datetime.strptime(
            response.headers['date'],
            '%a, %d %b %Y %H:%M:%S %Z').isoformat(sep=' ', timespec='seconds'
        )

        game = Game(
            name=game_soup.get_name(),
            description=game_soup.get_description(),
            url=game_soup.get_url(),
            image=game_soup.get_image(),
            price=game_soup.get_price(),
            review_count=game_soup.get_review_count(),
            review_summary=game_soup.get_review_summary(),
            date_created=date_as_iso
        )

        await self.store_game_in_cache(game)

        return game

async def setup(bot):
    await bot.get_cog('system').load_extension('sqlite')
    await bot.add_cog(Steam(bot))

async def teardown(bot):
    await bot.remove_cog('Steam')

print('SETUP STEAM')