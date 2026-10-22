"""Конфигурация для ML-пайплайна.

TODO: Настроить пути и параметры под конкретный датасет.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DATA_RAW = BASE_DIR / "data" / "raw"
DATA_PROCESSED = BASE_DIR / "data" / "processed"
DATA_TRAINING = BASE_DIR / "data" / "training"
MODELS_DIR = BASE_DIR / "models"

RANDOM_SEED = 42
TEST_SIZE = 0.2
TARGET_COLUMN = "target"
