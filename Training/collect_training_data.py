# collect_training_data.py
import requests
import json
import re
import random
import time
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from pathlib import Path

# ------------------------------------------
# 1. Вспомогательные функции (парсинг, генерация)
# ------------------------------------------

def random_key(length=5, parts=3, sep='-'):
    """Генерирует случайный ключ формата XXXX-XXXX-XXXX"""
    import random, string
    chars = string.ascii_uppercase + string.digits
    part = ''.join(random.choice(chars) for _ in range(length))
    key = sep.join([part] * parts)
    return key

def tokenize_text(text):
    """Разбивает текст на токены (слова и знаки препинания)"""
    return re.findall(r'\w+|[.,!?;:\'\"()\-]', text)

def find_keys_in_text(text):
    """Ищет ключи по регулярным выражениям, возвращает список (start, end, key)"""
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

def align_labels(tokens, key_spans, text):
    """Проставляет BIO-метки для токенов на основе найденных ключей"""
    labels = ['O'] * len(tokens)
    token_positions = []
    pos = 0
    for token in tokens:
        start = text.find(token, pos)
        if start == -1:
            start = pos
        end = start + len(token)
        token_positions.append((start, end, token))
        pos = end

    for (ks, ke, key) in key_spans:
        inside = False
        for i, (ts, te, tok) in enumerate(token_positions):
            if ts >= ks and te <= ke:
                if not inside:
                    labels[i] = 'B-KEY'
                    inside = True
                else:
                    labels[i] = 'I-KEY'
            elif inside and ts > ke:
                inside = False
    return labels

def parse_webpage(url, timeout=10, delay=1):
    """Загружает страницу, извлекает заголовок и текст, удаляя мусор"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        time.sleep(delay)
        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header']):
            tag.decompose()
        title = soup.title.string.strip() if soup.title else ''
        text_elements = soup.find_all(['p', 'h1', 'h2', 'h3', 'article', 'div', 'span'])
        text = ' '.join(elem.get_text(strip=True) for elem in text_elements)
        text = re.sub(r'\s+', ' ', text).strip()
        return title, text
    except Exception as e:
        print(f"Ошибка загрузки {url}: {e}")
        return None, None

# ------------------------------------------
# 2. Сбор данных с GamerPower API
# ------------------------------------------

def fetch_gamerpower_giveaways(limit=100):
    """Получает список раздач с GamerPower API"""
    url = "https://www.gamerpower.com/api/giveaways"
    params = {'limit': limit}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        print(f"Получено {len(data)} раздач из GamerPower API")
        return data
    except Exception as e:
        print(f"Ошибка получения данных GamerPower: {e}")
        return []

def generate_synthetic_ner_from_gamerpower(giveaways, num_examples=500):
    """
    Создаёт синтетические NER-примеры на основе описаний раздач,
    вставляя случайные ключи в текст.
    """
    examples = []
    label2id = {"O": 0, "B-KEY": 1, "I-KEY": 2}
    for i, g in enumerate(giveaways):
        if len(examples) >= num_examples:
            break
        title = g.get('title', '')
        desc = g.get('description', '')
        # platforms = g.get('platforms', '')  # можно использовать
        full_text = (title + ' ' + desc).strip()
        if len(full_text) < 20:
            continue

        # С вероятностью 0.7 вставляем ключ
        if random.random() < 0.7:
            key = random_key()
            # Вставляем в случайное место
            pos = random.randint(0, len(full_text))
            text_with_key = full_text[:pos] + ' ' + key + ' ' + full_text[pos:]
        else:
            text_with_key = full_text
            key = None

        tokens = tokenize_text(text_with_key)
        key_spans = find_keys_in_text(text_with_key)
        labels_str = align_labels(tokens, key_spans, text_with_key)
        ner_tags = [label2id[l] for l in labels_str]

        examples.append({
            'id': f"gamerpower_{i}",
            'tokens': tokens,
            'ner_tags': ner_tags
        })
    print(f"Сгенерировано {len(examples)} синтетических примеров из GamerPower")
    return examples

# ------------------------------------------
# 3. Сбор данных с форумов (IndieDB, Backloggd и др.)
# ------------------------------------------

def collect_from_forum_urls(url_list, max_per_url=3):
    """
    Для каждого URL загружает страницу, ищет ключи, создаёт примеры.
    Если страница содержит несколько потенциальных ключей, можно создать несколько примеров.
    """
    examples = []
    label2id = {"O": 0, "B-KEY": 1, "I-KEY": 2}
    for idx, url in enumerate(url_list):
        print(f"Обрабатываю [{idx+1}/{len(url_list)}]: {url}")
        title, text = parse_webpage(url)
        if not text:
            continue
        full_text = f"{title} {text}"[:5000]  # ограничим длину

        # Ищем ключи
        key_spans = find_keys_in_text(full_text)
        if not key_spans:
            # Если ключей нет, можем создать один пример без ключа (negative)
            tokens = tokenize_text(full_text)
            ner_tags = [0] * len(tokens)
            examples.append({
                'id': f"forum_no_key_{idx}",
                'tokens': tokens,
                'ner_tags': ner_tags
            })
        else:
            # Для каждого ключа можно создать отдельный пример (обрезка вокруг ключа)
            # Для простоты создадим один пример со всеми ключами
            tokens = tokenize_text(full_text)
            labels_str = align_labels(tokens, key_spans, full_text)
            ner_tags = [label2id[l] for l in labels_str]
            examples.append({
                'id': f"forum_{idx}",
                'tokens': tokens,
                'ner_tags': ner_tags
            })
        time.sleep(2)  # вежливая пауза

    print(f"Собрано {len(examples)} примеров с форумов")
    return examples

# ------------------------------------------
# 4. Основная функция
# ------------------------------------------

def main():
    # Параметры
    OUTPUT_FILE = "training_data/ner_dataset.json"
    GAMERPOWER_LIMIT = 200
    SYNTHETIC_EXAMPLES = 500
    FORUM_URLS = [
        "https://www.indiedb.com/giveaways",
        "https://www.backloggd.com/perpetual-giveaway/",
        # можно добавить другие URL
    ]

    # Создаём папку
    Path("training_data").mkdir(exist_ok=True)

    all_examples = []

    # 1. GamerPower
    print("="*60)
    print("ШАГ 1: Сбор данных с GamerPower API")
    giveaways = fetch_gamerpower_giveaways(limit=GAMERPOWER_LIMIT)
    if giveaways:
        synth_ex = generate_synthetic_ner_from_gamerpower(giveaways, num_examples=SYNTHETIC_EXAMPLES)
        all_examples.extend(synth_ex)

    # 2. Форумы
    print("="*60)
    print("ШАГ 2: Парсинг форумов")
    forum_ex = collect_from_forum_urls(FORUM_URLS)
    all_examples.extend(forum_ex)

    # Сохраняем
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_examples, f, indent=2, ensure_ascii=False)

    print("="*60)
    print(f"✅ ИТОГО: сохранено {len(all_examples)} примеров в {OUTPUT_FILE}")

if __name__ == "__main__":
    main()