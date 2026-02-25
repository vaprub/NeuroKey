# models.py
import os
import sys
import logging
import ctypes
import numpy as np
import re
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

logger = logging.getLogger(__name__)

# === ЖЁСТКИЙ ФИКС DLL (ДО ВСЕХ ИМПОРТОВ) ===
def force_fix_torch_dll():
    # ... (без изменений, оставляем как было) ...
    try:
        site_packages = Path(sys.prefix) / "Lib" / "site-packages"
        torch_lib = site_packages / "torch" / "lib"
        c10_path = torch_lib / "c10.dll"
        if not c10_path.exists():
            logger.warning(f"⚠️ c10.dll not found at {c10_path}")
            return False
        os.environ['PATH'] = str(torch_lib.absolute()) + os.pathsep + os.environ.get('PATH', '')
        try:
            ctypes.CDLL(str(c10_path.absolute()))
            logger.info(f"✅ c10.dll pre-loaded from {c10_path}")
        except Exception as e:
            logger.error(f"❌ Failed to pre-load c10.dll: {e}")
            return False
        try:
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel32.AddDllDirectory.argtypes = [ctypes.c_wchar_p]
            kernel32.AddDllDirectory.restype = ctypes.c_void_p
            kernel32.AddDllDirectory(str(torch_lib.absolute()))
            logger.info("✅ DLL directory added via AddDllDirectory")
        except Exception as e:
            logger.warning(f"⚠️ AddDllDirectory failed: {e}")
        torch_cpu_path = torch_lib / "torch_cpu.dll"
        if torch_cpu_path.exists():
            try:
                ctypes.CDLL(str(torch_cpu_path.absolute()))
                logger.info("✅ torch_cpu.dll pre-loaded")
            except Exception as e:
                logger.warning(f"⚠️ torch_cpu.dll pre-load failed: {e}")
        return True
    except Exception as e:
        logger.error(f"❌ DLL fix failed: {e}")
        return False

fix_result = force_fix_torch_dll()
logger.info(f"DLL fix result: {'✅ success' if fix_result else '❌ failed'}")

# === ИМПОРТ TORCH ===
TORCH_AVAILABLE = False
try:
    import torch
    TORCH_AVAILABLE = True
    logger.info(f"✅ Torch {torch.__version__} loaded successfully")
except Exception as e:
    logger.error(f"❌ Failed to load torch: {e}")
    logger.info("⚠️ Continuing in simplified mode without neural networks")

# === ИМПОРТ TRANSFORMERS ===
TRANSFORMERS_AVAILABLE = False
if TORCH_AVAILABLE:
    try:
        from sentence_transformers import SentenceTransformer
        from transformers import pipeline
        TRANSFORMERS_AVAILABLE = True
        logger.info("✅ Transformers loaded successfully")
    except ImportError as e:
        logger.error(f"❌ Failed to load transformers: {e}")
        logger.info("⚠️ Run: pip install sentence-transformers transformers")
else:
    logger.info("⚠️ Transformers not loaded (torch unavailable)")

# === ОПРЕДЕЛЕНИЕ ПЛАТФОРМЫ ПО КЛЮЧУ ===
PLATFORM_PATTERNS = [
    (r'^[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}$', 'Steam'),
    (r'^[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}$', 'Epic/Xbox/Ubisoft'),
    (r'^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$', 'EA/Origin'),
    (r'^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$', 'PlayStation'),
    (r'^[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}$', 'Battle.net'),
    (r'^[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}$', 'Microsoft/Rockstar'),
    (r'^B0[A-Z0-9]{14}$', 'Nintendo'),
    (r'^[A-Z0-9]{20}$', 'GOG (возможно)'),
    (r'^[A-Z0-9]{16,}$', 'Itch.io / другие'),
]

def guess_platform(key: str) -> str:
    for pattern, platform in PLATFORM_PATTERNS:
        if re.match(pattern, key):
            return platform
    return 'Unknown'

def guess_game_name(title: str, description: str, key: str) -> str:
    common_words = ['free', 'key', 'steam', 'gog', 'giveaway', 'get', 'now', 'limited',
                    'time', 'offer', 'claim', 'code', 'download', 'game', 'for', 'and', 'the']
    words = title.split()
    filtered = [w for w in words if w.lower() not in common_words and len(w) > 2]
    if filtered:
        return ' '.join(filtered[:3])
    return 'Unknown'

