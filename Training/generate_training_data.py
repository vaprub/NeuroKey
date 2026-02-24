# generate_training_data.py
"""
Генератор синтетических обучающих данных для NeuroKey.
Создаёт примеры для:
1. Поиска раздач (SentenceTransformer)
2. Извлечения ключей (NER)
"""

import json
import random
import csv
from datetime import datetime, timedelta
from pathlib import Path

# ============================================
# 1. ДАННЫЕ ДЛЯ ПОИСКА РАЗДАЧ (семантический поиск)
# ============================================

GIVEAWAY_WEBSITES = [
    {
        'name': 'Reddit r/FreeGameFindings',
        'url': 'reddit.com/r/FreeGameFindings',
        'description': 'Subreddit dedicated to finding free games and keys',
        'typical_titles': [
            '[STEAM] Free Game XYZ - limited time',
            'Giveaway: 1000 keys for Indie Game',
            'Free DLC for popular game',
            'Claim your free copy of Game Name',
            'Limited time: get Game for free',
        ]
    },
    {
        'name': 'Alienware Arena',
        'url': 'alienwarearena.com',
        'description': 'Gaming community with regular giveaways',
        'typical_titles': [
            'Alienware Arena - Free Game Giveaway',
            'Get your free Steam key now',
            'New bundle available - claim now',
            'Exclusive giveaway for members',
        ]
    },
    {
        'name': 'GiveawayBase',
        'url': 'giveawaybase.com',
        'description': 'Aggregator of game giveaways',
        'typical_titles': [
            '[Giveaway] Game Name - Steam Key',
            'Free GOG key inside',
            'Limited time offer: grab your key',
            'New giveaway: popular game',
        ]
    }
]

NEGATIVE_WEBSITES = [
    {
        'name': 'Game news site',
        'url': 'ign.com',
        'description': 'Game reviews and news',
        'typical_titles': [
            'New game release: Cyberpunk 2077 expansion',
            'Review: Latest game is amazing',
            'Patch notes for popular game',
            'Game sales: 50% off on Steam',
        ]
    },
    {
        'name': 'Gaming forum',
        'url': 'reddit.com/r/gaming',
        'description': 'General gaming discussion',
        'typical_titles': [
            'What games are you playing this week?',
            'Unpopular opinion: this game is overrated',
            'Help me choose a new game',
            'Best graphics settings for new game',
        ]
    },
    {
        'name': 'E-commerce',
        'url': 'amazon.com',
        'description': 'Online store',
        'typical_titles': [
            'Buy game now - 20% off',
            'Pre-order new game and get bonus',
            'Gaming laptop deals',
            'Gift cards for games',
        ]
    }
]

def generate_search_pairs(num_pairs=1000):
    """
    Генерирует пары (запрос, текст) для обучения поиску раздач.
    Возвращает список словарей с колонками: query, positive_text, negative_text
    """
    pairs = []
    
    # Шаблоны запросов пользователей
    query_templates = [
        "free {game} key",
        "giveaway {game} steam",
        "get {game} for free",
        "{game} free code",
        "раздача {game} ключ",
        "бесплатный ключ {game}",
        "claim free {game}",
        "{game} giveaway today",
    ]
    
    game_names = [
        "Cyberpunk 2077", "GTA V", "The Witcher 3", "Red Dead Redemption 2",
        "Minecraft", "Fortnite", "Among Us", "Stardew Valley", "Hades",
        "Hollow Knight", "Celeste", "Cuphead", "Portal 2", "Half-Life",
        "Left 4 Dead", "Team Fortress 2", "Dota 2", "Counter-Strike"
    ]
    
    for _ in range(num_pairs):
        # Выбираем случайную игру
        game = random.choice(game_names)
        
        # Формируем запрос
        query_template = random.choice(query_templates)
        query = query_template.format(game=game)
        
        # Позитивный пример (раздача)
        pos_site = random.choice(GIVEAWAY_WEBSITES)
        pos_title = random.choice(pos_site['typical_titles'])
        # Добавляем название игры в текст
        if random.random() > 0.5:
            pos_title = pos_title.replace('Game', game).replace('game', game)
        pos_text = f"{pos_title}. {pos_site['description']}"
        
        # Негативный пример (не раздача)
        neg_site = random.choice(NEGATIVE_WEBSITES)
        neg_title = random.choice(neg_site['typical_titles'])
        neg_text = f"{neg_title}. {neg_site['description']}"
        
        pairs.append({
            'query': query,
            'positive_text': pos_text,
            'negative_text': neg_text
        })
    
    return pairs

# ============================================
# 2. ДАННЫЕ ДЛЯ ИЗВЛЕЧЕНИЯ КЛЮЧЕЙ (NER)
# ============================================

# Шаблоны ключей разных форматов
KEY_TEMPLATES = [
    # Steam style: XXXXX-XXXXX-XXXXX
    lambda: f"{random_key(5)}-{random_key(5)}-{random_key(5)}",
    # 4 parts: XXXX-XXXX-XXXX-XXXX
    lambda: f"{random_key(4)}-{random_key(4)}-{random_key(4)}-{random_key(4)}",
    # 5 parts: XXXXX-XXXXX-XXXXX-XXXXX-XXXXX
    lambda: f"{random_key(5)}-{random_key(5)}-{random_key(5)}-{random_key(5)}-{random_key(5)}",
    # long key without hyphens
    lambda: random_key(16),
    lambda: random_key(20),
    # mixed case
    lambda: f"{random_key(5, digits=False)}-{random_key(5)}-{random_key(5, digits=False)}",
]

