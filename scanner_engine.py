# scanner_engine.py
import requests
import re
import time
import random
from urllib.parse import urlparse, quote
from typing import List, Dict, Optional, Set
import logging

from bs4 import BeautifulSoup
from models import ModelManager, guess_platform, guess_game_name
from models_data import GiveawayResult, KeyResult
from database import DatabaseManager

logger = logging.getLogger(__name__)

# Общий список User-Agent для ротации
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]

# Базовые заголовки, общие для всех запросов
BASE_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0',
}

class WebParser:
    def __init__(self, timeout=15, delay=2):
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        # Заголовки будут дополняться в каждом запросе (User-Agent, Cookie)

    def _get_headers(self) -> Dict:
        """Возвращает заголовки для запроса со случайным User-Agent и куками."""
        return {
            **BASE_HEADERS,
            'User-Agent': random.choice(USER_AGENTS),
            'Cookie': 'over18=1; _ga=GA1.2.123456789.1678901234; _gid=GA1.2.987654321.1678901234'
        }

    def extract_content(self, url: str) -> Optional[Dict]:
        try:
            # Для Reddit используем старую версию
            if 'reddit.com' in url and 'old.' not in url:
                url = url.replace('www.reddit.com', 'old.reddit.com')
                url = url.replace('reddit.com', 'old.reddit.com')

            headers = self._get_headers()
            response = self.session.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')
            for script in soup(['script', 'style', 'nav', 'footer', 'header']):
                script.decompose()
            title = soup.title.string if soup.title else ""
            title = ' '.join(title.split())[:200]
            text_elements = soup.find_all(['p', 'h1', 'h2', 'h3', 'article', 'div', 'span'])
            text = ' '.join([elem.get_text(strip=True) for elem in text_elements])
            text = re.sub(r'\s+', ' ', text)
            text = re.sub(r'[^\w\s\.\,\!\?\:\-\(\)\[\]]', '', text)
            tags = self._extract_tags(soup, url)
            return {'url': url, 'title': title, 'text': text[:10000], 'tags': tags}
        except Exception as e:
            logger.error(f"Ошибка при парсинге {url}: {e}")
            return None

    def _extract_tags(self, soup: BeautifulSoup, url: str) -> List[str]:
        # ... (без изменений) ...
        tags = set()
        meta_keywords = soup.find('meta', attrs={'name': 'keywords'})
        if meta_keywords and meta_keywords.get('content'):
            for kw in meta_keywords['content'].split(','):
                cleaned = kw.strip().lower()
                if cleaned and len(cleaned) < 30:
                    tags.add(cleaned)
        breadcrumbs = soup.select('ol.breadcrumb li, div.breadcrumbs a, nav[aria-label="breadcrumb"] a')
        for el in breadcrumbs:
            text = el.get_text(strip=True).lower()
            if text and len(text) < 30 and not text.isdigit():
                tags.add(text)
        tag_elements = soup.find_all(class_=re.compile(r'tag|genre|category', re.I))
        for el in tag_elements:
            text = el.get_text(strip=True).lower()
            if text and len(text) < 30 and not text.isdigit():
                tags.add(text)
        path_parts = urlparse(url).path.split('/')
        for part in path_parts:
            if part and len(part) < 30 and part.isalpha():
                tags.add(part.lower())
        return list(tags)


class WebSearcher:
    def __init__(self, delay_range=(3, 7)):
        self.delay_range = delay_range
        self.session = requests.Session()

    def _get_headers(self) -> Dict:
        """Возвращает заголовки для запроса со случайным User-Agent и куками."""
        return {
            **BASE_HEADERS,
            'User-Agent': random.choice(USER_AGENTS),
            'Cookie': 'over18=1; _ga=GA1.2.123456789.1678901234; _gid=GA1.2.987654321.1678901234'
        }

    def _fetch_soup(self, url: str) -> Optional[BeautifulSoup]:
        try:
            delay = random.uniform(*self.delay_range)
            time.sleep(delay)
            if 'reddit.com' in url and 'old.' not in url:
                url = url.replace('www.reddit.com', 'old.reddit.com')
                url = url.replace('reddit.com', 'old.reddit.com')
            headers = self._get_headers()
            resp = self.session.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            return BeautifulSoup(resp.text, 'lxml')
        except Exception as e:
            logger.warning(f"Ошибка загрузки {url}: {e}")
            return None

    def search_bing(self, query: str, num_pages: int = 2) -> List[str]:
        urls = []
        for page in range(1, num_pages + 1):
            first = (page - 1) * 10 + 1
            url = f"https://www.bing.com/search?q={quote(query)}&first={first}"
            soup = self._fetch_soup(url)
            if soup:
                for a in soup.select('li.b_algo h2 a'):
                    href = a.get('href')
                    if href and href.startswith('http'):
                        urls.append(href)
        return urls

    def search_duckduckgo(self, query: str, num_pages: int = 2) -> List[str]:
        urls = []
        for page in range(1, num_pages + 1):
            url = f"https://html.duckduckgo.com/html/?q={quote(query)}&s={10*(page-1)}"
            soup = self._fetch_soup(url)
            if soup:
                for a in soup.select('a.result__a'):
                    href = a.get('href')
                    if href and href.startswith('http'):
                        urls.append(href)
        return urls

    def search_brave(self, query: str, num_pages: int = 2) -> List[str]:
        urls = []
        for page in range(1, num_pages + 1):
            offset = (page - 1) * 20
            url = f"https://search.brave.com/search?q={quote(query)}&offset={offset}"
            soup = self._fetch_soup(url)
            if soup:
                for a in soup.select('div.snippet a'):
                    href = a.get('href')
                    if href and href.startswith('http'):
                        urls.append(href)
        return urls

    def search_all(self, query: str, enabled_engines: List[str], pages_per_engine: int = 2) -> Set[str]:
        all_urls = set()
        if 'bing' in enabled_engines:
            all_urls.update(self.search_bing(query, pages_per_engine))
        if 'duckduckgo' in enabled_engines:
            all_urls.update(self.search_duckduckgo(query, pages_per_engine))
        if 'brave' in enabled_engines:
            all_urls.update(self.search_brave(query, pages_per_engine))
        return all_urls


