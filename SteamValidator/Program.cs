using System;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;
using System.Text.Json;
using System.Collections.Generic;
using SteamKit2;
using ProtoBuf;
using SteamAuth; // требуется NuGet пакет SteamAuthStandart

namespace SteamKeyValidator
{
    class Program
    {
        static async Task<int> Main(string[] args)
        {
            if (args.Length < 3)
            {
                Console.Error.WriteLine("Использование: SteamValidator.exe <логин> <пароль> <ключ>");
                return 1;
            }

            string username = args[0];
            string password = args[1];
            string key = args[2];

            Console.WriteLine($"[INFO] Запуск валидации для пользователя {username}");

            // Если нет файла с секретами, выполняем привязку
            if (!File.Exists("steamguard.json"))
            {
                Console.WriteLine("[2FA] Файл steamguard.json не найден. Запускаем процедуру привязки аутентификатора...");
                var linker = new AuthenticatorLinker();
                bool success = await linker.LinkNewAuthenticator(username, password);
                if (!success)
                {
                    Console.WriteLine("[2FA] Не удалось привязать аутентификатор. Программа завершена.");
                    return 1;
                }
                Console.WriteLine("[2FA] Привязка завершена. Запустите программу снова для валидации ключа.");
                return 0;
            }

            // Основная валидация
            var validator = new SteamKeyValidator();
            var timeoutTask = Task.Delay(180000);
            var validationTask = validator.ValidateKey(username, password, key);
            var completedTask = await Task.WhenAny(validationTask, timeoutTask);

            if (completedTask == timeoutTask)
            {
                Console.WriteLine("[ERROR] Таймаут: Steam не отвечает в течение 180 секунд");
                return 1;
            }

            var result = await validationTask;

            Console.WriteLine($"ИТОГОВЫЙ РЕЗУЛЬТАТ:");
            Console.WriteLine($"RESULT:{result.Status}");
            if (!string.IsNullOrEmpty(result.Message))
                Console.WriteLine($"MESSAGE:{result.Message}");

            return result.Status == "success" ? 0 : 1;
        }
    }

    public class ValidationResult
    {
        public string Status { get; set; } = "pending";
        public string Message { get; set; } = "";
    }

    [ProtoContract]
    class CMsgClientRegisterKey : IExtensible
    {
        private IExtension? __pbn__extensionData;
        IExtension IExtensible.GetExtensionObject(bool createIfMissing)
            => Extensible.GetExtensionObject(ref __pbn__extensionData, createIfMissing);

        [ProtoMember(1)]
        public string key { get; set; } = "";
    }

    public class SteamKeyValidator
    {
        private SteamClient _steamClient = null!;
        private CallbackManager _callbackManager = null!;
        private SteamUser _steamUser = null!;
        private byte[]? _sentryFile;
        private string? _loginKey;
        private string _username = null!;
        private string _password = null!;
        private string? _twoFactorCode;
        private string? _authCode;
        private string _keyToValidate = null!;
        private ValidationResult _validationResult = null!;
        private TaskCompletionSource<ValidationResult>? _tcs;
        private bool _isRunning = true;
        private bool _loginSuccess = false;
        private int _codeAttempts = 0;
        private const int MaxCodeAttempts = 3;
        private const string SentryFile = "sentry.bin";
        private const string SteamGuardFile = "steamguard.json";
        private SteamGuardGenerator? _steamGuard;

