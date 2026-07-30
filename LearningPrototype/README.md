# VladStone Learning Prototype

Локальный вход в курс: открой эту папку, выполни `npm install` один раз, затем
`npm run study` (или привычное `npm run dev`). Сайт продолжает с точки из
`docs/learning/START.md`.

Прогресс одновременно хранится в браузерном `localStorage` и, когда сайт
запущен через `npm run study`, в `data/learning-progress.json`. Второй файл
нужен AI-агенту в этом же workspace: он может прочитать реальные ответы,
уверенность, подсказки и темы для повтора, не требуя пересказа от ученика.

Исходники глав и текущая Anki-колода не копируются вручную: dev-сервер читает
`../docs/learning/course` и `../docs/learning/anki/vladstone-gl1-2.txt`.
Поэтому курс остаётся единым источником правды.

`data/learning-progress.json` намеренно не попадает в Git: это личный учебный
журнал, а не код проекта.
