import { useEffect, useMemo, useRef, useState } from "react";
import { courseAnchor, courseRoute, mergeCards } from "./sessionData";
import type {
  AnswerRecord,
  Bootstrap,
  CardSchedule,
  CourseChapter,
  LearningCard,
  LearningProgress,
  SelfAssessment,
} from "./types";

const STORAGE_KEY = "vladstone-learning-progress-v1";
const sessionSize: Record<LearningProgress["preferredLength"], number> = {
  5: 1,
  10: 2,
  15: 3,
};
const reviewIntervalsInDays = [1, 3, 7, 14];

const defaultProgress = (): LearningProgress => ({
  version: 1,
  currentChapterId: "02",
  preferredLength: 10,
  answers: [],
  cardSchedules: {},
  completedSessions: [],
  updatedAt: new Date(0).toISOString(),
});

function normaliseProgress(raw: unknown): LearningProgress {
  type SavedAnswer = Omit<AnswerRecord, "selfAssessment"> & {
    selfAssessment?: SelfAssessment;
    result?: SelfAssessment;
  };
  const parsed = raw as Omit<Partial<LearningProgress>, "answers"> & { answers?: SavedAnswer[] };
  return {
    ...defaultProgress(),
    ...parsed,
    answers: (parsed.answers ?? []).map(({ result, ...answer }) => ({
      ...answer,
      selfAssessment: answer.selfAssessment ?? result ?? "review",
    })),
    cardSchedules: parsed.cardSchedules ?? {},
  };
}

function readBrowserProgress(): LearningProgress {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (!saved) return defaultProgress();
    return normaliseProgress(JSON.parse(saved));
  } catch {
    return defaultProgress();
  }
}

function stripCodeTags(text: string) {
  return text.replace(/<code>(.*?)<\/code>/g, "$1").replaceAll("&lt;", "<").replaceAll("&gt;", ">");
}

function formatDate(date: string) {
  return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "short" }).format(new Date(date));
}

function weekSessionCount(sessions: LearningProgress["completedSessions"]) {
  const now = new Date();
  const monday = new Date(now);
  const weekday = (now.getDay() + 6) % 7;
  monday.setDate(now.getDate() - weekday);
  monday.setHours(0, 0, 0, 0);
  return sessions.filter((session) => new Date(session.completedAt) >= monday).length;
}

function addDays(days: number) {
  const due = new Date();
  due.setDate(due.getDate() + days);
  return due.toISOString();
}

function scheduleCard(previous: CardSchedule | undefined, selfAssessment: SelfAssessment): CardSchedule {
  const level = selfAssessment === "understood"
    ? Math.min((previous?.level ?? -1) + 1, reviewIntervalsInDays.length - 1)
    : 0;
  const now = new Date().toISOString();
  return {
    level,
    dueAt: addDays(reviewIntervalsInDays[level]),
    lastSelfAssessment: selfAssessment,
    lastAnsweredAt: now,
  };
}

function nextCards(cards: LearningCard[], progress: LearningProgress, count: number) {
  const now = new Date();
  const due = cards
    .filter((card) => {
      const schedule = progress.cardSchedules[card.id];
      return schedule && new Date(schedule.dueAt) <= now;
    })
    .sort((left, right) => new Date(progress.cardSchedules[left.id].dueAt).getTime() - new Date(progress.cardSchedules[right.id].dueAt).getTime());

  const newBridges = cards.filter((card) =>
    card.kind === "bridge" && card.chapterId === progress.currentChapterId && !progress.cardSchedules[card.id],
  );
  const newCurrentChapter = cards.filter((card) =>
    card.kind === "course" && card.chapterId === progress.currentChapterId && !progress.cardSchedules[card.id],
  );
  const newAnki = cards.filter((card) => card.kind === "anki" && !progress.cardSchedules[card.id]);

  const queue = [...due.slice(0, 1), ...newBridges, ...newCurrentChapter, ...newAnki, ...due.slice(1)];
  return Array.from(new Map(queue.map((card) => [card.id, card])).values()).slice(0, count);
}

function nextChapter(currentChapterId: string) {
  const index = courseRoute.indexOf(currentChapterId);
  return courseRoute[index + 1] ?? currentChapterId;
}

