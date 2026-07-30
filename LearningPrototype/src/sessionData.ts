import type { LearningCard } from "./types";

export const courseAnchor = {
  current: "Глава 2 — материал пройден, зачёт без AI ещё впереди",
  next: "Повтор → dataclass vs Pydantic → старт главы 3",
  source: "docs/learning/START.md",
};

export const courseRoute = ["01", "02", "03", "05", "08", "09", "04", "06", "07", "12", "16", "10", "11", "13", "14", "15", "17"];

export const fixedCards: LearningCard[] = [
  {
    id: "anchor-resource",
    prompt:
      "Не открывая исходник, набросай resource(log) через @contextmanager. В каком месте должен быть yield и почему finally нельзя убрать?",
    expectedAnswer:
      "До yield захватываем ресурс, после него в finally освобождаем. Когда код внутри with выбрасывает исключение, оно возвращается в точку yield; finally выполняется при любом выходе и сохраняет инвариант очистки.",
    hint: "Сначала вспомни три события: вход в with → тело with → выход с ошибкой или без неё.",
    tag: "gl2",
    chapterId: "02",
    source: "docs/learning/START.md — домашка после главы 2",
    kind: "bridge",
  },
  {
    id: "anchor-dataclass-pydantic",
    prompt:
      "Ты описываешь входящее тело HTTP-запроса, а затем — внутреннюю неизменяемую конфигурацию доменного правила. Где выберешь Pydantic, а где dataclass? Объясни не названием библиотеки, а границей ответственности.",
    expectedAnswer:
      "Pydantic стоит на недоверенной границе HTTP: валидирует и преобразует внешние данные. dataclass подходит для простой внутренней модели, когда правила валидации уже обеспечены на границе и нужна прозрачная структура данных. Это не жёсткий запрет: выбор зависит от того, нужна ли runtime-валидация и сериализация.",
    hint: "Подумай, какие данные контролирует сервер, а какие пришли извне.",
    tag: "gl2",
    chapterId: "02",
    source: "docs/learning/START.md — хвост главы 2",
    kind: "bridge",
  },
];

export function mergeCards(
  chapters: { sourcePath: string; cards: Omit<LearningCard, "source" | "kind">[] }[],
  ankiCards: Omit<LearningCard, "source" | "kind">[],
): LearningCard[] {
  return [
    ...fixedCards,
    ...chapters.flatMap((chapter) => chapter.cards.map((card) => ({
      ...card,
      source: chapter.sourcePath,
      kind: "course" as const,
    }))),
    ...ankiCards.map((card) => ({
      ...card,
      source: "docs/learning/anki/vladstone-gl1-2.txt",
      kind: "anki" as const,
    })),
  ];
}
