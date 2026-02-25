# account_manager.py
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet
from typing import Dict, Optional, List

class AccountManager:
    """Управляет сохранёнными учётными записями Steam (логин, пароль, shared_secret)."""
    
    CONFIG_DIR = Path("data/accounts")
    KEY_FILE = CONFIG_DIR / "key.bin"
    ACCOUNTS_FILE = CONFIG_DIR / "accounts.enc"
    
    def __init__(self):
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._key = self._load_or_create_key()
        self._cipher = Fernet(self._key)
        self.accounts = self._load_accounts()
    
    def _load_or_create_key(self) -> bytes:
        """Загружает или создаёт ключ шифрования."""
        if self.KEY_FILE.exists():
            with open(self.KEY_FILE, 'rb') as f:
                return f.read()
        else:
            key = Fernet.generate_key()
            with open(self.KEY_FILE, 'wb') as f:
                f.write(key)
            return key
    
    def _load_accounts(self) -> Dict[str, Dict]:
        """Загружает зашифрованные аккаунты."""
        if not self.ACCOUNTS_FILE.exists():
            return {}
        try:
            with open(self.ACCOUNTS_FILE, 'rb') as f:
                enc_data = f.read()
            dec_data = self._cipher.decrypt(enc_data)
            return json.loads(dec_data.decode('utf-8'))
        except:
            return {}
    
    def _save_accounts(self):
        """Сохраняет аккаунты в зашифрованном виде."""
        data = json.dumps(self.accounts, indent=2).encode('utf-8')
        enc_data = self._cipher.encrypt(data)
        with open(self.ACCOUNTS_FILE, 'wb') as f:
            f.write(enc_data)
    
    def add_account(self, login: str, password: str, shared_secret: str = ""):
        """Добавляет или обновляет аккаунт."""
        self.accounts[login] = {
            'login': login,
            'password': password,
            'shared_secret': shared_secret
        }
        self._save_accounts()
    
    def remove_account(self, login: str):
        """Удаляет аккаунт."""
        if login in self.accounts:
            del self.accounts[login]
            self._save_accounts()
    
    def get_account(self, login: str) -> Optional[Dict]:
        """Возвращает данные аккаунта."""
        return self.accounts.get(login)
    
    def list_accounts(self) -> List[str]:
        """Возвращает список логинов."""
        return list(self.accounts.keys())