        private void LoadSteamGuard()
        {
            try
            {
                if (File.Exists(SteamGuardFile))
                {
                    string json = File.ReadAllText(SteamGuardFile);
                    var secrets = JsonSerializer.Deserialize<Dictionary<string, string>>(json);
                    if (secrets != null && secrets.TryGetValue("shared_secret", out string? sharedSecret))
                    {
                        _steamGuard = new SteamGuardGenerator(sharedSecret);
                        Console.WriteLine("[2FA] Загружен shared_secret из steamguard.json");
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[2FA] Ошибка загрузки steamguard.json: {ex.Message}");
            }
        }

        public async Task<ValidationResult> ValidateKey(string username, string password, string key)
        {
            _username = username;
            _password = password;
            _keyToValidate = key;
            _validationResult = new ValidationResult();
            _tcs = new TaskCompletionSource<ValidationResult>();

            Console.WriteLine("[STEP 1] Создание конфигурации Steam...");
            var config = SteamConfiguration.Create(b => b
                .WithProtocolTypes(ProtocolTypes.Tcp | ProtocolTypes.WebSocket)
            );

            Console.WriteLine("[STEP 2] Создание клиента Steam...");
            _steamClient = new SteamClient(config);
            _callbackManager = new CallbackManager(_steamClient);
            _steamUser = _steamClient.GetHandler<SteamUser>()!;

            Console.WriteLine("[STEP 3] Подписка на события...");
            _callbackManager.Subscribe<SteamClient.ConnectedCallback>(OnConnected);
            _callbackManager.Subscribe<SteamClient.DisconnectedCallback>(OnDisconnected);
            _callbackManager.Subscribe<SteamUser.LoggedOnCallback>(OnLoggedOn);
            _callbackManager.Subscribe<SteamUser.LoggedOffCallback>(OnLoggedOff);
            _callbackManager.Subscribe<SteamUser.LoginKeyCallback>(OnLoginKey);
            _callbackManager.Subscribe<SteamUser.UpdateMachineAuthCallback>(OnMachineAuth);
            _callbackManager.Subscribe<SteamApps.PurchaseResponseCallback>(OnPurchaseResult);

            if (File.Exists(SentryFile))
            {
                var fi = new FileInfo(SentryFile);
                Console.WriteLine($"[SENTRY] Найден файл: {Path.GetFullPath(SentryFile)} (размер: {fi.Length} байт)");
                _sentryFile = File.ReadAllBytes(SentryFile);
            }
            else
            {
                Console.WriteLine($"[SENTRY] Файл не найден: {Path.GetFullPath(SentryFile)}");
            }

            // Загружаем секреты 2FA, если есть
            LoadSteamGuard();

            // ===== ДИАГНОСТИКА СЕТИ =====
            Console.WriteLine("\n[DIAG] Диагностика сети:");
            try
            {
                Console.Write("  DNS steamcommunity.com... ");
                var hostEntry = Dns.GetHostEntry("steamcommunity.com");
                Console.WriteLine($"OK, найдено IP: {hostEntry.AddressList.Length}");
                foreach (var ip in hostEntry.AddressList)
                {
                    Console.WriteLine($"    - {ip}");
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"FAIL: {ex.Message}");
            }

            try
            {
                Console.Write("  TCP подключение к 208.64.200.52:27017... ");
                using (var tcpClient = new TcpClient())
                {
                    var connectTask = tcpClient.ConnectAsync("208.64.200.52", 27017);
                    if (await Task.WhenAny(connectTask, Task.Delay(5000)) == connectTask)
                    {
                        Console.WriteLine("OK");
                        tcpClient.Close();
                    }
                    else
                    {
                        Console.WriteLine("таймаут");
                    }
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"FAIL: {ex.Message}");
            }
            Console.WriteLine();

            Console.WriteLine("[STEP 4] Запуск подключения...");
            try
            {
                _steamClient.Connect();
                Console.WriteLine("[CONNECT] Запрос на подключение отправлен");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ERROR] Ошибка при подключении: {ex.Message}");
                _validationResult.Status = "error";
                _validationResult.Message = $"Ошибка подключения: {ex.Message}";
                return _validationResult;
            }

            Console.WriteLine("[STEP 5] Ожидание ответа...");

            while (_isRunning)
            {
                _callbackManager.RunWaitCallbacks(TimeSpan.FromSeconds(1));
            }

            return await _tcs.Task;
        }

        private void OnConnected(SteamClient.ConnectedCallback callback)
        {
            Console.WriteLine("[ONCONNECTED] Подключено к Steam. Выполняю вход...");

            byte[]? sentryHash = null;
            if (_sentryFile != null)
            {
                sentryHash = CryptoHelper.SHAHash(_sentryFile);
                Console.WriteLine($"[SENTRY] Использую сохранённый sentry файл");
            }

            try
            {
                // Если есть секрет 2FA, генерируем код автоматически
                if (_steamGuard != null)
                {
                    _twoFactorCode = _steamGuard.GenerateCode();
                    Console.WriteLine($"[2FA] Сгенерирован код: {_twoFactorCode}");
                }

                _steamUser.LogOn(new SteamUser.LogOnDetails
                {
                    Username = _username,
                    Password = _password,
                    TwoFactorCode = _twoFactorCode,
                    AuthCode = _authCode,
                    SentryFileHash = sentryHash,
                    ShouldRememberPassword = true
                });
                Console.WriteLine("[LOGIN] Запрос отправлен");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ERROR] Ошибка при отправке запроса на вход: {ex.Message}");
                _validationResult.Status = "error";
                _validationResult.Message = $"Ошибка входа: {ex.Message}";
                _tcs?.TrySetResult(_validationResult);
                _isRunning = false;
            }
        }

