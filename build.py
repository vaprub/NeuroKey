# build.py
import PyInstaller.__main__
import os
import shutil
import sys
import site

def check_requirements():
    """Проверяет, всё ли готово к сборке"""
    print("🔍 Проверка окружения...")
    
    # Проверяем Python
    print(f"🐍 Python: {sys.version}")
    
    # Проверяем наличие PyInstaller
    try:
        import PyInstaller
        print(f"✅ PyInstaller: {PyInstaller.__version__}")
    except:
        print("❌ PyInstaller не установлен! Установите: pip install pyinstaller")
        return False
    
    # Проверяем наличие всех модулей
    required_modules = ['PyQt5', 'torch', 'transformers', 'sentence_transformers', 'bs4']
    for module in required_modules:
        try:
            __import__(module)
            print(f"✅ {module} найден")
        except ImportError:
            print(f"❌ {module} не установлен! Установите: pip install {module}")
            return False
    
    return True

def clean_old_builds():
    """Очищает старые сборки"""
    print("\n🧹 Очистка старых сборок...")
    
    for folder in ['dist', 'build', '__pycache__']:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"   Удалено: {folder}")
    
    for file in ['*.spec']:
        for spec in glob.glob(file):
            os.remove(spec)
            print(f"   Удалено: {spec}")

def create_icon():
    """Создаёт иконку, если её нет"""
    icon_path = 'icon.ico'
    
    if not os.path.exists(icon_path):
        print("\n🎨 Иконка не найдена, создаём заглушку...")
        try:
            from PIL import Image, ImageDraw
            
            # Создаём изображение 256x256
            img = Image.new('RGBA', (256, 256), color=(0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            
            # Рисуем круг
            draw.ellipse([20, 20, 236, 236], fill=(255, 200, 0))
            
            # Рисуем текст
            try:
                font = ImageFont.truetype("arial.ttf", 150)
            except:
                font = ImageFont.load_default()
            
            draw.text((70, 70), "🎮", fill=(0, 0, 0), font=font)
            
            # Сохраняем как ICO
            img.save(icon_path, format='ICO', sizes=[(256, 256)])
            print(f"✅ Иконка создана: {icon_path}")
        except Exception as e:
            print(f"⚠️ Не удалось создать иконку: {e}")
            icon_path = None
    
    return icon_path

def build_exe():
    """Собирает EXE файл"""
    print("\n🚀 НАЧАЛО СБОРКИ EXE")
    print("=" * 50)
    
    # Проверяем требования
    if not check_requirements():
        input("\n❌ Нажмите Enter для выхода...")
        return
    
    # Очищаем старые сборки
    clean_old_builds()
    
    # Создаём иконку
    icon_path = create_icon()
    
    # Подготавливаем параметры
    print("\n📦 Подготовка параметров сборки...")
    
    # Основные параметры
    params = [
        'main.py',                    # главный файл
        '--name=GiveawayScanner',     # имя EXE
        '--windowed',                  # без консоли
        '--onefile',                   # один файл
        '--clean',                      # очистка кеша
        '--noconfirm',                  # не спрашивать подтверждение
        '--log-level=INFO',             # уровень логирования
    ]
    
    # Добавляем иконку, если есть
    if icon_path and os.path.exists(icon_path):
        params.append(f'--icon={icon_path}')
    
    # Добавляем скрытые импорты (очень важно для PyTorch и трансформеров!)
    hidden_imports = [
        'PyQt5.sip',
        'torch',
        'transformers',
        'sentence_transformers',
        'bs4',
        'lxml',
        'sqlite3',
        'queue',
        'threading',
        'json',
        'logging',
        'datetime'
    ]
    
    for imp in hidden_imports:
        params.append(f'--hidden-import={imp}')
    
    # Собираем все данные
    params.append('--collect-all=torch')
    params.append('--collect-all=transformers')
    params.append('--collect-all=sentence_transformers')
    params.append('--collect-all=PyQt5')
    
    print(f"\n📋 Параметры сборки:")
    for param in params:
        print(f"   {param}")
    
    print("\n⚙️ Запуск PyInstaller...")
    print("-" * 50)
    
    try:
        # Запускаем сборку
        PyInstaller.__main__.run(params)
        
        print("\n" + "=" * 50)
        print("✅ СБОРКА ЗАВЕРШЕНА УСПЕШНО!")
        print("=" * 50)
        
        # Показываем результат
        exe_path = os.path.join('dist', 'GiveawayScanner.exe')
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"\n📁 Файл создан: {exe_path}")
            print(f"📊 Размер: {size_mb:.1f} МБ")
            
            print("\n🚀 Чтобы запустить:")
            print(f"   1. Перейдите в папку dist")
            print(f"   2. Запустите GiveawayScanner.exe")
            print(f"\n📝 Важно: при первом запуске:")
            print(f"   - Будет создана папка models/ для скачивания моделей")
            print(f"   - Потребуется интернет для загрузки (~500 МБ)")
            print(f"   - Модели скачаются один раз")
        else:
            print(f"\n❌ ОШИБКА: EXE файл не найден!")
    
    except Exception as e:
        print(f"\n❌ ОШИБКА СБОРКИ: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n👋 Нажмите Enter для выхода...")
    input()

if __name__ == "__main__":
    # Устанавливаем кодировку для Windows
    if sys.platform == 'win32':
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
    
    build_exe()