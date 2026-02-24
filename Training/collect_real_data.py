# collect_real_data.py
import json
import re
import requests
from bs4 import BeautifulSoup
from pathlib import Path
import time
import random
from urllib.parse import urlparse
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# -------------------------------
# 1. Функции для парсинга страницы
# -------------------------------
def fetch_page(url, timeout=10, delay=2):
    """Загружает страницу и возвращает BeautifulSoup объект."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        time.sleep(delay)  # вежливость
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        # удаляем скрипты, стили, навигацию
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
        return soup
    except Exception as e:
        logger.error(f"Ошибка загрузки {url}: {e}")
        return None

def extract_text_from_soup(soup):
    """Извлекает заголовок и весь видимый текст."""
    title = soup.title.string.strip() if soup.title else ""
    # текст из основных блоков (p, h1-h6, div, span)
    text_elements = soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'span'])
    text = ' '.join(elem.get_text(strip=True) for elem in text_elements)
    # очистка от лишних пробелов
    text = re.sub(r'\s+', ' ', text).strip()
    return title, text

# -------------------------------
# 2. Разметка ключей (аналогично extract_keys, но с сохранением позиций)
# -------------------------------
def tokenize_text(text):
    """Разбивает текст на токены (слова и знаки препинания)."""
    # простое разбиение по пробелам с учётом пунктуации
    tokens = re.findall(r'\w+|[.,!?;:\'\"()\-]', text)
    return tokens

def find_keys_in_text(text):
    """Ищет ключи по регулярным выражениям, возвращает список (start, end, key)."""
    key_patterns = [
        r'[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}',
        r'[A-Z0-9]{4,7}-[A-Z0-9]{4,7}-[A-Z0-9]{4,7}',
        r'[A-Z0-9]{5,7}-[A-Z0-9]{5,7}-[A-Z0-9]{5,7}-[A-Z0-9]{5,7}-[A-Z0-9]{5,7}',
        r'[A-Z0-9]{4,6}-[A-Z0-9]{4,6}-[A-Z0-9]{4,6}-[A-Z0-9]{4,6}',
        r'[A-Z0-9]{16,20}',
        r'[A-Z0-9]{25,30}',
    ]
    matches = []
    for pattern in key_patterns:
        for m in re.finditer(pattern, text):
            matches.append((m.start(), m.end(), m.group()))
    return matches

def align_labels(tokens, key_spans):
    """
    Для каждого токена проставляет метку BIO.
    key_spans: список (start, end, key) в исходном тексте.
    Возвращает список меток длины len(tokens).
    """
    labels = ['O'] * len(tokens)
    # строим карту позиций токенов
    token_positions = []
    pos = 0
    for token in tokens:
        start = text.find(token, pos)
        if start == -1:
            # если не нашли, грубо привязываемся к порядку (но для англ. текста должно работать)
            start = pos
        end = start + len(token)
        token_positions.append((start, end, token))
        pos = end

    for (ks, ke, key) in key_spans:
        inside = False
        for i, (ts, te, tok) in enumerate(token_positions):
            if ts >= ks and te <= ke:
                # токен полностью внутри ключа
                if not inside:
                    labels[i] = 'B-KEY'
                    inside = True
                else:
                    labels[i] = 'I-KEY'
            elif inside and ts > ke:
                inside = False
    return labels

# -------------------------------
# 3. Основная функция сбора
# -------------------------------
def collect_from_urls(url_list, output_file='real_ner_dataset.json', max_pages=None):
    """
    Принимает список URL, парсит каждую страницу и добавляет размеченные примеры.
    """
    dataset = []
    for idx, url in enumerate(url_list):
        if max_pages and idx >= max_pages:
            break
        logger.info(f"Обрабатываю [{idx+1}/{len(url_list)}]: {url}")
        soup = fetch_page(url)
        if not soup:
            continue
        title, text = extract_text_from_soup(soup)
        full_text = f"{title}\n{text}"  # объединяем заголовок и текст
        # укорачиваем до разумных пределов (например, 5000 символов)
        full_text = full_text[:5000]
        # ищем ключи
        key_spans = find_keys_in_text(full_text)
        if not key_spans:
            logger.info(f"   Ключей не найдено, пропускаем.")
            continue
        # токенизация
        tokens = tokenize_text(full_text)
        labels = align_labels(tokens, key_spans)
        # добавляем пример
        example = {
            'id': str(idx),
            'tokens': tokens,
            'ner_tags': [{'O':0, 'B-KEY':1, 'I-KEY':2}[lbl] for lbl in labels],
            'url': url,
            'title': title
        }
        dataset.append(example)
        logger.info(f"   Добавлен пример с {len(key_spans)} ключами")

    # сохраняем
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)
    logger.info(f"Сохранено {len(dataset)} примеров в {output_file}")

# -------------------------------
# 4. Дополнительно: создание пар для поисковой модели
# -------------------------------
def create_search_pairs_from_urls(url_list, output_file='real_search_pairs.csv'):
    """
    Генерирует пары (запрос, текст) для обучения поиска.
    Запрос формируется из заголовка, текст – из содержимого.
    Все пары считаются позитивными.
    """
    import csv
    pairs = []
    for url in url_list:
        soup = fetch_page(url)
        if not soup:
            continue
        title, text = extract_text_from_soup(soup)
        # генерируем несколько запросов: сам заголовок, урезанный заголовок, ключевые слова
        queries = [title]
        # можно добавить вариации
        pairs.append({'query': title, 'positive_text': text[:1000], 'negative_text': ''})
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['query', 'positive_text', 'negative_text'])
        writer.writeheader()
        writer.writerows(pairs)
    logger.info(f"Сохранено {len(pairs)} поисковых пар в {output_file}")

# -------------------------------
# 5. Точка входа
# -------------------------------
if __name__ == "__main__":
    # Здесь вы можете задать список URL вручную или прочитать из файла
    urls = [
        "https://www.reddit.com/r/FreeGameFindings/comments/example1/",
        "https://giveawaybase.com/some-giveaway",
        "https://www.alienwarearena.com/giveaways/example",
        # добавьте свои ссылки
    ]
    # или прочитать из файла:
    # with open('urls.txt') as f:
    #     urls = [line.strip() for line in f if line.strip()]

    collect_from_urls(urls, output_file='real_ner_dataset.json', max_pages=50)
    # также можно создать пары для поиска:
    # create_search_pairs_from_urls(urls, output_file='real_search_pairs.csv')