        private void OnDisconnected(SteamClient.DisconnectedCallback callback)
        {
            Console.WriteLine($"[ONDISCONNECTED] Отключено. UserInitiated={callback.UserInitiated}");

            if (_validationResult.Status != "pending")
            {
                Console.WriteLine("[ONDISCONNECTED] Результат уже есть, завершаем цикл");
                _isRunning = false;
                return;
            }

            if (_loginSuccess)
            {
                Console.WriteLine("[ONDISCONNECTED] Успешный вход ранее, ожидаем ответа по ключу...");
                return;
            }

            if (_codeAttempts > 0 && !_loginSuccess)
            {
                Console.WriteLine("[RECONNECT] Ожидание 2 секунды перед переподключением...");
                Thread.Sleep(2000);
                _steamClient.Connect();
                return;
            }

            Console.WriteLine("[ONDISCONNECTED] Неожиданное отключение, завершаем с ошибкой");
            _validationResult.Status = "error";
            _validationResult.Message = "Отключено от Steam";
            _tcs?.TrySetResult(_validationResult);
            _isRunning = false;
        }

        private void OnLoggedOn(SteamUser.LoggedOnCallback callback)
        {
            Console.WriteLine($"[ONLOGGEDON] Результат: {callback.Result}");

            if (callback.Result == EResult.AccountLogonDenied)
            {
                _codeAttempts++;
                if (_codeAttempts > MaxCodeAttempts)
                {
                    Console.WriteLine("[2FA] Превышено количество попыток");
                    _validationResult.Status = "needauth";
                    _validationResult.Message = $"Требуется код подтверждения (попытки исчерпаны)";
                    _tcs?.TrySetResult(_validationResult);
                    _isRunning = false;
                    return;
                }

                Console.WriteLine($"[2FA] Требуется код подтверждения, отправлен на {callback.EmailDomain}");
                Console.Write($"[2FA] Введите код (попытка {_codeAttempts}/{MaxCodeAttempts}): ");
                _authCode = Console.ReadLine()?.Trim();

                if (string.IsNullOrEmpty(_authCode))
                {
                    Console.WriteLine("[2FA] Код не введён");
                    _validationResult.Status = "needauth";
                    _validationResult.Message = "Код не введён";
                    _tcs?.TrySetResult(_validationResult);
                    _isRunning = false;
                    return;
                }

                Console.WriteLine("[2FA] Код принят, ожидаем отключения и переподключения...");
                return;
            }
            else if (callback.Result == EResult.AccountLoginDeniedNeedTwoFactor)
            {
                _codeAttempts++;
                if (_codeAttempts > MaxCodeAttempts)
                {
                    Console.WriteLine("[2FA] Превышено количество попыток");
                    _validationResult.Status = "need2fa";
                    _validationResult.Message = "Требуется код двухфакторной аутентификации (попытки исчерпаны)";
                    _tcs?.TrySetResult(_validationResult);
                    _isRunning = false;
                    return;
                }

                Console.WriteLine($"[2FA] Требуется код двухфакторной аутентификации");
                Console.Write($"[2FA] Введите код из приложения (попытка {_codeAttempts}/{MaxCodeAttempts}): ");
                _twoFactorCode = Console.ReadLine()?.Trim();

                if (string.IsNullOrEmpty(_twoFactorCode))
                {
                    Console.WriteLine("[2FA] Код не введён");
                    _validationResult.Status = "need2fa";
                    _validationResult.Message = "Код не введён";
                    _tcs?.TrySetResult(_validationResult);
                    _isRunning = false;
                    return;
                }

                Console.WriteLine("[2FA] Код принят, ожидаем отключения и переподключения...");
                return;
            }
            else if (callback.Result == EResult.InvalidLoginAuthCode)
            {
                _codeAttempts++;
                if (_codeAttempts > MaxCodeAttempts)
                {
                    Console.WriteLine("[2FA] Превышено количество попыток");
                    _validationResult.Status = "error";
                    _validationResult.Message = "Неверный код подтверждения (попытки исчерпаны)";
                    _tcs?.TrySetResult(_validationResult);
                    _isRunning = false;
                    return;
                }

                Console.WriteLine($"[2FA] Неверный код подтверждения. Попытка {_codeAttempts}/{MaxCodeAttempts}");
                Console.Write("[2FA] Введите код ещё раз: ");
                _authCode = Console.ReadLine()?.Trim();

                if (string.IsNullOrEmpty(_authCode))
                {
                    Console.WriteLine("[2FA] Код не введён");
                    _validationResult.Status = "error";
                    _validationResult.Message = "Код не введён";
                    _tcs?.TrySetResult(_validationResult);
                    _isRunning = false;
                    return;
                }

                Console.WriteLine("[2FA] Код принят, ожидаем отключения и переподключения...");
                return;
            }
            else if (callback.Result != EResult.OK)
            {
                Console.WriteLine($"[ERROR] Ошибка входа: {callback.Result}");
                _validationResult.Status = "error";
                _validationResult.Message = $"Ошибка входа: {callback.Result}";
                _tcs?.TrySetResult(_validationResult);
                _isRunning = false;
                return;
            }

            Console.WriteLine("[SUCCESS] Вход выполнен успешно!");
            _loginSuccess = true;
            _codeAttempts = 0;

            Console.WriteLine($"[KEY] Отправка ключа на активацию: {_keyToValidate}");
            try
            {
                var registerKeyMsg = new ClientMsgProtobuf<CMsgClientRegisterKey>(EMsg.ClientRegisterKey);
                registerKeyMsg.Body.key = _keyToValidate;
                _steamClient.Send(registerKeyMsg);
                Console.WriteLine("[KEY] Ключ отправлен, ожидаю ответ...");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[ERROR] Ошибка при отправке ключа: {ex.Message}");
                _validationResult.Status = "error";
                _validationResult.Message = $"Ошибка отправки ключа: {ex.Message}";
                _tcs?.TrySetResult(_validationResult);
                _isRunning = false;
            }
        }

