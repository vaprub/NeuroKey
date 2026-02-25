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
    id: Optional[int] = None

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
    platform: Optional[str] = None
    game_name: Optional[str] = None
    is_active: bool = True
    user_corrected_platform: Optional[str] = None
    user_corrected_game: Optional[str] = None
    user_checked: bool = False
    validation_status: Optional[str] = 'pending'  # pending, valid, invalid, error
    validation_date: Optional[str] = None
    validation_details: Optional[str] = None       # JSON с ответом API
    id: Optional[int] = None
    detected_at: str = None

    def __post_init__(self):
        if self.detected_at is None:
            self.detected_at = datetime.now().isoformat()

    def to_dict(self):
        return asdict(self)