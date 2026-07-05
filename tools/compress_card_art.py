"""Пайплайн артов карт: сжимает рабочие копии в VladStoneWeb/src/assets/cards.

Использование (из корня репо):
    VladStoneAPI\\.venv\\Scripts\\python tools\\compress_card_art.py

Что делает: каждый png/jpg/jpeg в assets/cards уменьшается до MAX_SIDE px по
большей стороне и сохраняется как <card_id>.webp (с прозрачностью, если была);
исходная рабочая копия удаляется. Оригиналы в res/Cards не трогаются.
Фронт подхватывает .webp автоматически (glob в cardArt.tsx). Запуск повторно
безопасен: готовые .webp пропускаются, если рядом нет свежего png/jpg.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

CARDS_DIR = Path(__file__).resolve().parents[1] / "VladStoneWeb" / "src" / "assets" / "cards"
MAX_SIDE = 640
WEBP_QUALITY = 82


def compress_one(source: Path) -> tuple[int, int]:
    image = Image.open(source)
    image.load()
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)

    target = source.with_suffix(".webp")
    image.save(target, format="WEBP", quality=WEBP_QUALITY, method=6)

    before = source.stat().st_size
    after = target.stat().st_size
    source.unlink()
    return before, after


def main() -> None:
    sources = [
        path
        for path in sorted(CARDS_DIR.iterdir())
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"} and path.stat().st_size > 0
    ]
    if not sources:
        print(f"Нечего сжимать: в {CARDS_DIR} нет png/jpg рабочих копий.")
        return

    total_before = 0
    total_after = 0
    for source in sources:
        before, after = compress_one(source)
        total_before += before
        total_after += after
        print(f"{source.name:24} {before / 1024:8.0f} KB -> {after / 1024:6.0f} KB (.webp)")
    saved = 100 * (1 - total_after / total_before)
    total_line = f"{total_before / 1024:8.0f} KB -> {total_after / 1024:6.0f} KB (-{saved:.0f}%)"
    print(f"{'TOTAL':24} {total_line}")


if __name__ == "__main__":
    main()