class ModelManager:
    def __init__(self, model_dir: str = "models", use_gpu: bool = True):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(exist_ok=True)
        self.device = None
        self.use_gpu = use_gpu and TORCH_AVAILABLE
        self.cuda_error_occurred = False  # флаг, что была ошибка CUDA

        if TORCH_AVAILABLE and self.use_gpu:
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            logger.info(f"Using device: {self.device}")

        self.encoder = None
        self.classifier = None
        self.ner_pipeline = None
        self.giveaway_keywords = [
            'free', 'giveaway', 'key', 'steam', 'gog', 'epic',
            'claim', 'get free', 'limited', 'code', 'redeem',
            'free game', 'free key', 'giveaway key', 'game giveaway',
            'free steam', 'free gog', 'free epic', 'game code',
            'бесплатно', 'раздача', 'ключ', 'стим', 'получить',
            'бесплатный ключ', 'раздача ключей', 'стим ключ',
            'freebie', 'gift', 'present', 'bonus',
        ]
        self.keyword_weights = {
            'free': 1.5, 'giveaway': 2.0, 'key': 1.5, 'code': 1.5,
            'бесплатно': 1.5, 'раздача': 2.0, 'ключ': 1.5,
            'steam': 1.2, 'gog': 1.2,
        }
        logger.info(f"✅ ModelManager initialized (mode: {'full' if TORCH_AVAILABLE and TRANSFORMERS_AVAILABLE else 'simplified'})")
        if TORCH_AVAILABLE and TRANSFORMERS_AVAILABLE:
            self._load_models()

    def _load_models(self):
        if not TORCH_AVAILABLE or not TRANSFORMERS_AVAILABLE:
            return
        try:
            logger.info("Loading SentenceTransformer for search...")
            search_model_path = self.model_dir / "giveaway_search_model"
            if search_model_path.exists():
                self.encoder = SentenceTransformer(
                    str(search_model_path),
                    device='cuda' if self.use_gpu and torch.cuda.is_available() and not self.cuda_error_occurred else 'cpu'
                )
                logger.info("✅ Fine-tuned search model loaded")
            else:
                self.encoder = SentenceTransformer(
                    'all-MiniLM-L6-v2',
                    device='cuda' if self.use_gpu and torch.cuda.is_available() and not self.cuda_error_occurred else 'cpu'
                )
                logger.info("✅ Base SentenceTransformer loaded")

            logger.info("Loading classifier...")
            device_id = 0 if self.use_gpu and torch.cuda.is_available() and not self.cuda_error_occurred else -1
            self.classifier = pipeline(
                "text-classification",
                model="cross-encoder/stsb-distilroberta-base",
                device=device_id
            )
            logger.info("✅ Classifier loaded")

            logger.info("Loading NER model...")
            ner_model_path = self.model_dir / "key_extraction_ner"
            if ner_model_path.exists():
                self.ner_pipeline = pipeline(
                    "ner",
                    model=str(ner_model_path),
                    tokenizer=str(ner_model_path),
                    device=device_id
                )
                logger.info("✅ Fine-tuned NER model loaded")
            else:
                self.ner_pipeline = pipeline(
                    "ner",
                    model="dslim/bert-base-NER",
                    device=device_id
                )
                logger.info("✅ Base NER model loaded")
        except Exception as e:
            logger.error(f"❌ Error loading models: {e}")

    def _handle_cuda_error(self, e: Exception, component: str):
        """Обрабатывает CUDA-ошибку: переключает флаг и перезагружает модель на CPU."""
        if "CUDA" in str(e) or "cuda" in str(e):
            logger.error(f"CUDA error in {component}, switching to CPU: {e}")
            self.cuda_error_occurred = True
            # Перезагружаем все модели на CPU
            self._load_models()  # перезагрузит с device=-1
            return True
        return False

    def analyze_relevance(self, text: str) -> float:
        if not text:
            return 0.0

        text_lower = text.lower()
        total_weight = 0
        matched_weight = 0
        for keyword, weight in self.keyword_weights.items():
            total_weight += weight
            if keyword in text_lower:
                matched_weight += weight
        for keyword in self.giveaway_keywords:
            if keyword not in self.keyword_weights:
                total_weight += 1.0
                if keyword in text_lower:
                    matched_weight += 1.0
        if total_weight > 0:
            keyword_score = min(matched_weight / total_weight * 2, 0.95)
        else:
            keyword_score = 0.0
        strong_indicators = ['giveaway', 'раздача', 'free key', 'бесплатный ключ']
        for ind in strong_indicators:
            if ind in text_lower:
                keyword_score = min(keyword_score + 0.2, 0.95)

        if TORCH_AVAILABLE and self.classifier and not self.cuda_error_occurred:
            try:
                result = self.classifier(text[:512])[0]
                model_score = float(result['score'])
                if result['label'] == 'NEGATIVE':
                    model_score = 1 - model_score
                return 0.5 * keyword_score + 0.5 * model_score
            except RuntimeError as e:
                if self._handle_cuda_error(e, "classifier"):
                    # после перезагрузки пробуем снова (теперь на CPU)
                    try:
                        result = self.classifier(text[:512])[0]
                        model_score = float(result['score'])
                        if result['label'] == 'NEGATIVE':
                            model_score = 1 - model_score
                        return 0.5 * keyword_score + 0.5 * model_score
                    except Exception as e2:
                        logger.warning(f"Classifier failed even after CPU fallback: {e2}")
                        return keyword_score
            except Exception as e:
                logger.warning(f"Classifier failed: {e}")
                return keyword_score

        return keyword_score

    def extract_keys(self, text: str) -> list:
        keys = []

        if TORCH_AVAILABLE and self.ner_pipeline and not self.cuda_error_occurred:
            try:
                ner_results = self.ner_pipeline(text[:1000])
                for result in ner_results:
                    word = result['word'].replace('##', '')
                    if len(word) > 8 and word.isalnum() and word not in keys:
                        keys.append(word)
            except RuntimeError as e:
                if self._handle_cuda_error(e, "NER"):
                    # после перезагрузки пробуем снова (теперь на CPU)
                    try:
                        ner_results = self.ner_pipeline(text[:1000])
                        for result in ner_results:
                            word = result['word'].replace('##', '')
                            if len(word) > 8 and word.isalnum() and word not in keys:
                                keys.append(word)
                    except Exception as e2:
                        logger.warning(f"NER failed even after CPU fallback: {e2}")
            except Exception as e:
                logger.warning(f"NER failed: {e}")

        key_patterns = [
            r'[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}',
            r'[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}',
            r'[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}',
            r'[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}',
            r'[A-Z0-9]{6}-[A-Z0-9]{6}-[A-Z0-9]{6}',
            r'[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}',
            r'B0[A-Z0-9]{14}',
            r'[A-Z0-9]{20}',
            r'[A-Z0-9]{16,}',
        ]
        for pattern in key_patterns:
            found = re.findall(pattern, text)
            keys.extend(found)

        return list(set(keys))

    def is_giveaway(self, title: str, description: str = "") -> tuple:
        text = f"{title} {description}".strip()
        score = self.analyze_relevance(text)
        if TORCH_AVAILABLE and self.classifier and not self.cuda_error_occurred:
            threshold = 0.35
        else:
            threshold = 0.30
        return score > threshold, score

    def get_embedding(self, text: str) -> np.ndarray:
        if not TORCH_AVAILABLE or not self.encoder or self.cuda_error_occurred:
            return np.zeros(384)
        try:
            embedding = self.encoder.encode(text[:1000])
            return embedding
        except Exception as e:
            logger.error(f"Error getting embedding: {e}")
            return np.zeros(384)

    def get_model_info(self) -> dict:
        return {
            'torch_available': TORCH_AVAILABLE,
            'transformers_available': TRANSFORMERS_AVAILABLE,
            'device': str(self.device) if self.device else 'cpu',
            'encoder_loaded': self.encoder is not None,
            'classifier_loaded': self.classifier is not None,
            'ner_loaded': self.ner_pipeline is not None,
            'mode': 'full' if TORCH_AVAILABLE and TRANSFORMERS_AVAILABLE and self.encoder else 'simplified',
            'model_dir': str(self.model_dir),
            'keywords_count': len(self.giveaway_keywords)
        }