        private void OnLoggedOff(SteamUser.LoggedOffCallback callback)
        {
            Console.WriteLine($"[LOGGEDOFF] Выход из Steam: {callback.Result}");
            if (_tcs != null && !_tcs.Task.IsCompleted && _validationResult.Status == "pending")
            {
                _validationResult.Status = "error";
                _validationResult.Message = "Сессия завершена";
                _tcs.TrySetResult(_validationResult);
            }
            _isRunning = false;
        }

        private void OnLoginKey(SteamUser.LoginKeyCallback callback)
        {
            _loginKey = callback.LoginKey;
            Console.WriteLine("[LOGINKEY] Получен LoginKey (не используется)");
        }

        private void OnMachineAuth(SteamUser.UpdateMachineAuthCallback callback)
        {
            Console.WriteLine("[SENTRY] Сохранение sentry файла...");

            try
            {
                File.WriteAllBytes(SentryFile, callback.Data);
                _steamUser.SendMachineAuthResponse(new SteamUser.MachineAuthDetails
                {
                    JobID = callback.JobID,
                    FileName = callback.FileName,
                    BytesWritten = callback.BytesToWrite,
                    FileSize = callback.Data.Length,
                    Offset = callback.Offset,
                    Result = EResult.OK,
                    LastError = 0,
                    OneTimePassword = callback.OneTimePassword,
                    SentryFileHash = CryptoHelper.SHAHash(callback.Data),
                });

                _sentryFile = callback.Data;
                Console.WriteLine("[SENTRY] Файл сохранён.");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[SENTRY] Ошибка сохранения: {ex.Message}");
            }
        }

