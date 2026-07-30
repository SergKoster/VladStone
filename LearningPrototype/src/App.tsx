import { useEffect, useMemo, useRef, useState } from "react";
import { courseAnchor, mergeCards } from "./sessionData";
import type {
  AnswerRecord,
  AnswerResult,
  Bootstrap,
  CourseChapter,
  LearningCard,
  LearningProgress,
} from "./types";

const STORAGE_KEY = "vladstone-learning-progress-v1";
const sessionSize: Record<LearningProgress["preferredLength"], number> = {
  5: 1,
  10: 2,
  15: 3,
};

const defaultProgress = (): LearningProgress => ({
  version: 1,
  currentChapterId: "02",
  preferredLength: 10,
  answers: [],
  completedSessions: [],
  updatedAt: new Date(0).toISOString(),
});

function readBrowserProgress(): LearningProgress {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return saved ? (JSON.parse(saved) as LearningProgress) : defaultProgress();
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

function nextCards(cards: LearningCard[], answers: AnswerRecord[], count: number) {
  const previousById = new Map<string, AnswerRecord>();
  answers.forEach((answer) => previousById.set(answer.questionId, answer));

  return [...cards]
    .sort((left, right) => {
      const leftAnswer = previousById.get(left.id);
      const rightAnswer = previousById.get(right.id);
      const leftPriority = leftAnswer?.result === "review" ? 0 : leftAnswer ? 2 : 1;
      const rightPriority = rightAnswer?.result === "review" ? 0 : rightAnswer ? 2 : 1;
      return leftPriority - rightPriority;
    })
    .slice(0, count);
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
          const serverProgress = (await serverProgressResponse.json()) as LearningProgress;
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

  const allCards = useMemo(() => (bootstrap ? mergeCards(bootstrap.cards) : []), [bootstrap]);
  const cardsForSession = useMemo(
    () => nextCards(allCards, progress.answers, sessionSize[progress.preferredLength]),
    [allCards, progress.answers, progress.preferredLength],
  );
  const card = cardsForSession[activeIndex];
  const finishedSession = cardsForSession.length > 0 && activeIndex >= cardsForSession.length;
  const completedThisWeek = weekSessionCount(progress.completedSessions);
  const currentChapter = bootstrap?.chapters.find((chapter) => chapter.id === progress.currentChapterId);

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

  function recordResult(result: AnswerResult) {
    if (!card || confidence === null) return;
    const now = new Date().toISOString();
    const record: AnswerRecord = {
      questionId: card.id,
      prompt: card.prompt,
      source: card.source,
      answer: answer.trim(),
      confidence,
      result,
      hintsOpened,
      answeredAt: now,
    };

    setProgress((previous) => ({
      ...previous,
      answers: [...previous.answers.filter((item) => item.questionId !== card.id), record],
      updatedAt: now,
    }));

    if (activeIndex + 1 >= cardsForSession.length) {
      setProgress((previous) => ({
        ...previous,
        completedSessions: [
          ...previous.completedSessions,
          { completedAt: now, questionIds: cardsForSession.map((item) => item.id) },
        ],
        updatedAt: now,
      }));
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
          `- ${stripCodeTags(item.prompt)}\n  Ответ: ${item.answer || "(пусто)"}\n  Уверенность: ${item.confidence}/5; самооценка: ${item.result === "understood" ? "понял" : "повторить"}.`,
      ),
    ].join("\n");
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  if (!isReady) {
    return <main className="loading">Поднимаю твою следующую тему…</main>;
  }

  if (!bootstrap || !card && !finishedSession) {
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
            <strong>{courseAnchor.current}</strong>
            <p>{courseAnchor.next}</p>
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
          ) : (
            <>
              <div className="session-heading">
                <div>
                  <p className="eyebrow">ХОД {activeIndex + 1} ИЗ {cardsForSession.length}</p>
                  <p className="source">{card.source}</p>
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
                <legend>Насколько уверен?</legend>
                <div>
                  {[1, 2, 3, 4, 5].map((value) => (
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
              </fieldset>

              {!showAnswer ? (
                <div className="actions">
                  {card.hint && hintsOpened === 0 && (
                    <button className="text-button" onClick={() => setHintsOpened(1)}>Показать маленький намёк</button>
                  )}
                  {hintsOpened > 0 && card.hint && <p className="hint">{card.hint}</p>}
                  <button className="primary-button" disabled={!answer.trim() || confidence === null} onClick={() => setShowAnswer(true)}>
                    Открыть разбор
                  </button>
                </div>
              ) : (
                <div className="feedback-card">
                  <p className="eyebrow">ОПОРА ДЛЯ СВЕРКИ</p>
                  <p>{stripCodeTags(card.expectedAnswer)}</p>
                  <p className="feedback-question">После сравнения: получилось удержать причинную модель?</p>
                  <div className="result-actions">
                    <button className="secondary-button" onClick={() => recordResult("review")}>Вернуть на повтор</button>
                    <button className="primary-button" onClick={() => recordResult("understood")}>Понял, дальше</button>
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
            {bootstrap.chapters.map((chapter) => {
              const status = chapter.id === "01" ? "done" : chapter.id === "02" ? "current" : "future";
              return (
                <li key={chapter.id} className={status}>
                  <button onClick={() => { setSelectedChapter(chapter); setShowCourse(true); }}>
                    <span>{status === "done" ? "✓" : chapter.id}</span>
                    {chapter.title.replace(/^Глава \d+\.\s*/, "")}
                  </button>
                </li>
              );
            })}
          </ol>
          <p className="sync-note">Ответы синхронизируются в <code>data/learning-progress.json</code> — агент в этом workspace может прочитать их напрямую.</p>
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