def random_key(length, digits=True, letters=True):
    """Генерирует случайный ключ заданной длины"""
    import random
    import string
    chars = ''
    if letters:
        chars += string.ascii_uppercase
    if digits:
        chars += string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def generate_ner_examples(num_examples=500):
    """
    Генерирует примеры для NER с размеченными ключами.
    Возвращает список словарей с текстом и метками.
    """
    examples = []
    
    # Шаблоны предложений, в которые вставляются ключи
    sentence_templates = [
        "Here is your key: {key}",
        "Claim your free key: {key}",
        "Use code {key} to activate",
        "Your Steam key: {key}",
        "GOG key: {key}",
        "Key: {key}",
        "Activation code: {key}",
        "Copy this key: {key}",
        "Redeem at: {key}",
        "Free game key: {key}",
        "Получите ключ: {key}",
        "Ваш ключ: {key}",
        "Ключ активации: {key}",
        "Steam ключ: {key}",
    ]
    
    # Контекстные фразы до и после ключа
    prefixes = [
        "Congratulations! ", "Limited time offer! ", "Hurry up! ",
        "Only today! ", "Exclusive giveaway! ", "New! ",
        "Don't miss! ", "First come first served! ", ""
    ]
    suffixes = [
        " Enjoy!", " Have fun!", " Act fast!", " Valid for 24 hours.",
        " Share with friends!", " Good luck!", "", ""
    ]
    
    for _ in range(num_examples):
        # Генерируем ключ
        key_template = random.choice(KEY_TEMPLATES)
        key = key_template()
        
        # Выбираем шаблон предложения
        template = random.choice(sentence_templates)
        sentence = template.format(key=key)
        
        # Добавляем контекст
        prefix = random.choice(prefixes)
        suffix = random.choice(suffixes)
        full_text = prefix + sentence + suffix
        
        # Размечаем BIO-метки (O, B-KEY, I-KEY)
        # Для простоты будем считать, что ключ — это непрерывная последовательность
        # токенов, которые мы получим через пробел
        words = full_text.split()
        labels = []
        key_tokens = key.split('-') if '-' in key else [key]
        
        i = 0
        while i < len(words):
            word = words[i]
            if word in key_tokens or word == key:
                # Начало ключа
                labels.append('B-KEY')
                # Последующие части ключа (если ключ разбит на несколько токенов)
                j = i + 1
                while j < len(words) and words[j] in key_tokens:
                    labels.append('I-KEY')
                    j += 1
                i = j
            else:
                labels.append('O')
                i += 1
        
        # Сохраняем пример в формате для Hugging Face Dataset
        # Но для удобства используем простой JSON
        examples.append({
            'text': full_text,
            'key': key,
            'labels': labels,
            'tokens': words
        })
    
    return examples

# ============================================
# 3. СОХРАНЕНИЕ ДАННЫХ В ФАЙЛЫ
# ============================================

def save_search_data(pairs, filename='training_pairs.csv'):
    """Сохраняет пары для поиска в CSV"""
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['query', 'positive_text', 'negative_text'])
        writer.writeheader()
        writer.writerows(pairs)
    print(f"✅ Сохранено {len(pairs)} пар поиска в {filename}")

def save_ner_data(examples, filename='key_extraction_data.json'):
    """Сохраняет NER примеры в JSON"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(examples, f, indent=2, ensure_ascii=False)
    print(f"✅ Сохранено {len(examples)} NER примеров в {filename}")

def save_ner_data_for_transformers(examples, filename='ner_dataset.json'):
    """
    Сохраняет NER данные в формате, готовом для использования в transformers.
    Каждый пример: {"id": "...", "tokens": [...], "ner_tags": [...]}
    """
    dataset = []
    for idx, ex in enumerate(examples):
        # Преобразуем строковые метки в числа
        label2id = {"O": 0, "B-KEY": 1, "I-KEY": 2}
        ner_tags = [label2id[label] for label in ex['labels']]
        
        dataset.append({
            'id': str(idx),
            'tokens': ex['tokens'],
            'ner_tags': ner_tags
        })
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)
    print(f"✅ Сохранён transformers-совместимый датасет в {filename}")

# ============================================
# 4. ЗАПУСК ГЕНЕРАЦИИ
# ============================================

if __name__ == "__main__":
    print("🔧 ГЕНЕРАЦИЯ ОБУЧАЮЩИХ ДАННЫХ ДЛЯ NEUROKEY")
    print("=" * 60)
    
    # Создаём папку для данных, если её нет
    Path("training_data").mkdir(exist_ok=True)
    
    # Генерируем данные для поиска
    print("\n📊 Генерация данных для поиска раздач...")
    search_pairs = generate_search_pairs(2000)
    save_search_data(search_pairs, "training_data/search_pairs.csv")
    
    # Генерируем данные для извлечения ключей
    print("\n🔑 Генерация данных для извлечения ключей...")
    ner_examples = generate_ner_examples(1000)
    save_ner_data(ner_examples, "training_data/ner_examples.json")
    save_ner_data_for_transformers(ner_examples, "training_data/ner_dataset.json")
    
    print("\n" + "=" * 60)
    print("✅ ГЕНЕРАЦИЯ ЗАВЕРШЕНА!")
    print("📁 Файлы сохранены в папке 'training_data'")
    print("\nТеперь вы можете использовать эти данные для дообучения моделей:")
    print("  - Для поиска: training_data/search_pairs.csv")
    print("  - Для извлечения ключей: training_data/ner_dataset.json")
    print("\nСкрипты для дообучения я уже показывал ранее.")