# database.py
import sqlite3
import json
from datetime import datetime
from typing import List, Optional, Tuple
from contextlib import contextmanager
import logging

from models_data import GiveawayResult, KeyResult

logger = logging.getLogger(__name__)


class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def init_database(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS giveaways (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT UNIQUE NOT NULL,
                    source_site TEXT NOT NULL,
                    description TEXT,
                    confidence_score REAL,
                    detected_at TIMESTAMP,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    giveaway_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    platform TEXT,
                    game_name TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    user_corrected_platform TEXT,
                    user_corrected_game TEXT,
                    user_checked BOOLEAN DEFAULT 0,
                    validation_status TEXT DEFAULT 'pending',
                    validation_date TIMESTAMP,
                    validation_details TEXT,
                    detected_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (giveaway_id) REFERENCES giveaways (id) ON DELETE CASCADE,
                    UNIQUE(giveaway_id, key)
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS feedback_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_id INTEGER NOT NULL,
                    original_platform TEXT,
                    original_game TEXT,
                    corrected_platform TEXT,
                    corrected_game TEXT,
                    corrected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (key_id) REFERENCES keys (id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_giveaway_url ON giveaways(url)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_keys_giveaway ON keys(giveaway_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_keys_platform ON keys(platform)')
            logger.info("База данных инициализирована (с таблицей keys и полями валидации)")

    # ----- Работа с раздачами -----
    def add_giveaway(self, giveaway: GiveawayResult) -> int:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO giveaways
                (title, url, source_site, description, confidence_score, detected_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                giveaway.title,
                giveaway.url,
                giveaway.source_site,
                giveaway.description,
                giveaway.confidence_score,
                giveaway.detected_at,
                giveaway.is_active
            ))
            cursor.execute('SELECT id FROM giveaways WHERE url = ?', (giveaway.url,))
            row = cursor.fetchone()
            return row['id'] if row else None

    def get_giveaway_by_id(self, giveaway_id: int) -> Optional[GiveawayResult]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM giveaways WHERE id = ?', (giveaway_id,))
            row = cursor.fetchone()
            if row:
                return GiveawayResult(
                    title=row['title'],
                    url=row['url'],
                    source_site=row['source_site'],
                    description=row['description'],
                    confidence_score=row['confidence_score'],
                    detected_at=row['detected_at'],
                    is_active=bool(row['is_active']),
                    id=row['id']
                )
            return None

    def get_all_giveaways(self) -> List[GiveawayResult]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM giveaways ORDER BY detected_at DESC')
            return [
                GiveawayResult(
                    title=row['title'],
                    url=row['url'],
                    source_site=row['source_site'],
                    description=row['description'],
                    confidence_score=row['confidence_score'],
                    detected_at=row['detected_at'],
                    is_active=bool(row['is_active']),
                    id=row['id']
                )
                for row in cursor.fetchall()
            ]

    # ----- Работа с ключами -----
    def add_keys(self, keys: List[KeyResult]):
        if not keys:
            return
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for k in keys:
                try:
                    cursor.execute('''
                        INSERT OR IGNORE INTO keys
                        (giveaway_id, key, platform, game_name, is_active, detected_at, validation_status)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        k.giveaway_id,
                        k.key,
                        k.platform,
                        k.game_name,
                        k.is_active,
                        k.detected_at,
                        k.validation_status or 'pending'
                    ))
                except Exception as e:
                    logger.error(f"Ошибка добавления ключа {k.key}: {e}")

    def get_keys_for_giveaway(self, giveaway_id: int) -> List[KeyResult]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM keys WHERE giveaway_id = ? ORDER BY id', (giveaway_id,))
            return [
                KeyResult(
                    giveaway_id=row['giveaway_id'],
                    key=row['key'],
                    platform=row['platform'],
                    game_name=row['game_name'],
                    is_active=bool(row['is_active']),
                    user_corrected_platform=row['user_corrected_platform'],
                    user_corrected_game=row['user_corrected_game'],
                    user_checked=bool(row['user_checked']),
                    validation_status=row['validation_status'],
                    validation_date=row['validation_date'],
                    validation_details=row['validation_details'],
                    id=row['id'],
                    detected_at=row['detected_at']
                )
                for row in cursor.fetchall()
            ]

    def get_keys_by_giveaway_ids(self, giveaway_ids: List[int]) -> List[KeyResult]:
        if not giveaway_ids:
            return []
        placeholders = ','.join(['?'] * len(giveaway_ids))
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f'SELECT * FROM keys WHERE giveaway_id IN ({placeholders})', giveaway_ids)
            return [
                KeyResult(
                    giveaway_id=row['giveaway_id'],
                    key=row['key'],
                    platform=row['platform'],
                    game_name=row['game_name'],
                    is_active=bool(row['is_active']),
                    user_corrected_platform=row['user_corrected_platform'],
                    user_corrected_game=row['user_corrected_game'],
                    user_checked=bool(row['user_checked']),
                    validation_status=row['validation_status'],
                    validation_date=row['validation_date'],
                    validation_details=row['validation_details'],
                    id=row['id'],
                    detected_at=row['detected_at']
                )
                for row in cursor.fetchall()
            ]

    def get_all_keys(self, include_empty_giveaways=False) -> List[Tuple[GiveawayResult, List[KeyResult]]]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM giveaways ORDER BY detected_at DESC')
            giveaways = cursor.fetchall()
            result = []
            for g_row in giveaways:
                giveaway = GiveawayResult(
                    title=g_row['title'],
                    url=g_row['url'],
                    source_site=g_row['source_site'],
                    description=g_row['description'],
                    confidence_score=g_row['confidence_score'],
                    detected_at=g_row['detected_at'],
                    is_active=bool(g_row['is_active']),
                    id=g_row['id']
                )
                cursor.execute('SELECT * FROM keys WHERE giveaway_id = ? ORDER BY id', (g_row['id'],))
                keys_rows = cursor.fetchall()
                keys = [
                    KeyResult(
                        giveaway_id=row['giveaway_id'],
                        key=row['key'],
                        platform=row['platform'],
                        game_name=row['game_name'],
                        is_active=bool(row['is_active']),
                        user_corrected_platform=row['user_corrected_platform'],
                        user_corrected_game=row['user_corrected_game'],
                        user_checked=bool(row['user_checked']),
                        validation_status=row['validation_status'],
                        validation_date=row['validation_date'],
                        validation_details=row['validation_details'],
                        id=row['id'],
                        detected_at=row['detected_at']
                    )
                    for row in keys_rows
                ]
                if include_empty_giveaways or keys:
                    result.append((giveaway, keys))
            return result

    def get_unvalidated_keys(self, limit: int = 100) -> List[KeyResult]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM keys WHERE validation_status = 'pending' ORDER BY detected_at DESC LIMIT ?
            ''', (limit,))
            return [
                KeyResult(
                    giveaway_id=row['giveaway_id'],
                    key=row['key'],
                    platform=row['platform'],
                    game_name=row['game_name'],
                    is_active=bool(row['is_active']),
                    user_corrected_platform=row['user_corrected_platform'],
                    user_corrected_game=row['user_corrected_game'],
                    user_checked=bool(row['user_checked']),
                    validation_status=row['validation_status'],
                    validation_date=row['validation_date'],
                    validation_details=row['validation_details'],
                    id=row['id'],
                    detected_at=row['detected_at']
                )
                for row in cursor.fetchall()
            ]

    def update_key_validation(self, key_id: int, status: str, details: str = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE keys
                SET validation_status = ?, validation_date = ?, validation_details = ?
                WHERE id = ?
            ''', (status, datetime.now().isoformat(), details, key_id))

    def update_key_correction(self, key_id: int, corrected_platform: str = None, corrected_game: str = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT platform, game_name FROM keys WHERE id = ?', (key_id,))
            row = cursor.fetchone()
            if not row:
                return
            original_platform = row['platform']
            original_game = row['game_name']

            update_fields = []
            params = []
            if corrected_platform is not None:
                update_fields.append('user_corrected_platform = ?')
                params.append(corrected_platform)
            if corrected_game is not None:
                update_fields.append('user_corrected_game = ?')
                params.append(corrected_game)
            update_fields.append('user_checked = 1')
            if not update_fields:
                return
            params.append(key_id)
            cursor.execute(f'UPDATE keys SET {", ".join(update_fields)} WHERE id = ?', params)

            cursor.execute('''
                INSERT INTO feedback_keys (key_id, original_platform, original_game, corrected_platform, corrected_game)
                VALUES (?, ?, ?, ?, ?)
            ''', (key_id, original_platform, original_game, corrected_platform, corrected_game))

    def get_statistics(self) -> dict:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM giveaways')
            total_giveaways = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM keys')
            total_keys = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM keys WHERE user_checked = 1')
            checked_keys = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM keys WHERE validation_status = "valid"')
            valid_keys = cursor.fetchone()[0]
            cursor.execute('SELECT COUNT(*) FROM keys WHERE validation_status = "invalid"')
            invalid_keys = cursor.fetchone()[0]
            today = datetime.now().date().isoformat()
            cursor.execute('SELECT COUNT(*) FROM keys WHERE date(detected_at) = ?', (today,))
            today_keys = cursor.fetchone()[0]
            return {
                'total_giveaways': total_giveaways,
                'total_keys': total_keys,
                'checked_keys': checked_keys,
                'valid_keys': valid_keys,
                'invalid_keys': invalid_keys,
                'today_keys': today_keys
            }