        private void OnPurchaseResult(SteamApps.PurchaseResponseCallback callback)
        {
            Console.WriteLine("\n[PURCHASE] ПОЛУЧЕН ОТВЕТ ОТ STEAM");
            Console.WriteLine($"  Результат: {callback.Result}");
            Console.WriteLine($"  Детальный результат: {callback.PurchaseResultDetail}");

            string status;
            string message;

            switch (callback.Result)
            {
                case EResult.OK:
                    status = "success";
                    message = "Ключ успешно активирован";
                    if (callback.PurchaseReceiptInfo != null)
                    {
                        try
                        {
                            var lineItems = callback.PurchaseReceiptInfo["lineitems"].Children;
                            if (lineItems.Count > 0)
                            {
                                var game = lineItems[0]["ItemDescription"].AsString();
                                if (!string.IsNullOrEmpty(game))
                                {
                                    message += $". Игра: {game}";
                                }
                            }
                        }
                        catch { }
                    }
                    break;

                case EResult.Fail:
                    switch (callback.PurchaseResultDetail)
                    {
                        case EPurchaseResultDetail.DuplicateActivationCode:
                            status = "duplicate";
                            message = "Ключ уже был активирован ранее";
                            break;
                        case EPurchaseResultDetail.BadActivationCode:
                            status = "invalid_format";
                            message = "Неверный формат ключа";
                            break;
                        case EPurchaseResultDetail.AlreadyPurchased:
                            status = "already_used";
                            message = "Ключ уже был использован";
                            break;
                        case EPurchaseResultDetail.DoesNotOwnRequiredApp:
                            status = "missing_game";
                            message = "Для активации требуется базовая игра";
                            break;
                        case EPurchaseResultDetail.RestrictedCountry:
                            status = "region_locked";
                            message = "Ключ ограничен по региону";
                            break;
                        case EPurchaseResultDetail.CancelledByUser:
                            status = "cancelled";
                            message = "Активация отменена пользователем";
                            break;
                        case EPurchaseResultDetail.RateLimited:
                            status = "rate_limited";
                            message = "Слишком много попыток, попробуйте позже";
                            break;
                        default:
                            status = "fail";
                            message = $"Ошибка активации: {callback.PurchaseResultDetail}";
                            break;
                    }
                    break;

                case EResult.DuplicateName:
                    status = "duplicate";
                    message = "Ключ уже активирован на другом аккаунте";
                    break;

                case EResult.Invalid:
                case EResult.InvalidParam:
                    status = "invalid";
                    message = "Недействительный ключ";
                    break;

                case EResult.Expired:
                    status = "expired";
                    message = "Срок действия ключа истёк";
                    break;

                case EResult.Revoked:
                    status = "revoked";
                    message = "Ключ был отозван разработчиком";
                    break;

                case EResult.Timeout:
                    status = "timeout";
                    message = "Превышено время ожидания ответа от Steam";
                    break;

                default:
                    status = "error";
                    message = $"Неизвестная ошибка: {callback.Result} / {callback.PurchaseResultDetail}";
                    break;
            }

            Console.WriteLine($"[PURCHASE] Статус: {status}");
            Console.WriteLine($"[PURCHASE] Сообщение: {message}");

            _validationResult.Status = status;
            _validationResult.Message = message;
            _tcs?.TrySetResult(_validationResult);
            _isRunning = false;
        }
    }

    // ============================================================
    // Класс для автоматической привязки 2FA (AuthenticatorLinker)
    // ============================================================
    public class AuthenticatorLinker
    {
        private SteamAuth.UserLogin _userLogin = null!;
        private SteamAuth.AuthenticatorLinker _linker = null!;
        private SteamAuth.SteamGuardAccount _linkedAccount = null!;

