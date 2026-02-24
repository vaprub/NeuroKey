# models_data.py
from dataclasses import dataclass, asdict
from typing import List, Optional
from datetime import datetime

@dataclass
class GiveawayResult:
    """Информация о раздаче (без ключей, которые хранятся отдельно)."""
    title: str
    url: str
    source_site: str
    description: str
    confidence_score: float
    detected_at: str = None
    is_active: bool = True
    id: Optional[int] = None  # будет присвоено после сохранения в БД

    def __post_init__(self):
        if self.detected_at is None:
            self.detected_at = datetime.now().isoformat()

    def to_dict(self):
        return asdict(self)


@dataclass
class KeyResult:
    """Информация о найденном ключе, связанном с раздачей."""
    giveaway_id: int
    key: str
    platform: Optional[str] = None          # определённая платформа
    game_name: Optional[str] = None          # предположительное название игры
    is_active: bool = True                    # активен ли ключ (не использован)
    user_corrected_platform: Optional[str] = None  # исправление пользователя
    user_corrected_game: Optional[str] = None      # исправление пользователя
    user_checked: bool = False                    # проверял ли пользователь
    id: Optional[int] = None
    detected_at: str = None

    def __post_init__(self):
        if self.detected_at is None:
            self.detected_at = datetime.now().isoformat()

    def to_dict(self):
        return asdict(self)