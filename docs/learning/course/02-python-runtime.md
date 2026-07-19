# Глава 2. Python: модель выполнения

## Результат

Профессионалу мало помнить синтаксис. Нужно видеть объекты, ссылки, области
видимости, стек вызовов, итерацию и исключения так, как их видит runtime.

После главы ты сможешь:

- предсказывать мутацию и aliasing без запуска;
- отличать iterable, iterator и generator;
- объяснять замыкание, декоратор и контекстный менеджер;
- проектировать границы исключений;
- читать современный Python 3.12 в `VladStoneAPI`.

## Входной прогноз

```python
def reserve(hand: list[str], card: str, selected: list[str] = []) -> list[str]:
    if card in hand:
        selected.append(card)
    return selected

a = reserve(["mage"], "mage")
b = reserve(["tank"], "tank")
print(a, b, a is b)
```

Запиши точный вывод и причину. Затем ответь: изменение `selected=[]` на
`selected=None` исправляет какой инвариант?

## 1. Имена указывают на объекты

В Python переменная — не коробка с копией значения, а имя, связанное с
объектом. Присваивание обычно меняет связь, мутация — сам объект:

```python
cards = ["mage"]
planned = cards
planned.append("tank")       # один список виден через два имени
planned = [*planned, "heal"] # новое имя теперь указывает на новый список
```

Mental model:

```text
cards ─┐
       ├──> list#1 ["mage", "tank"]
planned┘

после переприсваивания:
cards ─────> list#1
planned ───> list#2
```

Отсюда mutable-default bug: объект аргумента по умолчанию создаётся один раз
при выполнении `def`, а не на каждый вызов. Надёжная форма:

```python
def reserve(
    hand: list[str],
    card: str,
    selected: list[str] | None = None,
) -> list[str]:
    result = [] if selected is None else selected
    if card in hand:
        result.append(card)
    return result
```

Это не означает «никогда не мутируй». Важно явно решить, кому принадлежит
объект и разрешена ли наблюдаемая мутация.

## 2. Вызов и область видимости

При вызове создаётся frame: локальные имена, позиция выполнения и ссылка на
внешнее окружение. LEGB-поиск идёт Local → Enclosing → Global → Builtins.

```python
def make_counter():
    count = 0

    def next_value():
        nonlocal count
        count += 1
        return count

    return next_value
```

`next_value` сохраняет связь с enclosing frame — это closure. `nonlocal`
говорит не создавать новое локальное имя. Декораторы FastAPI используют ту же
способность функций быть объектами:

```python
@router.get("/catalog")
def get_card_catalog():
    ...
```

Синтаксически это близко к:

```python
get_card_catalog = router.get("/catalog")(get_card_catalog)
```

Декоратор регистрирует функцию в роутере и возвращает вызываемый объект.

## 3. Итерация и ленивость

**Iterable** умеет создать iterator через `iter(x)`. **Iterator** хранит
позицию и отдаёт следующий элемент через `next(x)`, пока не бросит
`StopIteration`. **Generator** — удобный iterator, чей frame приостанавливается
на `yield`.

```python
def active_ids(records):
    for record in records:
        if record.status == "active":
            yield record.id
```

Плюсы ленивости: не строим весь результат заранее, можно обрабатывать поток.
Цена: работа и исключения происходят при потреблении, generator одноразовый,
а удерживаемый frame может удерживать ресурсы.

В `app/db/session.py`:

```python
def get_db() -> Generator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

FastAPI потребляет dependency-generator как lifecycle: всё до `yield` —
acquire, значение после `yield` — cleanup. Это тот же общий паттерн
контекстного менеджера: ресурс должен закрыться и при успехе, и при
исключении.

## 4. Исключения — часть контракта

Исключение разматывает стек до подходящего `except`; `finally` выполняется при
обычном выходе и при ошибке.

Плохая граница:

```python
try:
    resolve_everything()
except Exception:
    pass
