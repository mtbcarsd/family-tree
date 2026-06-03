"""
parse_trees.py — OCR-парсинг изображений генеалогического древа.

Конвертирует MPO-файлы (part1–part8) в текст через pytesseract,
сохраняет сырые результаты в output/ocr_partN.txt и output/raw_ocr.txt.
Результаты OCR требуют ручной проверки — качество зависит от
разрешения и чёткости изображений.
"""

import sys
import os
from pathlib import Path

# ── Проверка зависимостей ─────────────────────────────────────────────────────
try:
    import pytesseract
    from PIL import Image
    import cv2
    import numpy as np
except ImportError as e:
    print(f"[ОШИБКА] Не установлена библиотека: {e}")
    print("Активируйте виртуальное окружение и запустите:")
    print("  pip install pytesseract Pillow opencv-python")
    sys.exit(1)

BASE_DIR = Path(__file__).parent
IMAGES_DIR = BASE_DIR / "original_foto_tree_parts"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def check_tesseract() -> bool:
    """Проверяет, доступен ли Tesseract OCR."""
    try:
        pytesseract.get_tesseract_version()
        return True
    except pytesseract.TesseractNotFoundError:
        print("[ОШИБКА] Tesseract не установлен или не найден в PATH.")
        print("Установите командой:")
        print("  sudo apt-get install tesseract-ocr tesseract-ocr-rus")
        return False


def preprocess_image(pil_img: Image.Image) -> Image.Image:
    """
    Улучшает изображение для OCR:
    - конвертирует MPO → RGB → grayscale
    - увеличивает масштаб для лучшего распознавания
    - применяет адаптивный порог
    """
    rgb = pil_img.convert("RGB")
    arr = np.array(rgb)

    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

    # Масштабируем: мелкий текст лучше распознаётся при 300+ dpi
    h, w = gray.shape
    scale = 2.0 if max(h, w) < 4000 else 1.5
    resized = cv2.resize(gray, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_LANCZOS4)

    # Адаптивный порог — помогает при неравномерном освещении
    binary = cv2.adaptiveThreshold(
        resized, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,
        C=10,
    )

    # Лёгкое расширение для улучшения читаемости букв
    kernel = np.ones((1, 1), np.uint8)
    processed = cv2.dilate(binary, kernel, iterations=1)

    return Image.fromarray(processed)


def ocr_image(image_path: Path, lang: str = "rus+eng") -> str:
    """Открывает изображение, предобрабатывает и выполняет OCR."""
    try:
        img = Image.open(image_path)
        processed = preprocess_image(img)
        # --psm 6: равномерный блок текста; --oem 3: LSTM + legacy
        text = pytesseract.image_to_string(
            processed,
            lang=lang,
            config="--psm 6 --oem 3",
        )
        return text.strip()
    except Exception as e:
        return f"[ОШИБКА при обработке {image_path.name}: {e}]"


def save_raw_text(filename: str, text: str) -> None:
    path = OUTPUT_DIR / filename
    path.write_text(text, encoding="utf-8")


def main() -> None:
    print("=" * 60)
    print("  OCR-парсинг генеалогического древа")
    print("=" * 60)

    if not check_tesseract():
        sys.exit(1)

    parts = sorted(IMAGES_DIR.glob("part*.jpeg"))
    if not parts:
        print(f"[ОШИБКА] Файлы part*.jpeg не найдены в {IMAGES_DIR}")
        sys.exit(1)

    print(f"\nНайдено файлов: {len(parts)}\n")

    all_text_parts: list[str] = []

    for img_path in parts:
        print(f"  Обрабатываю: {img_path.name} ...", end=" ", flush=True)
        text = ocr_image(img_path)

        out_file = f"ocr_{img_path.stem}.txt"
        save_raw_text(out_file, text)

        all_text_parts.append(f"{'='*40}\n=== {img_path.name} ===\n{'='*40}\n{text}\n")
        print(f"сохранено → output/{out_file}")

    combined = "\n".join(all_text_parts)
    save_raw_text("raw_ocr.txt", combined)

    print(f"\n[OK] Результаты OCR сохранены в output/")
    print(f"     raw_ocr.txt — объединённый файл")
    print(f"     ocr_partN.txt — по каждому листу отдельно\n")
    print("ВНИМАНИЕ: OCR на рукописных/печатных схемах даёт частичный")
    print("результат. Проверьте output/family_data.csv и исправьте имена.")


if __name__ == "__main__":
    main()