# === ТЕСТИРОВАНИЕ ===
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    print("\n" + "="*60)
    print("🔧 ТЕСТИРОВАНИЕ МОДЕЛИ")
    print("="*60)
    model = ModelManager()
    info = model.get_model_info()
    print("\n📊 ИНФОРМАЦИЯ О МОДЕЛИ:")
    for key, value in info.items():
        print(f"  {key}: {value}")
    test_texts = [
        "Free Steam key for awesome game! Limited time offer",
        "Check out this new gaming mouse for $50",
        "Giveaway: 1000 GOG keys for Cyberpunk 2077",
        "Today only: 50% off on all games",
        "Get your free game code here - first come first served",
        "New game release: Cyberpunk 2077 now available for $60",
        "Раздача бесплатных ключей Steam! Успей получить",
        "Steam Gift Card $20 - купить сейчас",
    ]
    print("\n🔍 ТЕСТ АНАЛИЗА РАЗДАЧ:")
    print("-"*60)
    for text in test_texts:
        is_give, conf = model.is_giveaway(text)
        keys = model.extract_keys(text)
        status = "✅ РАЗДАЧА" if is_give else "❌ НЕ РАЗДАЧА"
        print(f"\n📝 {text[:50]}...")
        print(f"   {status} (уверенность: {conf:.2%})")
        if keys:
            platforms = [guess_platform(k) for k in keys]
            print(f"   🔑 Найденные ключи: {', '.join(keys)}")
            print(f"   🎮 Платформы: {', '.join(platforms)}")
    print("\n" + "="*60)
    input("Нажми Enter для выхода...")