```

Она теряет сигнал и продолжает работу с неизвестным состоянием. В
`combat_timer_worker.py` широкий `except Exception` оправдан на внешней
границе бесконечного воркера: ошибка логируется, а следующий тик должен жить.
Внутри batch есть ещё одна граница на матч: rollback одного матча не отменяет
остальные. `CancelledError` пробрасывается отдельно, потому что отмена —
управляющий сигнал shutdown, не обычный дефект матча.

Правило: лови исключение там, где можешь выполнить осмысленное восстановление,
перевести его в контракт слоя или добавить контекст. Не лови только ради
тишины.

## 5. Модели данных: dataclass и Pydantic

`@dataclass` генерирует обычный Python boilerplate для уже доверенных данных.
Pydantic валидирует и преобразует данные на границах, строит schema и умеет
JSON. В проекте есть оба:

- `ResolvedPlanningMatch` — внутренний результат, `@dataclass(frozen=True)`;
- `BattleStateV4` и request-модели — данные сериализуются и валидируются,
  поэтому Pydantic.

Не выбирай Pydantic «потому что современно»: за runtime-валидацию платим
временем и зависимостью. В горячем внутреннем цикле простой тип может быть
лучше; на недоверенной границе проверка ценнее.

## Разобранный пример: устойчивый batch

Упрощённая форма `resolve_expired_planning_matches`:

```python
results = []
for record in records:
    try:
        result = resolve_one(record)
        db.commit()
    except StaleDataError:
        db.rollback()
        continue
    except Exception:
        db.rollback()
        logger.exception("failed")
        continue
    results.append(result)
```

Трассировка для трёх записей:

1. A разрешилась: commit, результат добавлен.
2. B проиграла конкуренту: rollback очищает session, цикл продолжается.
3. C имеет баг: rollback + traceback; batch не теряет A.

Заметь порядок `append`: только после успешного commit. Если добавить результат
раньше, наружу уйдёт событие, которого нет в БД.

## PRIMM-лаборатория

### Predict

Что изменится, если `results.append(result)` перенести перед `db.commit()`?
Назови минимум два режима отказа.

### Run

Прогони целевой тест:

```powershell
.\.venv\Scripts\python -m pytest tests/test_combat_resolve_race.py -q
```

из `VladStoneAPI/`. До запуска запиши ожидаемый исход.

### Investigate

Открой:

- `app/services/combat_turn_timers.py`;
- `app/services/combat_timer_worker.py`;
- `tests/test_combat_resolve_race.py`.

Найди три разных уровня ошибки: конкурентная запись, битое состояние одного
матча, падение целого тика. Объясни разную реакцию.

### Modify

В отдельном мини-файле реализуй `process(items, fn)`, который возвращает
успехи, логирует ошибки и не прекращает batch. Затем добавь специальное
исключение `StopBatch`, которое обязано прерваться. Сначала тесты, затем код.

### Make

С чистого листа напиши контекстный менеджер для временного «ресурса», который
логирует acquire/release и гарантирует release при исключении. Реализуй
сначала классом, потом `@contextmanager`; сравни состояния.

## Типичные ложные модели

- «Аннотация `list[str]` копирует/замораживает список». Нет, это только
  контракт для инструментов; runtime-объект остаётся mutable.
- «Generator уже выполнил тело при вызове». Нет, вызов создаёт generator;
  тело стартует на первом `next`.
- «`finally` выполняется только при ошибке». Он выполняется при любом выходе.
- «Широкий `except` всегда плох». Он допустим на чёткой fault-containment
  границе с логом и восстановлением.
- «Pydantic — улучшенный dataclass». У них разные главные обязанности.

## Самопроверка

1. Объясни aliasing и mutable default через момент создания объектов.
2. Что хранит closure?
3. Чем iterable отличается от iterator?
4. Когда исполняется код generator?
5. Почему `append` после commit — часть correctness?
6. Где уместен `except Exception`, а где нет?
7. Когда выбрать dataclass, а когда Pydantic?

<details>
<summary>Короткие ответы</summary>

1. Два имени могут указывать на один mutable-объект; default создаётся один
   раз при `def`.
2. Связи с enclosing scope/frame, необходимые свободным переменным.
3. Iterable создаёт iterator; iterator хранит прогресс и выдаёт элементы.
4. При итерации, начиная с первого `next`/цикла.
5. До commit результат ещё не стал durable truth; broadcast/return создал бы
   фантомный успех.
6. На внешней границе отказоустойчивого процесса с восстановлением и логом;
   не внутри логики, где ошибка замалчивается.
7. Dataclass для доверенной внутренней структуры; Pydantic на
   валидационной/сериализационной границе.

</details>

## Проверка мастерства и повторение

Без запуска предскажи пять коротких примеров на aliasing, closure, generator,
`try/finally` и исключения. Затем создай один новый пример, на котором старая
ошибка дала бы другой результат. Зачёт — 4/5 прогнозов и причинные объяснения.

- **+1:** вопросы 1–7.
- **+3:** восстановить batch pattern.
- **+7:** найти в проекте ещё два lifecycle-контракта.
- **+14:** объяснить новый Python-фрагмент до запуска.

Углубление:
[Python tutorial](https://docs.python.org/3/tutorial/),
[Data model](https://docs.python.org/3/reference/datamodel.html),
[Exceptions](https://docs.python.org/3/tutorial/errors.html),
[contextlib](https://docs.python.org/3/library/contextlib.html).