class GiveawayScanner:
    # ... (без изменений, как в вашем файле) ...
    def __init__(self, model_manager, db_manager, config: dict = None):
        self.model_manager = model_manager
        self.db_manager = db_manager
        self.parser = WebParser()
        self.searcher = WebSearcher()
        self.known_urls = set()
        self.config = config or self._default_config()
        self.load_known_urls()
        logger.info("Сканер инициализирован")

    def _default_config(self) -> dict:
        return {
            'use_static_sites': True,
            'static_sites': [
                "https://www.reddit.com/r/FreeGameFindings/search?q={query}&restrict_sr=1",
                "https://giveawaybase.com/?s={query}",
                "https://www.indiegala.com/giveaways",
                "https://www.gamasutra.com/search/?search_text={query}"
            ],
            'use_search_engines': True,
            'enabled_engines': ['bing', 'duckduckgo'],
            'pages_per_engine': 2,
            'max_total_urls': 50
        }

    def load_known_urls(self):
        try:
            giveaways = self.db_manager.get_all_giveaways()
            self.known_urls = {g.url for g in giveaways}
            logger.info(f"Загружено {len(self.known_urls)} известных URL")
        except Exception as e:
            logger.error(f"Ошибка загрузки известных URL: {e}")

    def _collect_urls(self, query: str) -> List[str]:
        all_urls = set()
        if self.config.get('use_static_sites'):
            for site in self.config.get('static_sites', []):
                try:
                    url = site.format(query=query)
                    all_urls.add(url)
                except:
                    pass
        if self.config.get('use_search_engines'):
            enabled = self.config.get('enabled_engines', [])
            pages = self.config.get('pages_per_engine', 2)
            search_urls = self.searcher.search_all(query, enabled, pages)
            all_urls.update(search_urls)
        url_list = list(all_urls)
        random.shuffle(url_list)
        max_urls = self.config.get('max_total_urls', 50)
        if len(url_list) > max_urls:
            url_list = url_list[:max_urls]
        logger.info(f"Собрано {len(url_list)} URL для анализа")
        return url_list

    def scan(self, query: str, max_pages: int = None) -> List[GiveawayResult]:
        urls_to_scan = self._collect_urls(query)
        results = []

        for site in urls_to_scan:
            if site in self.known_urls:
                logger.debug(f"Пропускаем уже известный URL: {site}")
                continue

            logger.info(f"Анализ: {site}")
            content = self.parser.extract_content(site)
            if not content:
                continue

            text_for_analysis = f"{content['title']} {content['text'][:1000]}"
            relevance = self.model_manager.analyze_relevance(text_for_analysis)

            if relevance > 0.25:
                key_strings = self.model_manager.extract_keys(content['text'])
                if not key_strings:
                    logger.debug("Ключи не найдены, раздача не сохраняется.")
                    continue

                giveaway = GiveawayResult(
                    title=content['title'],
                    url=site,
                    source_site=urlparse(site).netloc,
                    description=content['text'][:500] + "...",
                    confidence_score=float(relevance)
                )
                giveaway_id = self.db_manager.add_giveaway(giveaway)
                if not giveaway_id:
                    logger.error(f"Не удалось сохранить раздачу {site}")
                    continue

                key_objects = []
                for k in key_strings:
                    platform = guess_platform(k)
                    game = guess_game_name(content['title'], content['text'], k)
                    key_objects.append(KeyResult(
                        giveaway_id=giveaway_id,
                        key=k,
                        platform=platform,
                        game_name=game
                    ))
                self.db_manager.add_keys(key_objects)

                results.append(giveaway)
                self.known_urls.add(site)

            time.sleep(self.parser.delay)

        logger.info(f"Сканирование завершено. Найдено {len(results)} новых раздач с ключами.")
        return results

    def update_config(self, new_config: dict):
        self.config.update(new_config)
        logger.info("Конфигурация сканера обновлена")