        public async Task<bool> LinkNewAuthenticator(string username, string password)
        {
            Console.WriteLine("[2FA] Начинаем процесс привязки аутентификатора...");

            // 1. Вход в аккаунт
            _userLogin = new SteamAuth.UserLogin(username, password);
            var loginResult = await _userLogin.DoLoginAsync();

            while (loginResult != LoginResult.LoginOkay)
            {
                switch (loginResult)
                {
                    case LoginResult.Need2FA:
                        Console.WriteLine("[2FA] Требуется код двухфакторной аутентификации");
                        Console.Write("Введите код: ");
                        _userLogin.TwoFactorCode = Console.ReadLine()?.Trim();
                        break;

                    case LoginResult.NeedEmail:
                        Console.WriteLine("[2FA] Требуется код подтверждения из email");
                        Console.Write("Введите код: ");
                        _userLogin.EmailCode = Console.ReadLine()?.Trim();
                        break;

                    case LoginResult.NeedCaptcha:
                        var captchaUrl = _userLogin.GetCaptchaUrl();
                        Console.WriteLine($"[2FA] Требуется капча: {captchaUrl}");
                        Console.Write("Введите текст с картинки: ");
                        _userLogin.CaptchaText = Console.ReadLine()?.Trim();
                        break;

                    default:
                        Console.WriteLine($"[2FA] Ошибка входа: {loginResult}");
                        return false;
                }

                loginResult = await _userLogin.DoLoginAsync();
            }

            Console.WriteLine("[2FA] Вход выполнен успешно");

            // 2. Создаём линкер с полученной сессией
            _linker = new SteamAuth.AuthenticatorLinker(_userLogin.Session);

            // 3. Запрашиваем добавление аутентификатора
            Console.WriteLine("[2FA] Запрашиваем добавление аутентификатора...");
            var linkResult = await _linker.AddAuthenticatorAsync();

            if (linkResult == LinkResult.MustProvidePhoneNumber)
            {
                Console.Write("[2FA] Введите номер телефона (с кодом страны, например +79123456789): ");
                _linker.PhoneNumber = Console.ReadLine()?.Trim();
                linkResult = await _linker.AddAuthenticatorAsync();
            }

            if (linkResult != LinkResult.AwaitingFinalization)
            {
                Console.WriteLine($"[2FA] Ошибка при добавлении: {linkResult}");
                return false;
            }

            // 4. Сохраняем данные ДО финализации! [citation:2][citation:5]
            _linkedAccount = _linker.LinkedAccount;
            SaveSecrets(_linkedAccount);
            Console.WriteLine("[2FA] Данные сохранены в steamguard.json (НЕ удаляйте этот файл!)");

            // 5. Ждём SMS и финализируем
            Console.Write("[2FA] Введите код из SMS: ");
            var smsCode = Console.ReadLine()?.Trim();

            var finalizeResult = await _linker.FinalizeAddAuthenticatorAsync(smsCode);

            if (finalizeResult == FinalizeResult.Success)
            {
                Console.WriteLine("[2FA] ✅ Аутентификатор успешно привязан!");
                // Обновляем сохранённые данные (на всякий случай)
                SaveSecrets(_linkedAccount);
                return true;
            }
            else
            {
                Console.WriteLine($"[2FA] ❌ Ошибка финализации: {finalizeResult}");
                return false;
            }
        }

        private void SaveSecrets(SteamAuth.SteamGuardAccount account)
        {
            var secrets = new
            {
                shared_secret = account.SharedSecret,
                identity_secret = account.IdentitySecret,
                secret_1 = account.Secret1,
                serial_number = account.SerialNumber,
                revocation_code = account.RevocationCode,
                uri = account.Uri,
                account_name = account.AccountName,
                token_gid = account.TokenGID
            };

            var json = JsonSerializer.Serialize(secrets, new JsonSerializerOptions { WriteIndented = true });
            File.WriteAllText("steamguard.json", json);
        }
    }

    // ============================================================
    // Класс для генерации кодов 2FA (SteamGuardGenerator)
    // ============================================================
    public class SteamGuardGenerator
    {
        private readonly byte[] _sharedSecret;

        public SteamGuardGenerator(string sharedSecretBase64)
        {
            _sharedSecret = Convert.FromBase64String(sharedSecretBase64);
        }

        public string GenerateCode()
        {
            return GenerateCodeForTimestamp(DateTimeOffset.UtcNow.ToUnixTimeSeconds());
        }

        public string GenerateCodeForTimestamp(long timestamp)
        {
            long timeInterval = timestamp / 30L;

            byte[] timeBytes = BitConverter.GetBytes(timeInterval);
            if (BitConverter.IsLittleEndian)
                Array.Reverse(timeBytes);

            using (var hmac = new System.Security.Cryptography.HMACSHA1(_sharedSecret))
            {
                byte[] hmacResult = hmac.ComputeHash(timeBytes);

                int offset = hmacResult[hmacResult.Length - 1] & 0x0F;
                int code = (hmacResult[offset] & 0x7F) << 24 |
                           (hmacResult[offset + 1] & 0xFF) << 16 |
                           (hmacResult[offset + 2] & 0xFF) << 8 |
                           (hmacResult[offset + 3] & 0xFF);

                code = code % 100000;
                return code.ToString("D5");
            }
        }
    }
}