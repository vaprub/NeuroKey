# build.py
import PyInstaller.__main__
import os
import shutil
import sys
import site
import glob  # <-- добавить

def check_requirements():
    # ... (без изменений) ...
    print("🔍 Проверка окружения...")
    print(f"🐍 Python: {sys.version}")
    try:
        import PyInstaller
        print(f"✅ PyInstaller: {PyInstaller.__version__}")
    except:
        print("❌ PyInstaller не установлен! Установите: pip install pyinstaller")
        return False
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
    print("\n🧹 Очистка старых сборок...")
    for folder in ['dist', 'build', '__pycache__']:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"   Удалено: {folder}")
    for spec in glob.glob('*.spec'):  # <-- исправлено
        os.remove(spec)
        print(f"   Удалено: {spec}")

def create_icon():
    # ... (без изменений) ...
    icon_path = 'icon.ico'
    if not os.path.exists(icon_path):
        print("\n🎨 Иконка не найдена, создаём заглушку...")
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new('RGBA', (256, 256), color=(0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([20, 20, 236, 236], fill=(255, 200, 0))
            try:
                font = ImageFont.truetype("arial.ttf", 150)
            except:
                font = ImageFont.load_default()
            draw.text((70, 70), "🎮", fill=(0, 0, 0), font=font)
            img.save(icon_path, format='ICO', sizes=[(256, 256)])
            print(f"✅ Иконка создана: {icon_path}")
        except Exception as e:
            print(f"⚠️ Не удалось создать иконку: {e}")
            icon_path = None
    return icon_path

def build_exe():
    # ... (без изменений) ...
    print("\n🚀 НАЧАЛО СБОРКИ EXE")
    print("=" * 50)
    if not check_requirements():
        input("\n❌ Нажмите Enter для выхода...")
        return
    clean_old_builds()
    icon_path = create_icon()
    print("\n📦 Подготовка параметров сборки...")
    params = [
        'main.py',
        '--name=GiveawayScanner',
        '--windowed',
        '--onefile',
        '--clean',
        '--noconfirm',
        '--log-level=INFO',
    ]
    if icon_path and os.path.exists(icon_path):
        params.append(f'--icon={icon_path}')
    hidden_imports = [
        'PyQt5.sip', 'torch', 'transformers', 'sentence_transformers',
        'bs4', 'lxml', 'sqlite3', 'queue', 'threading', 'json', 'logging', 'datetime'
    ]
    for imp in hidden_imports:
        params.append(f'--hidden-import={imp}')
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
        PyInstaller.__main__.run(params)
        print("\n" + "=" * 50)
        print("✅ СБОРКА ЗАВЕРШЕНА УСПЕШНО!")
        print("=" * 50)
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
    if sys.platform == 'win32':
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
    build_exe()