# validator.py
import subprocess
import logging
import os
import json
import threading
import queue
import select
import time
from typing import Dict, Optional
from pathlib import Path

from steam_2fa import Steam2FA
from account_manager import AccountManager

logger = logging.getLogger(__name__)

class SteamExeValidator:
    def __init__(self, exe_path: str = "SteamValidator.exe"):
        self.exe_path = exe_path
        self.available = os.path.exists(self.exe_path)
        self.account_manager = AccountManager()

        if not self.available:
            logger.warning(f"SteamValidator.exe не найден по пути {self.exe_path}. Валидация Steam будет недоступна.")

    def validate(self, key: str, login: str = None, password: str = None, 
                 twofa_callback=None, remember: bool = False) -> Dict:
        """
        Запускает SteamValidator.exe и возвращает результат.
        Если login не указан, используется первый сохранённый аккаунт.
        """
        if not self.available:
            return {'valid': False, 'game': '', 'message': 'SteamValidator.exe не найден', 'status': 'error'}

        # Определяем учётные данные
        account = None
        effective_login = login
        effective_password = password

        if not effective_login and not effective_password:
            # Берём первый сохранённый аккаунт
            accounts = self.account_manager.list_accounts()
            if accounts:
                effective_login = accounts[0]
                account = self.account_manager.get_account(effective_login)
                effective_password = account['password']
            else:
                return {'valid': False, 'game': '', 'message': 'Нет сохранённых аккаунтов', 'status': 'error'}
        elif effective_login and not effective_password:
            # Ищем по логину
            account = self.account_manager.get_account(effective_login)
            if account:
                effective_password = account['password']
            else:
                return {'valid': False, 'game': '', 'message': f'Аккаунт {effective_login} не найден', 'status': 'error'}

        # Генерируем 2FA-код, если есть shared_secret
        two_factor_code = None
        if account and account.get('shared_secret'):
            two_factor_code = Steam2FA.generate_code(account['shared_secret'])
            logger.debug(f"[2FA] Сгенерирован код для {effective_login}: {two_factor_code}")

        # Формируем команду
        cmd = [self.exe_path, effective_login, effective_password, key]
        if two_factor_code:
            cmd.append(two_factor_code)

        try:
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                encoding='utf-8',
                errors='replace'
            )
        except Exception as e:
            logger.error(f"Ошибка запуска SteamValidator: {e}")
            return {'valid': False, 'game': '', 'message': str(e), 'status': 'error'}

        stdout_lines = []
        twofa_requested = False

        start_time = time.time()
        timeout = 120

        while True:
            if time.time() - start_time > timeout:
                process.terminate()
                return {'valid': False, 'game': '', 'message': 'Таймаут выполнения', 'status': 'timeout'}

            try:
                if select.select([process.stdout], [], [], 1)[0]:
                    line = process.stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    stdout_lines.append(line)
                    logger.debug(f"SteamValidator: {line}")

                    # Если программа запрашивает код 2FA (но у нас уже есть сгенерированный код, этого не должно случиться)
                    if "Требуется код подтверждения" in line and not twofa_callback:
                        twofa_requested = True
                        if twofa_callback:
                            code = twofa_callback()
                            if code:
                                process.stdin.write(code + '\n')
                                process.stdin.flush()
                            else:
                                process.terminate()
                                return {'valid': False, 'game': '', 'message': 'Код не предоставлен', 'status': 'need2fa'}
            except (IOError, OSError) as e:
                logger.error(f"Ошибка чтения вывода: {e}")
                break

        process.wait(timeout=10)

        # Парсим результат
        result = {'valid': False, 'game': '', 'message': '', 'status': 'error'}
        for line in stdout_lines:
            if line.startswith('RESULT:'):
                result['status'] = line[7:].strip()
            elif line.startswith('GAME:'):
                result['game'] = line[5:].strip()
            elif line.startswith('MESSAGE:'):
                result['message'] = line[8:].strip()

        status = result.get('status', 'error')
        status_messages = {
            'success': ('valid', True, 'Ключ успешно активирован'),
            'duplicate': ('duplicate', False, 'Ключ уже активирован на другом аккаунте'),
            'invalid': ('invalid', False, 'Недействительный ключ'),
            'invalid_format': ('invalid_format', False, 'Неверный формат ключа'),
            'already_used': ('already_used', False, 'Ключ уже был использован'),
            'region_locked': ('region_locked', False, 'Ключ ограничен по региону'),
            'missing_game': ('missing_game', False, 'Для активации требуется базовая игра'),
            'expired': ('expired', False, 'Срок действия ключа истёк'),
            'revoked': ('revoked', False, 'Ключ был отозван разработчиком'),
            'limit_exceeded': ('limit_exceeded', False, 'Превышен лимит активаций'),
            'service_unavailable': ('service_unavailable', False, 'Сервис Steam временно недоступен'),
            'timeout': ('timeout', False, 'Превышено время ожидания'),
            'access_denied': ('access_denied', False, 'Нет прав для активации'),
            'need2fa': ('need2fa', False, 'Требуется код двухфакторной аутентификации'),
            'needauth': ('needauth', False, 'Требуется код подтверждения'),
        }

        if status in status_messages:
            mapped_status, valid, default_message = status_messages[status]
            return {
                'valid': valid,
                'game': result.get('game', ''),
                'message': result.get('message', default_message),
                'status': mapped_status
            }
        else:
            return {
                'valid': False,
                'game': '',
                'message': result.get('message', 'Неизвестная ошибка'),
                'status': 'error'
            }