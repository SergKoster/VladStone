import type { LearningCard } from "./types";

export const courseAnchor = {
  current: "Глава 2 — материал пройден, зачёт без AI ещё впереди",
  next: "Повтор → dataclass vs Pydantic → старт главы 3",
  source: "docs/learning/START.md",
};

export const fixedCards: LearningCard[] = [
  {
    id: "anchor-resource",
    prompt:
      "Не открывая исходник, набросай resource(log) через @contextmanager. В каком месте должен быть yield и почему finally нельзя убрать?",
    expectedAnswer:
      "До yield захватываем ресурс, после него в finally освобождаем. Когда код внутри with выбрасывает исключение, оно возвращается в точку yield; finally выполняется при любом выходе и сохраняет инвариант очистки.",
    hint: "Сначала вспомни три события: вход в with → тело with → выход с ошибкой или без неё.",
    tag: "gl2",
    source: "docs/learning/START.md — домашка после главы 2",
  },
  {
    id: "anchor-dataclass-pydantic",
    prompt:
      "Ты описываешь входящее тело HTTP-запроса, а затем — внутреннюю неизменяемую конфигурацию доменного правила. Где выберешь Pydantic, а где dataclass? Объясни не названием библиотеки, а границей ответственности.",
    expectedAnswer:
      "Pydantic стоит на недоверенной границе HTTP: валидирует и преобразует внешние данные. dataclass подходит для простой внутренней модели, когда правила валидации уже обеспечены на границе и нужна прозрачная структура данных. Это не жёсткий запрет: выбор зависит от того, нужна ли runtime-валидация и сериализация.",
    hint: "Подумай, какие данные контролирует сервер, а какие пришли извне.",
    tag: "gl2",
    source: "docs/learning/START.md — хвост главы 2",
  },
  {
    id: "anchor-typing-start",
    prompt:
      "Глава 3 начинается с моделирования контрактов. Что именно полезный тип должен сообщить следующему читателю кода, кроме того что значение «какого-то класса»? Назови один пример из backend-кода.",
    expectedAnswer:
      "Тип выражает контракт: допустимые данные, отсутствие значения, владение и ожидаемый результат операции. Например, Optional[User] заставляет обработать случай «пользователь не найден», а Mapping[str, str] сообщает, что функцию не должна полагаться на мутацию словаря.",
    hint: "Подумай о случае, который можно пропустить, если написать просто object или Any.",
    tag: "gl3",
    source: "docs/learning/course/03-typing-and-modeling.md",
  },
];

export function mergeCards(cards: Omit<LearningCard, "source">[]): LearningCard[] {
  return [
    ...fixedCards,
    ...cards.map((card) => ({ ...card, source: "docs/learning/anki/vladstone-gl1-2.txt" })),
  ];
}