function App() {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [progress, setProgress] = useState<LearningProgress>(readBrowserProgress);
  const [isReady, setIsReady] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [answer, setAnswer] = useState("");
  const [confidence, setConfidence] = useState<number | null>(null);
  const [hintsOpened, setHintsOpened] = useState(0);
  const [showAnswer, setShowAnswer] = useState(false);
  const [showCourse, setShowCourse] = useState(false);
  const [selectedChapter, setSelectedChapter] = useState<CourseChapter | null>(null);
  const [copied, setCopied] = useState(false);
  const synchronised = useRef(false);

  useEffect(() => {
    async function boot() {
      try {
        const [bootstrapResponse, serverProgressResponse] = await Promise.all([
          fetch("/api/bootstrap"),
          fetch("/api/progress"),
        ]);
        if (!bootstrapResponse.ok) throw new Error("Курс не удалось загрузить");
        setBootstrap((await bootstrapResponse.json()) as Bootstrap);

        if (serverProgressResponse.ok) {
          const serverProgress = normaliseProgress(await serverProgressResponse.json());
          setProgress((browserProgress) =>
            new Date(serverProgress.updatedAt) > new Date(browserProgress.updatedAt)
              ? serverProgress
              : browserProgress,
          );
        }
      } catch (error) {
        console.error(error);
      } finally {
        synchronised.current = true;
        setIsReady(true);
      }
    }
    void boot();
  }, []);

  useEffect(() => {
    if (!synchronised.current) return;
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(progress));
    void fetch("/api/progress", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(progress),
    });
  }, [progress]);

  const allCards = useMemo(
    () => (bootstrap ? mergeCards(bootstrap.chapters, bootstrap.ankiCards) : []),
    [bootstrap],
  );
  const cardsForSession = useMemo(
    () => nextCards(allCards, progress, sessionSize[progress.preferredLength]),
    [allCards, progress, progress.preferredLength],
  );
  const card = cardsForSession[activeIndex];
  const finishedSession = cardsForSession.length > 0 && activeIndex >= cardsForSession.length;
  const noDueWork = cardsForSession.length === 0;
  const completedThisWeek = weekSessionCount(progress.completedSessions);
  const currentChapter = bootstrap?.chapters.find((chapter) => chapter.id === progress.currentChapterId);
  const currentRouteIndex = courseRoute.indexOf(progress.currentChapterId);
  const dueToday = allCards.filter((candidate) => {
    const schedule = progress.cardSchedules[candidate.id];
    return schedule && new Date(schedule.dueAt) <= new Date();
  }).length;
  const nextDueAt = Object.values(progress.cardSchedules)
    .map((schedule) => new Date(schedule.dueAt))
    .filter((date) => date > new Date())
    .sort((left, right) => left.getTime() - right.getTime())[0];
  const currentMessage = progress.currentChapterId === "02"
    ? courseAnchor.current
    : currentChapter?.title ?? courseAnchor.current;
  const nextMessage = progress.currentChapterId === "02"
    ? courseAnchor.next
    : dueToday > 0
      ? `Сегодня сначала ${dueToday} ${dueToday === 1 ? "повтор" : "повтора"}, потом новая опора.`
      : "Сначала одна новая опора, потом — по расписанию.";

  function chooseLength(length: LearningProgress["preferredLength"]) {
    setProgress((previous) => ({ ...previous, preferredLength: length, updatedAt: new Date().toISOString() }));
    setActiveIndex(0);
    resetQuestion();
  }

  function resetQuestion() {
    setAnswer("");
    setConfidence(null);
    setHintsOpened(0);
    setShowAnswer(false);
  }

  function openCardChapter() {
    const chapter = bootstrap?.chapters.find((item) => item.id === card?.chapterId);
    if (!chapter) return;
    setSelectedChapter(chapter);
    setShowCourse(true);
  }

  function recordResult(selfAssessment: SelfAssessment) {
    if (!card || confidence === null) return;
    const now = new Date().toISOString();
    const record: AnswerRecord = {
      questionId: card.id,
      prompt: card.prompt,
      source: card.source,
      answer: answer.trim(),
      confidence,
      selfAssessment,
      hintsOpened,
      answeredAt: now,
    };

    setProgress((previous) => {
      const cardSchedules = {
        ...previous.cardSchedules,
        [card.id]: scheduleCard(previous.cardSchedules[card.id], selfAssessment),
      };
      let currentChapterId = previous.currentChapterId;
      if (card.id === "anchor-dataclass-pydantic" && selfAssessment === "understood") {
        currentChapterId = "03";
      } else if (card.kind === "course" && card.chapterId === previous.currentChapterId) {
        const currentCards = allCards.filter((candidate) =>
          candidate.kind === "course" && candidate.chapterId === previous.currentChapterId,
        );
        const isFirstPassComplete = currentCards.length > 0 && currentCards.every(
          (candidate) => cardSchedules[candidate.id]?.lastSelfAssessment === "understood",
        );
        if (isFirstPassComplete) currentChapterId = nextChapter(previous.currentChapterId);
      }

      return {
        ...previous,
        currentChapterId,
        answers: [...previous.answers, record],
        cardSchedules,
        completedSessions: [
          ...previous.completedSessions,
          ...(activeIndex + 1 >= cardsForSession.length
            ? [{ completedAt: now, questionIds: cardsForSession.map((item) => item.id) }]
            : []),
        ],
        updatedAt: now,
      };
    });

    if (activeIndex + 1 >= cardsForSession.length) {
      setActiveIndex(cardsForSession.length);
      return;
    }

    setActiveIndex((previous) => previous + 1);
    resetQuestion();
  }

  async function copyAiContext() {
    const latestAnswers = progress.answers.slice(-5).reverse();
    const text = [
      "Учебный контекст VladStone",
      `Точка: ${courseAnchor.current}. Следующее: ${courseAnchor.next}.`,
      `Полный журнал автоматически лежит в LearningPrototype/data/learning-progress.json.`,
      "Последние ответы:",
      ...latestAnswers.map(
        (item) =>
          `- ${stripCodeTags(item.prompt)}\n  Ответ: ${item.answer || "(пусто)"}\n  Уверенность: ${item.confidence}/100; самооценка: ${item.selfAssessment === "understood" ? "пока понимаю" : "нужен повтор"}.`,
      ),
    ].join("\n");
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  if (!isReady) {
    return <main className="loading">Поднимаю твою следующую тему…</main>;
  }

  if (!bootstrap || !card && !finishedSession && !noDueWork) {
    return <main className="loading">Не удалось открыть материалы курса. Проверь, что сайт запущен через <code>npm run dev</code>.</main>;
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">VLADSTONE · ЛИЧНЫЙ КУРС</p>
          <h1>Просто зайди. Следующий ход уже готов.</h1>
        </div>
        <button className="subtle-button" onClick={() => void copyAiContext()}>
          {copied ? "Контекст скопирован" : "Контекст для AI"}
        </button>
      </header>

      <section className="overview" aria-label="Состояние обучения">
        <div className="current-route">
          <span className="route-dot" />
          <div>
            <p className="label">Ты здесь</p>
            <strong>{currentMessage}</strong>
            <p>{nextMessage}</p>
          </div>
        </div>
        <div className="weekly-progress">
            <p className="label">Неделя без наказаний</p>
            <strong>{completedThisWeek}/3 касания</strong>
          <div className="dots" aria-label={`${completedThisWeek} сессий на этой неделе`}>
            {[0, 1, 2].map((index) => <span className={index < completedThisWeek ? "filled" : ""} key={index} />)}
          </div>
        </div>
      </section>

      <section className="study-layout">
        <article className="session-card">
          {finishedSession ? (
            <div className="session-finished">
              <p className="eyebrow">СЕССИЯ ЗАКРЫТА</p>
              <h2>На сегодня достаточно.</h2>
              <p>Ты сделал {cardsForSession.length} {cardsForSession.length === 1 ? "ход" : "хода"}. Следующий вопрос сам будет ждать при новом запуске.</p>
              <button className="primary-button" onClick={() => { setActiveIndex(0); resetQuestion(); }}>
                Открыть ещё одну короткую сессию
              </button>
            </div>
          ) : noDueWork ? (
            <div className="session-finished">
              <p className="eyebrow">ПАУЗА ПО РАСПИСАНИЮ</p>
              <h2>Сегодня не нужно выжимать ещё один вопрос.</h2>
              <p>
                {nextDueAt
                  ? `Следующий повтор появится ${formatDate(nextDueAt.toISOString())}. Материал не исчезнет; интервал — часть тренировки.`
                  : "Ты прошёл все подготовленные карточки. Открой следующую главу на карте или добавь новую самопроверку в материалы курса."}
              </p>
            </div>
          ) : (
            <>
              <div className="session-heading">
                <div>
                  <p className="eyebrow">ХОД {activeIndex + 1} ИЗ {cardsForSession.length}</p>
                  <p className="source">{card.source} · {dueToday > 0 && activeIndex === 0 ? "сначала повтор по расписанию" : "новая опора"}</p>
                </div>
                <div className="length-switch" aria-label="Длина сессии">
                  {([5, 10, 15] as const).map((length) => (
                    <button
                      className={progress.preferredLength === length ? "selected" : ""}
                      key={length}
                      onClick={() => chooseLength(length)}
                    >
                      {length} мин
                    </button>
                  ))}
                </div>
              </div>

              <h2>{stripCodeTags(card.prompt)}</h2>
              <label className="answer-label" htmlFor="answer">Твоя версия — до разбора</label>
              <textarea
                id="answer"
                placeholder="Пиши как думаешь. Догадка тоже годится."
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
                rows={6}
              />

              <fieldset className="confidence">
                <legend>Уверенность до разбора</legend>
                <div>
                  {[0, 25, 50, 75, 100].map((value) => (
                    <button
                      type="button"
                      className={confidence === value ? "selected" : ""}
                      onClick={() => setConfidence(value)}
                      key={value}
                    >
                      {value}
                    </button>
                  ))}
                </div>
                <p className="confidence-help">0 — наугад, 50 — есть модель, 100 — смогу защитить причинную цепочку.</p>
              </fieldset>

              {!showAnswer ? (
                <div className="actions">
                  {card.hint && hintsOpened === 0 && (
                    <button className="text-button" onClick={() => setHintsOpened(1)}>Показать маленький намёк</button>
                  )}
                  <button className="text-button" onClick={openCardChapter}>Открыть главу как опору</button>
                  {hintsOpened > 0 && card.hint && <p className="hint">{card.hint}</p>}
                  <button className="primary-button" disabled={!answer.trim() || confidence === null} onClick={() => setShowAnswer(true)}>
                    Открыть разбор
                  </button>
                </div>
              ) : (
                <div className="feedback-card">
                  <p className="eyebrow">ОПОРА ДЛЯ СВЕРКИ</p>
                  <p>{stripCodeTags(card.expectedAnswer)}</p>
                  <p className="feedback-question">Это самооценка, не автоматическая проверка. Что честнее записать для следующего повтора?</p>
                  <div className="result-actions">
                    <button className="secondary-button" onClick={() => recordResult("review")}>Нужен повтор</button>
                    <button className="primary-button" onClick={() => recordResult("understood")}>Пока понимаю, дальше</button>
                  </div>
                </div>
              )}
            </>
          )}
        </article>

        <aside className="course-panel">
          <p className="eyebrow">КАРТА КУРСА</p>
          <p className="course-count">{bootstrap.chapters.length} глав · материалы уже в проекте</p>
          <ol>
            {courseRoute.map((chapterId) => {
              const chapter = bootstrap.chapters.find((item) => item.id === chapterId);
              if (!chapter) return null;
              const routeIndex = courseRoute.indexOf(chapter.id);
              const status = routeIndex < currentRouteIndex ? "seen" : routeIndex === currentRouteIndex ? "current" : "future";
              return (
                <li key={chapter.id} className={status}>
                  <button onClick={() => { setSelectedChapter(chapter); setShowCourse(true); }}>
                    <span>{status === "seen" ? "·" : chapter.id}</span>
                    {chapter.title.replace(/^Глава \d+\.\s*/, "")}
                  </button>
                </li>
              );
            })}
          </ol>
          <p className="sync-note">Точка на карте означает «перешёл к следующей главе», а не зачёт. Для зачёта всё ещё нужны Recall, Trace, Build и Transfer без AI.</p>
          <p className="sync-note">Повторы идут через 1, 3, 7 и 14 дней. Ответы синхронизируются в <code>data/learning-progress.json</code>; агент в этом workspace читает фактические ответы, а не только отметки.</p>
        </aside>
      </section>

      {showCourse && selectedChapter && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setShowCourse(false)}>
          <section className="course-modal" role="dialog" aria-modal="true" aria-label={selectedChapter.title} onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-heading">
              <div>
                <p className="eyebrow">{selectedChapter.sourcePath}</p>
                <h2>{selectedChapter.title}</h2>
              </div>
              <button className="close-button" onClick={() => setShowCourse(false)} aria-label="Закрыть материалы">×</button>
            </div>
            <pre>{selectedChapter.body}</pre>
          </section>
        </div>
      )}

      <footer>
        <span>Последний ответ: {progress.answers.length ? formatDate(progress.answers.at(-1)!.answeredAt) : "ещё нет"}</span>
        <span>{currentChapter?.sourcePath ?? "docs/learning/START.md"}</span>
      </footer>
    </main>
  );
}

export default App;
