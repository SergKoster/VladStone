import React from "react";

import {
  type CombatCatalogCard,
  type CombatEvent,
  type CombatMatch,
  type CombatResponse,
  type CombatStatusDefinition,
  type CombatUnit,
  type Placement,
  type SpellCast,
  getCombat,
  resolveCombat,
  startCombat,
} from "../../api";
import { CardArt } from "../../shared/cardArt";
import { BootIcon, BurstIcon, HeartIcon, SwordIcon } from "../../shared/icons";
import { CardDetail } from "../collection/CardDetail";
import {
  AREA_PULSE_MS,
  DEATH_FADE_MS,
  DECK_DRAW_MS,
  LUNGE_MS,
  MOVE_MS,
  PHASE_OVERLAY_FADE_MS,
  POPUP_TTL_MS,
  SPAWN_MS,
  SPELL_CAST_MS,
  UNIT_WAITED_MS,
} from "./animationConfig";
import {
  type BattlePopup,
  type CellPulse,
  type LungeEffect,
} from "./battleAnimations";
import { type MatchRealtimeStatus, connectMatchRealtime } from "./matchRealtime";
import { phaseLabel, responsePlaybackKey } from "./turnPlayback";
import { useTurnPlayback } from "./useTurnPlayback";

type Props = {
  cards: CombatCatalogCard[];
  statuses: CombatStatusDefinition[];
  onBattleFinished: () => void;
};

type PlannedUnit = { kind: "unit"; card_id: string; row: number; col: number };
type PlannedSpell = { kind: "spell"; card_id: string; row: number; col: number };
type Planned = PlannedUnit | PlannedSpell;

const TURN_SECONDS = 30;
// Пикселей до превращения нажатия на карту в перетаскивание (ниже — тап-выбор).
const DRAG_THRESHOLD = 6;
// Даёт спокойно пересечь короткий зазор между токеном и плавающей панелью.
const INSPECTOR_CLOSE_DELAY_MS = 240;
const INSPECTOR_EDGE_PX = 8;
const INSPECTOR_GAP_PX = 10;
const INSPECTOR_WIDTH_PX = 224;
const INSPECTOR_MAX_HEIGHT_PX = 280;

type InspectorPlacement =
  | { side: "right"; left: number; top: number }
  | { side: "left"; left: number; top: number }
  | { side: "bottom" };

type InspectedUnit = { unitId: string; placement: InspectorPlacement };
// V8: запись клиентского журнала розыгрышей (события spell_cast/spawn публичны).
type PlayLogEntry = {
  key: number;
  turn: number;
  mine: boolean;
  cardId: string;
  row: number;
  col: number;
  kind: "spell" | "unit";
};
type CombatDetail = {
  cardId: string | null;
  fromHand: boolean;
  fallbackDescription?: string;
  fallbackName?: string;
  unit?: CombatUnit;
};

export function BattleV4({ cards, statuses, onBattleFinished }: Props) {
  const catalog = React.useMemo(() => new Map(cards.map((c) => [c.id, c])), [cards]);
  const statusCatalog = React.useMemo(
    () => new Map(statuses.map((status) => [status.id, status])),
    [statuses],
  );
  const [match, setMatch] = React.useState<CombatMatch | null>(null);
  const matchRef = React.useRef<CombatMatch | null>(null);
  const [planned, setPlanned] = React.useState<Planned[]>([]);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [resultDismissed, setResultDismissed] = React.useState(false);
  const [realtime, setRealtime] = React.useState<MatchRealtimeStatus>("Realtime не подключен");
  const [secondsLeft, setSecondsLeft] = React.useState(TURN_SECONDS);
  const {
    activeEvent,
    animatedMatch,
    cellPulses,
    deckDraws,
    dyingIds,
    isAnimating,
    lunges,
    phaseEvent,
    playTurn,
    popups,
    spawningIds,
    spellCasts,
    waitedUnits,
  } = useTurnPlayback();
  // Синхронный флаг для WS-обработчика: React-state обновляется не сразу, а
  // echo собственного resolve может прилететь раньше HTTP-ответа и показать
  // финальное поле перед запуском плеера.
  const isResolvingRef = React.useRef(false);
  // Перетаскивание карты руки на клетку (pointer events — мышь и тач одним путём).
  const dragRef = React.useRef<{
    cardId: string;
    startX: number;
    startY: number;
    dragging: boolean;
  } | null>(null);
  // Глотает click, который браузер синтезирует после pointerup (чтобы драг/тап
  // не сработали дважды через onClick).
  const suppressClickRef = React.useRef(false);
  const [dragGhost, setDragGhost] = React.useState<{
    x: number;
    y: number;
    valid: boolean;
    name: string;
  } | null>(null);
  const autoSubmittedDeadline = React.useRef<string | null>(null);
  const realtimePlaybackKeyRef = React.useRef<string | null>(null);
  // Полноценное WS-эхо не выбрасываем во время собственного HTTP resolve:
  // при гонке с таймером именно оно может оказаться единственной лентой хода.
  const pendingRealtimeResolutionRef = React.useRef<CombatResponse | null>(null);
  const realtimeResolutionWaiterRef = React.useRef<
    ((payload: CombatResponse) => void) | null
  >(null);
  const inspectorCloseTimerRef = React.useRef<number | null>(null);
  const inspectedTokenRef = React.useRef<HTMLElement | null>(null);
  const lastInspectorPointerTypeRef = React.useRef<string | null>(null);
  const [inspected, setInspected] = React.useState<InspectedUnit | null>(null);
  const detailSourceRef = React.useRef<HTMLElement | null>(null);
  const [detail, setDetail] = React.useState<CombatDetail | null>(null);

  // V8: клиентский журнал розыгрышей. Серверный match.log в v4 пуст; журнал
  // строится из событий завершённых ходов (розыгрыш публичен для обоих).
  const [playLog, setPlayLog] = React.useState<PlayLogEntry[]>([]);
  const [logHighlight, setLogHighlight] = React.useState<
    { key: number; row: number; col: number } | null
  >(null);
  const playLogTurnsRef = React.useRef(new Set<string>());
  const playLogKeyRef = React.useRef(0);
  const logHighlightTimerRef = React.useRef<number | null>(null);

  const recordPlays = React.useCallback((payload: CombatResponse) => {
    const turn = payload.resolved_turn;
    if (turn === null) return;
    const dedupKey = `${payload.match.id}:${turn}`;
    if (playLogTurnsRef.current.has(dedupKey)) return;
    playLogTurnsRef.current.add(dedupKey);
    const viewerSide = payload.match.players.find(
      (p) => p.id === payload.match.viewer_id,
    )?.side;
    const entries: PlayLogEntry[] = [];
    for (const event of payload.events) {
      if (!event.card_id || !event.to_position) continue;
      if (event.type === "spell_cast") {
        entries.push({
          key: ++playLogKeyRef.current,
          turn,
          mine: event.actor_id === payload.match.viewer_id,
          cardId: event.card_id,
          row: event.to_position.row,
          col: event.to_position.col,
          kind: "spell",
        });
      } else if (event.type === "spawn") {
        // Актор спавна — юнит; его сторону даёт снапшот события.
        const side = event.snapshot.units.find((u) => u.id === event.actor_id)?.side;
        entries.push({
          key: ++playLogKeyRef.current,
          turn,
          mine: side === viewerSide,
          cardId: event.card_id,
          row: event.to_position.row,
          col: event.to_position.col,
          kind: "unit",
        });
      }
    }
    if (entries.length) setPlayLog((prev) => [...prev, ...entries].slice(-24));
  }, []);

  function flashLogHighlight(entry: PlayLogEntry) {
    if (logHighlightTimerRef.current !== null) {
      window.clearTimeout(logHighlightTimerRef.current);
    }
    setLogHighlight({ key: entry.key, row: entry.row, col: entry.col });
    // Тач не шлёт pointerleave — подсветка сама гаснет.
    logHighlightTimerRef.current = window.setTimeout(
      () => setLogHighlight(null),
      1600,
    );
  }

  // V1: добранная карта определяется diff-ом СВОЕЙ руки до/после хода —
  // сервер её в событиях не раскрывает (анти-чит), но владелец видит свою
  // руку в payload. Помеченная карта влетает в свой слот со стороны стопки.
  const [justDrawn, setJustDrawn] = React.useState<{ cardId: string } | null>(null);
  const justDrawnTimerRef = React.useRef<number | null>(null);

  const commitMatch = React.useCallback((nextMatch: CombatMatch) => {
    const prev = matchRef.current;
    if (prev && nextMatch.id === prev.id && nextMatch.turn > prev.turn) {
      const viewerId = nextMatch.viewer_id;
      const before = prev.players.find((p) => p.id === viewerId)?.hand ?? [];
      const after = nextMatch.players.find((p) => p.id === viewerId)?.hand ?? [];
      const counts = new Map<string, number>();
      before.forEach((id) => counts.set(id, (counts.get(id) ?? 0) + 1));
      const gained = after.filter((id) => {
        const left = counts.get(id) ?? 0;
        if (left > 0) {
          counts.set(id, left - 1);
          return false;
        }
        return true;
      });
      if (gained.length === 1) {
        if (justDrawnTimerRef.current !== null) {
          window.clearTimeout(justDrawnTimerRef.current);
        }
        setJustDrawn({ cardId: gained[0] });
        justDrawnTimerRef.current = window.setTimeout(
          () => setJustDrawn(null),
          DECK_DRAW_MS + 200,
        );
      }
    }
    matchRef.current = nextMatch;
    setMatch(nextMatch);
  }, []);

  const renderedMatch = isAnimating && animatedMatch ? animatedMatch : match;
  const viewer = renderedMatch?.players.find((p) => p.id === renderedMatch.viewer_id) ?? null;
  const enemy = renderedMatch?.players.find((p) => viewer && p.team !== viewer.team) ?? null;
  const rows = renderedMatch?.rows ?? 5;
  const cols = renderedMatch?.cols ?? 5;
  const isFinished =
    renderedMatch?.result.status === "finished" || renderedMatch?.result.status === "expired";

  const plannedCost = planned.reduce((sum, p) => sum + (catalog.get(p.card_id)?.cost ?? 0), 0);
  const availableMana = Math.max(0, (viewer?.mana ?? 0) - plannedCost);

  function clearInspectorCloseTimer() {
    if (inspectorCloseTimerRef.current !== null) {
      window.clearTimeout(inspectorCloseTimerRef.current);
      inspectorCloseTimerRef.current = null;
    }
  }

  function placementForInspector(target: HTMLElement): InspectorPlacement {
    const rect = target.getBoundingClientRect();
    const top = Math.max(
      INSPECTOR_EDGE_PX,
      Math.min(rect.top, window.innerHeight - INSPECTOR_MAX_HEIGHT_PX - INSPECTOR_EDGE_PX),
    );
    if (rect.right + INSPECTOR_GAP_PX + INSPECTOR_WIDTH_PX <= window.innerWidth - INSPECTOR_EDGE_PX) {
      return { side: "right", left: rect.right + INSPECTOR_GAP_PX, top };
    }
    if (rect.left - INSPECTOR_GAP_PX - INSPECTOR_WIDTH_PX >= INSPECTOR_EDGE_PX) {
      return { side: "left", left: rect.left - INSPECTOR_GAP_PX - INSPECTOR_WIDTH_PX, top };
    }
    return { side: "bottom" };
  }

  function openInspector(unitId: string, target: HTMLElement) {
    clearInspectorCloseTimer();
    inspectedTokenRef.current = target;
    setInspected({ unitId, placement: placementForInspector(target) });
  }

  function scheduleInspectorClose(unitId: string) {
    clearInspectorCloseTimer();
    inspectorCloseTimerRef.current = window.setTimeout(() => {
      inspectorCloseTimerRef.current = null;
      const focusedUnitId = document.activeElement?.getAttribute("data-inspector-unit-id");
      if (focusedUnitId !== unitId) {
        setInspected((current) => (current?.unitId === unitId ? null : current));
      }
    }, INSPECTOR_CLOSE_DELAY_MS);
  }

  // V5 (решение владельца): ховер-инспектор живёт только пока курсор на самом
  // токене — уход с юнита закрывает панель СРАЗУ, без задержки и без «заезда»
  // курсором внутрь панели. Задержка остаётся только у blur (клавиатура).
  function closeInspectorNow(unitId: string) {
    clearInspectorCloseTimer();
    setInspected((current) => (current?.unitId === unitId ? null : current));
  }

  function rememberInspectorPointer(pointerType: string) {
    lastInspectorPointerTypeRef.current = pointerType;
    window.setTimeout(() => {
      lastInspectorPointerTypeRef.current = null;
    }, 0);
  }

  function openDetail(
    nextDetail: CombatDetail,
    source: HTMLElement,
  ) {
    clearInspectorCloseTimer();
    setInspected(null);
    detailSourceRef.current = source;
    setDetail(nextDetail);
  }

  function closeDetail() {
    setDetail(null);
    window.requestAnimationFrame(() => detailSourceRef.current?.focus());
  }

  function canChooseCard(cardId: string): boolean {
    if (busy || isAnimating || isFinished) return false;
    const card = catalog.get(cardId);
    if (!card) return false;
    const plannedCopies = planned.filter((plan) => plan.card_id === cardId).length;
    const handCopies = (viewer?.hand ?? []).filter((id) => id === cardId).length;
    return plannedCopies < handCopies && plannedCost + card.cost <= (viewer?.mana ?? 0);
  }

  function chooseCardFromDetail(cardId: string) {
    if (!canChooseCard(cardId)) return;
    setSelected(cardId);
    closeDetail();
  }

  React.useEffect(() => {
    if (!inspected) return undefined;
    const updatePlacement = () => {
      if (inspectedTokenRef.current) {
        setInspected((current) =>
          current ? { ...current, placement: placementForInspector(inspectedTokenRef.current!) } : current,
        );
      }
    };
    window.addEventListener("resize", updatePlacement);
    window.addEventListener("scroll", updatePlacement, true);
    return () => {
      window.removeEventListener("resize", updatePlacement);
      window.removeEventListener("scroll", updatePlacement, true);
    };
  }, [inspected?.unitId]);

  React.useEffect(
    () => () => {
      clearInspectorCloseTimer();
    },
    [],
  );

  // --- realtime: server-pushed updates (timer resolves, own resolve echo) ---
  React.useEffect(() => {
    if (!match) return undefined;
    const clearPlans = () => {
      setPlanned([]);
      setSelected(null);
    };
    const consumeResolution = (payload: CombatResponse) => {
      // R1: broadcast собственного resolve может обогнать HTTP-ответ. Не даём
      // ему показать финальный кадр, но сохраняем полную ленту на случай 409.
      if (isResolvingRef.current) {
        if (payload.events.length > 0) {
          pendingRealtimeResolutionRef.current = payload;
          realtimeResolutionWaiterRef.current?.(payload);
        }
        return;
      }
      const preMatch = matchRef.current;
      if (!preMatch) {
        commitMatch(payload.match);
        clearPlans();
        return;
      }
      clearPlans();

      const advanced =
        payload.match.turn > preMatch.turn || payload.match.status !== preMatch.status;
      if (!advanced || payload.events.length === 0) {
        // Eventless snapshot допустим для первичного connect, но не является
        // источником реплея завершённого хода.
        commitMatch(payload.match);
        return;
      }

      recordPlays(payload); // V8: журнал розыгрышей (свой дедуп по ходу)
      const playbackKey = responsePlaybackKey(payload);
      if (realtimePlaybackKeyRef.current === playbackKey) return;
      realtimePlaybackKeyRef.current = playbackKey;
      void playTurn(preMatch, payload.events, payload.match, playbackKey)
        .then((result) => {
          if (result !== "busy") commitMatch(payload.match);
        })
        .catch(() => commitMatch(payload.match))
        .finally(() => {
          if (realtimePlaybackKeyRef.current === playbackKey) {
            realtimePlaybackKeyRef.current = null;
          }
        });
    };
    const applySnapshot = (payload: CombatResponse) => consumeResolution(payload);
    const applyUpdate = (payload: CombatResponse) => consumeResolution(payload);
    const disconnect = connectMatchRealtime({
      matchId: match.id,
      onSnapshot: applySnapshot,
      onUpdate: applyUpdate,
      onStatus: setRealtime,
    });
    return disconnect;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [match?.id]);

  // --- turn countdown from the server planning deadline ---
  // Длительность хода — серверная (эндшпиль сжимает её с 15-го хода,
  // DESIGN §3.5); TURN_SECONDS — только запасное значение до первого payload.
  const planningSeconds = match?.planning_seconds ?? TURN_SECONDS;
  React.useEffect(() => {
    if (isAnimating) {
      // Дедлайн следующего хода уже включает серверный animation buffer, но
      // игроку во время резолва показываем именно паузу, а не убывающие секунды.
      setSecondsLeft(planningSeconds);
      return undefined;
    }
    if (!match?.planning_deadline || match.status !== "planning") {
      setSecondsLeft(planningSeconds);
      return undefined;
    }
    // Серверный deadline включает оценочный animation buffer. Если реальное
    // проигрывание короче резерва, сырой deadline ещё несколько секунд был бы
    // больше длительности хода и визуальный таймер «застывал» бы после
    // анимации. Локальная шкала стартует сейчас, но не продлевает серверный срок.
    const displayDeadline = Math.min(
      Date.parse(match.planning_deadline),
      Date.now() + planningSeconds * 1000,
    );
    const tick = () => {
      const left = Math.max(
        0,
        Math.ceil((displayDeadline - Date.now()) / 1000),
      );
      setSecondsLeft(left);
    };
    tick();
    const id = window.setInterval(tick, 500);
    return () => window.clearInterval(id);
  }, [isAnimating, match?.planning_deadline, match?.status, planningSeconds]);

  React.useEffect(() => {
    if (
      !match?.planning_deadline ||
      match.status !== "planning" ||
      secondsLeft > 0 ||
      busy ||
      isAnimating
    ) {
      return;
    }
    const deadlineKey = `${match.id}:${match.turn}:${match.planning_deadline}`;
    if (autoSubmittedDeadline.current === deadlineKey) return;
    autoSubmittedDeadline.current = deadlineKey;
    void handleResolve();
  }, [
    busy,
    isAnimating,
    match?.id,
    match?.planning_deadline,
    match?.status,
    match?.turn,
    secondsLeft,
  ]);

  React.useEffect(() => {
    if (isFinished) setResultDismissed(false);
  }, [isFinished]);

  async function handleStart() {
    if (isAnimating) return;
    setBusy(true);
    try {
      const res = await startCombat();
      commitMatch(res.match);
      setPlanned([]);
      setSelected(null);
      // V8: журнал живёт в рамках одного матча.
      setPlayLog([]);
      setLogHighlight(null);
      playLogTurnsRef.current.clear();
    } finally {
      setBusy(false);
    }
  }

  const unitAt = (row: number, col: number): CombatUnit | undefined =>
    renderedMatch?.units.find((u) => !u.is_tower && u.row === row && u.col === col);
  const plannedAt = (row: number, col: number) =>
    planned.find((p) => p.row === row && p.col === col);

  // Absolute spawn rows for the viewer (bottom side): rows counted from own edge.
  const spawnRowsFor = (card: CombatCatalogCard): number[] =>
    (card.spawn_rows ?? []).map((r) => rows - r).filter((r) => r >= 0 && r < rows);

  function isValidTarget(card: CombatCatalogCard, row: number, col: number): boolean {
    if (col < 0 || col >= cols) return false;
    if (card.card_type === "spell") return unitAt(row, col) != null;
    if (!spawnRowsFor(card).includes(row)) return false;
    return !unitAt(row, col) && !plannedAt(row, col);
  }

  // Общая точка размещения — и клик-путь, и drag-n-drop идут через неё
  // (одинаковые проверки маны/зоны/занятости). true — карта запланирована.
  function placeCard(cardId: string, row: number, col: number): boolean {
    if (busy || isAnimating || isFinished) return false;
    const card = catalog.get(cardId);
    if (!card) return false;
    if (plannedCost + card.cost > (viewer?.mana ?? 0)) return false;
    if (!isValidTarget(card, row, col)) return false;
    setPlanned((cur) => [
      ...cur,
      card.card_type === "spell"
        ? { kind: "spell", card_id: card.id, row, col }
        : { kind: "unit", card_id: card.id, row, col },
    ]);
    // Если копий этой карты в руке больше не осталось — снять выбор.
    const inHand = (viewer?.hand ?? []).filter((c) => c === cardId).length;
    const plannedSame = planned.filter((p) => p.card_id === cardId).length + 1;
    if (plannedSame >= inHand) setSelected(null);
    return true;
  }

  function handleCellClick(row: number, col: number) {
    // Повторный обычный тап по уже запланированной клетке отменяет именно этот
    // план. Проверяем раньше выбранной карты, чтобы клик не выглядел как
    // безрезультатный отказ из-за занятой клетки.
    if (plannedAt(row, col)) {
      setPlanned((current) =>
        current.filter((plan) => plan.row !== row || plan.col !== col),
      );
      return;
    }
    if (selected) placeCard(selected, row, col);
  }

  // Клетка под указателем — по elementFromPoint + data-атрибутам. Координаты
  // мерим ЖИВЬЁМ на каждом move: страница может проскроллиться / сервер
  // дорезолвит ход по таймеру, заранее снятые координаты устаревают.
  function cellFromPoint(x: number, y: number): { row: number; col: number } | null {
    const el = document.elementFromPoint(x, y)?.closest(".cell-v4");
    if (!el) return null;
    const row = Number(el.getAttribute("data-row"));
    const col = Number(el.getAttribute("data-col"));
    return Number.isNaN(row) || Number.isNaN(col) ? null : { row, col };
  }

  function handleCardPointerDown(e: React.PointerEvent<HTMLButtonElement>, cardId: string) {
    // Начало нового взаимодействия сбрасывает подавление: настоящий драг мыши
    // может не породить финальный click, и застрявший флаг съел бы следующий.
    suppressClickRef.current = false;
    if (!canChooseCard(cardId)) return;
    dragRef.current = { cardId, startX: e.clientX, startY: e.clientY, dragging: false };
    // Держим move/up на карте даже после ухода указателя за её пределы.
    try {
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      // Некоторые окружения отклоняют capture на синтетических указателях — не фатально.
    }
  }

  function handleCardPointerMove(e: React.PointerEvent<HTMLButtonElement>) {
    const d = dragRef.current;
    if (!d) return;
    const dist = Math.hypot(e.clientX - d.startX, e.clientY - d.startY);
    if (!d.dragging && dist < DRAG_THRESHOLD) return; // ещё тап, не драг
    if (!d.dragging) {
      d.dragging = true;
      setSelected(d.cardId); // выбор включает подсветку валидных клеток (.ok)
    }
    const cell = cellFromPoint(e.clientX, e.clientY);
    const card = catalog.get(d.cardId);
    const valid = Boolean(
      cell &&
        card &&
        plannedCost + card.cost <= (viewer?.mana ?? 0) &&
        isValidTarget(card, cell.row, cell.col),
    );
    setDragGhost({ x: e.clientX, y: e.clientY, valid, name: card?.name ?? d.cardId });
  }

  function handleCardPointerUp(e: React.PointerEvent<HTMLButtonElement>) {
    const d = dragRef.current;
    dragRef.current = null;
    setDragGhost(null);
    if (!d) return;
    suppressClickRef.current = true; // click после pointerup не должен сработать
    if (d.dragging) {
      const cell = cellFromPoint(e.clientX, e.clientY);
      if (cell) placeCard(d.cardId, cell.row, cell.col);
    } else {
      openDetail({ cardId: d.cardId, fromHand: true }, e.currentTarget);
    }
  }

  function handleCardPointerCancel() {
    dragRef.current = null;
    setDragGhost(null);
  }

  function handleCardClick(cardId: string, source: HTMLButtonElement) {
    // Тач/мышь обслуживаются pointerup; клавиатурный click открывает detail.
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    openDetail({ cardId, fromHand: true }, source);
  }

  async function handleResolve() {
    if (!match || busy || isAnimating || isFinished) return;
    const preMatch = match;
    const placements: Placement[] = planned
      .filter((p): p is PlannedUnit => p.kind === "unit")
      .map(({ card_id, row, col }) => ({ card_id, row, col }));
    const spells: SpellCast[] = planned
      .filter((p): p is PlannedSpell => p.kind === "spell")
      .map(({ card_id, row, col }) => ({ card_id, row, col }));
    pendingRealtimeResolutionRef.current = null;
    isResolvingRef.current = true;
    setBusy(true);
    try {
      const res = await resolveCombat(match.id, match.turn, placements, spells);
      pendingRealtimeResolutionRef.current = null;
      setPlanned([]);
      setSelected(null);
      recordPlays(res);
      await playTurn(preMatch, res.events, res.match, responsePlaybackKey(res));
      commitMatch(res.match);
      if (res.match.result.status !== "active") onBattleFinished();
    } catch {
      // Дедлайн истёк / ход уже дорезолвлен таймером или конкурентом (409):
      // сначала ждём полноценное WS-эхо. Eventless GET — только fallback,
      // иначе он успевает показать финал и лишает реплей исходного состояния.
      const realtimeResolution =
        pendingRealtimeResolutionRef.current ??
        (await waitForRealtimeResolution(realtimeResolutionWaiterRef));
      const belongsToRequestedTurn =
        realtimeResolution?.match.id === preMatch.id &&
        realtimeResolution.resolved_turn === preMatch.turn &&
        realtimeResolution.events.length > 0;
      if (realtimeResolution && belongsToRequestedTurn) {
        recordPlays(realtimeResolution);
        await playTurn(
          preMatch,
          realtimeResolution.events,
          realtimeResolution.match,
          responsePlaybackKey(realtimeResolution),
        );
        commitMatch(realtimeResolution.match);
      } else {
        const fresh = await getCombat(match.id).catch(() => null);
        if (
          fresh?.resolved_turn === preMatch.turn &&
          fresh.events.length > 0
        ) {
          recordPlays(fresh);
          await playTurn(
            preMatch,
            fresh.events,
            fresh.match,
            responsePlaybackKey(fresh),
          );
          commitMatch(fresh.match);
        } else if (fresh) {
          commitMatch(fresh.match);
        }
      }
      setPlanned([]);
      setSelected(null);
    } finally {
      realtimeResolutionWaiterRef.current = null;
      pendingRealtimeResolutionRef.current = null;
      isResolvingRef.current = false;
      setBusy(false);
    }
  }

  const towersOf = (side: "top" | "bottom") =>
    (renderedMatch?.units ?? [])
      .filter((u) => u.is_tower && u.side === side)
      .sort((a, b) => a.col - b.col);

  // Hand entries, marking planned copies so a card can't be planned twice.
  const handEntries = React.useMemo(() => {
    const usedByCard: Record<string, number> = {};
    return (viewer?.hand ?? []).map((cardId, index) => {
      const used = (usedByCard[cardId] = (usedByCard[cardId] ?? 0) + 1);
      const plannedCount = planned.filter((p) => p.card_id === cardId).length;
      return { key: `${cardId}-${index}`, cardId, isPlanned: used <= plannedCount };
    });
  }, [viewer?.hand, planned]);

  if (!match) {
    return (
      <section className="battle-empty">
        <button className="ghost-btn" disabled={busy || isAnimating} onClick={handleStart}>
          {busy ? "Запуск..." : "Старт боя"}
        </button>
      </section>
    );
  }
  const visibleMatch = renderedMatch ?? match;
  const currentPhaseLabel = phaseLabel(phaseEvent);
  const lungeByUnit = new Map(lunges.map((lunge) => [lunge.unitId, lunge]));
  // V7: подсветка `.ok` на клетках прячется под токенами — юниты-цели
  // выбранного заклинания подсвечиваются на самих токенах.
  const selectedSpell = (() => {
    const card = selected ? catalog.get(selected) : null;
    return card?.card_type === "spell" ? card : null;
  })();
  const waitReasonByUnit = new Map(waitedUnits.map((waited) => [waited.unitId, waited.reason]));
  const visibleUnits = visibleMatch.units
    .filter((unit) => !unit.is_tower)
    .sort((a, b) => a.id.localeCompare(b.id));
  const inspectedUnit = inspected
    ? visibleUnits.find((unit) => unit.id === inspected.unitId) ?? null
    : null;
  const inspectedCard = inspectedUnit?.card_id ? catalog.get(inspectedUnit.card_id) : null;
  const inspectedCoverage = inspectedUnit && inspectedCard
    ? coverageCellsFor(inspectedUnit, inspectedCard, rows, cols)
    : new Set<string>();
  const detailCard = detail?.cardId ? catalog.get(detail.cardId) : undefined;
  const detailAction = detail?.fromHand && detailCard
    ? {
        label: detailCard.card_type === "unit" ? "Выбрать для постановки" : "Выбрать цель",
        disabled: !canChooseCard(detailCard.id),
        onClick: () => chooseCardFromDetail(detailCard.id),
      }
    : undefined;
  const boardStyle = {
    ["--area-pulse-ms" as string]: `${AREA_PULSE_MS}ms`,
    ["--cols" as string]: cols,
    ["--death-ms" as string]: `${DEATH_FADE_MS}ms`,
    ["--move-ms" as string]: `${MOVE_MS}ms`,
    ["--popup-ms" as string]: `${POPUP_TTL_MS}ms`,
    ["--rows" as string]: rows,
    ["--spawn-ms" as string]: `${SPAWN_MS}ms`,
    ["--strike-ms" as string]: `${LUNGE_MS}ms`,
    ["--unit-waited-ms" as string]: `${UNIT_WAITED_MS}ms`,
  } as React.CSSProperties;

  return (
    <div className="battle-v4">
      {dragGhost ? (
        <div
          aria-hidden
          className={`card-drag-ghost${dragGhost.valid ? " valid" : ""}`}
          style={{ left: dragGhost.x, top: dragGhost.y }}
        >
          {dragGhost.name}
        </div>
      ) : null}
      {/* U2: --cols/--rows и тайминги заданы на stage — от них считаются и кап
          поля по высоте вьюпорта, и геометрия слоёв (наследование CSS-переменных). */}
      <section className="battle-stage" style={boardStyle}>
        <div className="battle-topbar">
          <button className="ghost-btn" disabled={busy || isAnimating} onClick={handleStart}>
            Новый бой
          </button>
          <span className="rt-status">{realtime}</span>
        </div>

        <TowerRow
          label="Башни врага"
          onTowerOpen={(tower, source) =>
            openDetail(
              {
                cardId: null,
                fromHand: false,
                fallbackDescription:
                  "Структура линии. Башня не является коллекционной картой, но её текущее здоровье видно в этом описании.",
                fallbackName: "Башня",
                unit: tower,
              },
              source,
            )
          }
          towers={towersOf(enemy?.side ?? "top")}
        />

        <div className="phase-overlay-slot">
          <PhaseOverlay label={currentPhaseLabel} />
        </div>

        <div className="board-v4-wrap">
          <div className="board-v4">
            {Array.from({ length: rows * cols }, (_, i) => {
              const row = Math.floor(i / cols);
              const col = i % cols;
              const unit = unitAt(row, col);
              const plan = plannedAt(row, col);
              const card = selected ? catalog.get(selected) : null;
              const highlight = card && isValidTarget(card, row, col);
              return (
                <button
                  key={i}
                  className={[
                    "cell-v4",
                    highlight ? "ok" : "",
                    inspectedCoverage.has(`${row}:${col}`) ? "inspect-coverage" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  data-row={row}
                  data-col={col}
                  disabled={busy || isAnimating || isFinished}
                  onClick={() => handleCellClick(row, col)}
                >
                  {plan && !unit ? (
                    // U5/W6: план юнита — полупрозрачный синий превью-токен.
                    // pointer-events: none — клик по клетке отменяет план.
                    <PlannedPreview card={catalog.get(plan.card_id)} />
                  ) : null}
                </button>
              );
            })}
          </div>
          <div
            className="unit-layer unit-layer-v4"
            aria-live="polite"
            style={
              {
                ["--cols" as string]: cols,
                ["--rows" as string]: rows,
              } as React.CSSProperties
            }
          >
            {cellPulses.map((pulse) => (
              <CellPulseView key={pulse.key} pulse={pulse} />
            ))}
            {visibleUnits.map((unit) => (
              <UnitToken
                key={unit.id}
                acting={activeEvent?.actor_id === unit.id}
                catalog={catalog}
                dying={dyingIds.includes(unit.id)}
                lunge={lungeByUnit.get(unit.id)}
                spawning={spawningIds.includes(unit.id)}
                inspected={inspected?.unitId === unit.id}
                onInspectorBlur={() => scheduleInspectorClose(unit.id)}
                onInspectorFocus={(target) => {
                  if (lastInspectorPointerTypeRef.current !== "touch") openInspector(unit.id, target);
                }}
                onInspectorPointerDown={rememberInspectorPointer}
                onInspectorPointerEnter={(target) => openInspector(unit.id, target)}
                onInspectorPointerLeave={() => closeInspectorNow(unit.id)}
                onUnitClick={(source) => {
                  // U5: на клетке юнита лежит спелл-план — обычный клик отменяет
                  // его, как на пустой клетке (тот же handleCellClick-путь).
                  if (
                    !busy && !isAnimating && !isFinished &&
                    plannedAt(unit.row, unit.col)
                  ) {
                    handleCellClick(unit.row, unit.col);
                    return;
                  }
                  // При уже выбранном заклинании клик по юниту остаётся выбором
                  // цели; во всех остальных случаях открывается detail (W1d).
                  if (selected && catalog.get(selected)?.card_type === "spell") {
                    handleCellClick(unit.row, unit.col);
                  } else {
                    openDetail({ cardId: unit.card_id, fromHand: false, unit }, source);
                  }
                }}
                showRemainingActions={isAnimating}
                spellTargetable={Boolean(
                  selectedSpell && isValidTarget(selectedSpell, unit.row, unit.col),
                )}
                targeted={activeEvent?.target_id === unit.id}
                unit={unit}
                waitReason={waitReasonByUnit.get(unit.id)}
              />
            ))}
            {planned
              .filter((plan): plan is PlannedSpell => plan.kind === "spell")
              .map((plan) => (
                // U5/W6: спелл-план лежит на занятой клетке, поэтому маркер
                // рисуется поверх юнита в overlay-слое. pointer-events: none —
                // клик проходит к юниту, а тот отменяет план (см. onUnitClick).
                <span
                  key={`plan-spell-${plan.row}-${plan.col}`}
                  aria-hidden="true"
                  className="planned-target"
                  style={
                    {
                      ["--col" as string]: plan.col,
                      ["--row" as string]: plan.row,
                    } as React.CSSProperties
                  }
                >
                  {/* V7: мини-арт заклинания в углу токена цели. */}
                  <span className="planned-target-art">
                    <CardArt
                      cardId={plan.card_id}
                      label={catalog.get(plan.card_id)?.name ?? plan.card_id}
                      rarity="common"
                    />
                  </span>
                  <span className="planned-badge spell">План</span>
                </span>
              ))}
            {spellCasts.map((cast) => (
              // V7: применённое заклинание всплывает артом над клеткой цели.
              <span
                key={cast.key}
                aria-hidden="true"
                className="spell-cast-float"
                style={
                  {
                    ["--col" as string]: cast.col,
                    ["--row" as string]: cast.row,
                    ["--spell-cast-ms" as string]: `${SPELL_CAST_MS}ms`,
                  } as React.CSSProperties
                }
              >
                <span className="spell-cast-float-art">
                  <CardArt
                    cardId={cast.cardId}
                    label={catalog.get(cast.cardId)?.name ?? cast.cardId}
                    rarity="common"
                  />
                </span>
              </span>
            ))}
            {logHighlight ? (
              // V8: «куда была разыграна карта» — кольцо над клеткой цели.
              <span
                aria-hidden="true"
                className="log-target-ring"
                style={
                  {
                    ["--col" as string]: logHighlight.col,
                    ["--row" as string]: logHighlight.row,
                  } as React.CSSProperties
                }
              />
            ) : null}
            {popups.map((popup) => (
              <DamagePopupView
                key={popup.key}
                popup={popup}
                statusLabel={
                  popup.kind === "status"
                    ? statusCatalog.get(popup.statusId ?? "")?.name ?? popup.statusId
                    : undefined
                }
              />
            ))}
          </div>
          {inspected && inspectedUnit ? (
            // V5: у панели нет pointer-обработчиков — она чисто read-only и
            // исчезает вместе с уходом курсора с токена.
            <UnitInspector
              card={inspectedCard ?? undefined}
              placement={inspected.placement}
              showRemainingActions={isAnimating}
              statusCatalog={statusCatalog}
              unit={inspectedUnit}
            />
          ) : null}
        </div>

        <TowerRow
          label="Твои башни"
          onTowerOpen={(tower, source) =>
            openDetail(
              {
                cardId: null,
                fromHand: false,
                fallbackDescription:
                  "Структура линии. Башня не является коллекционной картой, но её текущее здоровье видно в этом описании.",
                fallbackName: "Башня",
                unit: tower,
              },
              source,
            )
          }
          towers={towersOf(viewer?.side ?? "bottom")}
        />

        <div className="mana-bar" aria-label="Мана">
          <div
            style={{ width: `${(availableMana / (visibleMatch.mana_cap || 10)) * 100}%` }}
          />
          <span>
            Мана {availableMana}/{visibleMatch.mana_cap}
          </span>
        </div>
      </section>

      <section className="battle-side">
        <div className="battle-hud">
          <div className={secondsLeft <= 5 ? "turn-timer warning" : "turn-timer"}>
            {secondsLeft}
          </div>
          <div className="turn-plate">
            <strong>Ход {visibleMatch.turn}</strong>
            <span>Рука: {viewer?.hand_count ?? 0}</span>
          </div>
          {/* U3: стопка колоды вместо текста; счётчик убывает по кадрам
              реплея (deck_count в event snapshot), рубашка летит на доборе. */}
          <DeckStack
            count={viewer?.deck_count ?? 0}
            drawing={deckDraws.some((draw) => draw.playerId === viewer?.id)}
          />
        </div>

        <div
          className="hand-v4"
          style={{ ["--deck-draw-ms" as string]: `${DECK_DRAW_MS}ms` } as React.CSSProperties}
        >
          {handEntries.map(({ key, cardId, isPlanned }, index) => {
            const card = catalog.get(cardId);
            const affordable = (card?.cost ?? 0) + plannedCost <= (viewer?.mana ?? 0);
            // V1: добор кладёт карту в конец руки — влёт получает последний
            // экземпляр добранного id, ровно в его настоящем слоте.
            const isDrawnCard =
              justDrawn !== null &&
              cardId === justDrawn.cardId &&
              index === (viewer?.hand ?? []).lastIndexOf(justDrawn.cardId);
            return (
              <button
                key={key}
                className={[
                  "hand-card-v4",
                  selected === cardId ? "active" : "",
                  isPlanned ? "planned" : "",
                  !affordable && !isPlanned ? "poor" : "",
                  isDrawnCard ? "drawn" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                disabled={
                  busy ||
                  isAnimating ||
                  isFinished
                }
                onClick={(event) => handleCardClick(cardId, event.currentTarget)}
                onPointerDown={(e) => handleCardPointerDown(e, cardId)}
                onPointerMove={handleCardPointerMove}
                onPointerUp={handleCardPointerUp}
                onPointerCancel={handleCardPointerCancel}
              >
                <span className="hand-card-art">
                  <CardArt cardId={cardId} label={card?.name ?? cardId} rarity="common" />
                </span>
                <span className="hand-card-name">{card?.name ?? cardId}</span>
                {/* Характеристики видны ВСЕГДА (описание-механика — отдельно, тултип). */}
                {card?.stats ? (
                  <span className="hand-card-stats">
                    <span title="Здоровье">
                      <HeartIcon />
                      {card.stats.hp}
                    </span>
                    <span title="Урон">
                      <BurstIcon />
                      {card.stats.damage}
                    </span>
                    <span title="Атаки за ход">
                      <SwordIcon />
                      {card.stats.attacks_per_turn}
                    </span>
                    <span title="Шаги за ход">
                      <BootIcon />
                      {card.stats.move_steps}
                    </span>
                  </span>
                ) : (
                  <span className="hand-card-stats spell">заклинание</span>
                )}
                <span className="hand-card-cost">{card?.cost ?? "?"}</span>
              </button>
            );
          })}
        </div>

        {selected || planned.length > 0 ? (
          // U5 (§24.1): компактная сводка — что выбрано, что запланировано,
          // стоимость и остаток маны; отмена одного действия и всего плана.
          <section aria-label="План на ход" className="plan-summary">
            {selected ? (
              <p className="plan-summary-selected">
                Выбрано: <b>{catalog.get(selected)?.name ?? selected}</b> — кликни
                подсвеченную клетку
              </p>
            ) : null}
            {planned.length > 0 ? (
              <>
                <header className="plan-summary-head">
                  <strong>План: {planned.length}</strong>
                  <span>
                    стоимость {plannedCost} · останется {availableMana}
                  </span>
                </header>
                <ul className="plan-summary-list">
                  {planned.map((plan, index) => {
                    const card = catalog.get(plan.card_id);
                    return (
                      <li key={`${plan.card_id}-${plan.row}-${plan.col}-${index}`}>
                        <span aria-hidden="true" className={`plan-summary-kind ${plan.kind}`}>
                          {plan.kind === "spell" ? "✨" : "⚔"}
                        </span>
                        <span className="plan-summary-name">
                          {card?.name ?? plan.card_id}
                        </span>
                        <span className="plan-summary-cost">{card?.cost ?? "?"}</span>
                        <button
                          aria-label={`Отменить: ${card?.name ?? plan.card_id}`}
                          className="plan-summary-remove"
                          disabled={busy || isAnimating || isFinished}
                          onClick={() =>
                            setPlanned((cur) => cur.filter((_, i) => i !== index))
                          }
                        >
                          ×
                        </button>
                      </li>
                    );
                  })}
                </ul>
                <button
                  className="ghost-btn plan-summary-clear"
                  disabled={busy || isAnimating || isFinished}
                  onClick={() => {
                    setPlanned([]);
                    setSelected(null);
                  }}
                >
                  Очистить план
                </button>
              </>
            ) : null}
          </section>
        ) : null}

        <button
          className="resolve-btn"
          disabled={busy || isAnimating || isFinished}
          onClick={handleResolve}
        >
          {busy ? "Ход идёт..." : "Завершить ход"}
        </button>

        {/* V8: журнал розыгрышей обеих сторон (серверный match.log в v4 пуст).
            Куда легла карта — подсветкой клетки на ховере/тапе записи. */}
        <ul aria-label="Лог розыгрышей" className="battle-log play-log">
          {playLog.length === 0 ? (
            <li className="play-log-empty">Розыгрышей пока не было</li>
          ) : null}
          {playLog.map((entry) => (
            <li key={entry.key}>
              <button
                className={`play-log-entry${logHighlight?.key === entry.key ? " active" : ""}`}
                onClick={() => flashLogHighlight(entry)}
                onPointerEnter={(event) => {
                  if (event.pointerType !== "touch") {
                    setLogHighlight({ key: entry.key, row: entry.row, col: entry.col });
                  }
                }}
                onPointerLeave={() =>
                  setLogHighlight((cur) => (cur?.key === entry.key ? null : cur))
                }
                type="button"
              >
                <span aria-hidden="true" className={`play-log-side ${entry.mine ? "mine" : "enemy"}`} />
                <span className="play-log-turn">х{entry.turn}</span>
                <span aria-hidden="true" className="play-log-kind">
                  {entry.kind === "spell" ? "✨" : "⚔"}
                </span>
                <span className="play-log-name">
                  {catalog.get(entry.cardId)?.name ?? entry.cardId}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      {isFinished && !resultDismissed ? (
        <ResultOverlay match={visibleMatch} onClose={() => setResultDismissed(true)} />
      ) : null}
      {detail ? (
        <CardDetail
          card={detailCard}
          detailAction={detailAction}
          fallbackDescription={detail.fallbackDescription}
          fallbackName={detail.fallbackName}
          onClose={closeDetail}
          statusCatalog={statuses}
          unit={detail.unit}
        />
      ) : null}
    </div>
  );
}

function waitForRealtimeResolution(
  waiterRef: React.MutableRefObject<((payload: CombatResponse) => void) | null>,
): Promise<CombatResponse | null> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (payload: CombatResponse | null) => {
      if (settled) return;
      settled = true;
      waiterRef.current = null;
      resolve(payload);
    };
    waiterRef.current = finish;
    window.setTimeout(() => finish(null), 750);
  });
}

function TowerRow({
  label,
  onTowerOpen,
  towers,
}: {
  label: string;
  onTowerOpen: (tower: CombatUnit, source: HTMLButtonElement) => void;
  towers: CombatUnit[];
}) {
  return (
    <div className="tower-row" aria-label={label}>
      {towers.map((t) => (
        <button
          key={t.id}
          aria-label={`Подробнее: башня, здоровье ${Math.max(0, t.current_hp)}`}
          className={`tower${t.current_hp <= 0 ? " dead" : ""}`}
          onClick={(event) => onTowerOpen(t, event.currentTarget)}
          type="button"
        >
          <span className="tower-hp">{Math.max(0, t.current_hp)}</span>
          <span className="tower-bar">
            <span style={{ width: `${Math.max(0, (t.current_hp / t.max_hp) * 100)}%` }} />
          </span>
        </button>
      ))}
    </div>
  );
}

function PhaseOverlay({ label }: { label: string | null }) {
  const [displayedLabel, setDisplayedLabel] = React.useState(label);

  React.useEffect(() => {
    if (label) {
      setDisplayedLabel(label);
      return undefined;
    }
    if (!displayedLabel) return undefined;
    const timer = window.setTimeout(
      () => setDisplayedLabel(null),
      PHASE_OVERLAY_FADE_MS,
    );
    return () => window.clearTimeout(timer);
  }, [displayedLabel, label]);

  if (!displayedLabel) return null;
  return (
    <div
      className={`iteration-overlay${label ? "" : " exiting"}`}
      role="status"
      style={
        {
          ["--phase-fade-ms" as string]: `${PHASE_OVERLAY_FADE_MS}ms`,
        } as React.CSSProperties
      }
    >
      <span key={displayedLabel}>{displayedLabel}</span>
    </div>
  );
}

function UnitToken({
  acting,
  unit,
  catalog,
  dying,
  inspected,
  lunge,
  onInspectorBlur,
  onInspectorFocus,
  onInspectorPointerDown,
  onInspectorPointerEnter,
  onInspectorPointerLeave,
  onUnitClick,
  showRemainingActions,
  spawning,
  spellTargetable,
  targeted,
  waitReason,
}: {
  acting: boolean;
  unit: CombatUnit;
  catalog: Map<string, CombatCatalogCard>;
  dying: boolean;
  inspected: boolean;
  lunge?: LungeEffect;
  onInspectorBlur: () => void;
  onInspectorFocus: (target: HTMLElement) => void;
  onInspectorPointerDown: (pointerType: string) => void;
  onInspectorPointerEnter: (target: HTMLElement) => void;
  onInspectorPointerLeave: () => void;
  onUnitClick: (source: HTMLElement) => void;
  showRemainingActions: boolean;
  spawning: boolean;
  spellTargetable: boolean;
  targeted: boolean;
  waitReason?: NonNullable<CombatEvent["wait_reason"]>;
}) {
  const card = unit.card_id ? catalog.get(unit.card_id) : null;
  return (
    <span
      className={[
        "unit-token",
        "unit-token-v4",
        lunge ? "lunging" : "",
        dying ? "dying" : "",
        spawning ? "spawning" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-describedby={inspected ? "unit-inspector" : undefined}
      aria-label={`Инспектор юнита: ${card?.name ?? "неизвестный юнит"}`}
      data-inspector-unit-id={unit.id}
      data-unit-id={unit.id}
      onBlur={onInspectorBlur}
      onClick={(event) => onUnitClick(event.currentTarget)}
      onFocus={(event) => onInspectorFocus(event.currentTarget)}
      onPointerDown={(event) => onInspectorPointerDown(event.pointerType)}
      onPointerEnter={(event) => {
        if (event.pointerType !== "touch") onInspectorPointerEnter(event.currentTarget);
      }}
      onPointerLeave={onInspectorPointerLeave}
      tabIndex={0}
      style={
        {
          ["--col" as string]: unit.col,
          ["--row" as string]: unit.row,
        } as React.CSSProperties
      }
    >
      <span
        className={`unit-token-inner${lunge ? " striking" : ""}`}
        style={
          lunge
            ? ({
                ["--lunge-x" as string]: `${lunge.dx}%`,
                ["--lunge-y" as string]: `${lunge.dy}%`,
              } as React.CSSProperties)
            : undefined
        }
      >
        <span
          className={[
            "unit-v4",
            unit.side,
            `stance-${unit.stance}`,
            acting ? "acting" : "",
            targeted ? "targeted" : "",
            waitReason ? "waiting" : "",
            inspected ? "inspected" : "",
            spellTargetable ? "spell-target" : "",
          ]
            .filter(Boolean)
            .join(" ")}
        >
          <span className="unit-v4-art">
            <CardArt cardId={unit.card_id ?? ""} label={card?.name ?? "?"} rarity="common" />
          </span>
          <span className="unit-v4-stat unit-v4-steps" title="Шаги за ход">
            <BootIcon />
            {showRemainingActions ? unit.remaining_steps : unit.move_steps}
          </span>
          <span className="unit-v4-stat unit-v4-attacks" title="Атаки за ход">
            <SwordIcon />
            {showRemainingActions ? unit.remaining_attacks : unit.attacks_per_turn}
          </span>
          <span className="unit-v4-stat unit-v4-dmg" title="Урон">
            <BurstIcon />
            {unit.damage}
          </span>
          <span className="unit-v4-stat unit-v4-hp" title="Здоровье">
            {/* Только текущее HP: потолка нет (Q4), лечение может поднять выше
                базы, и "6/2" читалось бы как поломка. Максимум/база — в карточке. */}
            <HeartIcon />
            {Math.max(0, unit.current_hp)}
          </span>
          <span
            aria-label={stanceAria(unit)}
            className="unit-v4-stance"
            title={stanceTitle(unit)}
          >
            <span aria-hidden="true">{unit.stance === "defense" ? "🛡" : "⚔"}</span>
            {/* V6: остаток ходов конечной стойки — как HP на сердечке. */}
            {unit.stance_turns_left !== null ? (
              <span className="unit-v4-stance-count">{unit.stance_turns_left}</span>
            ) : null}
          </span>
          {unit.statuses.length > 0 ? (
            <span className="unit-v4-status">
              {unit.statuses.map((s) => s.stacks).join("·")}
            </span>
          ) : null}
        </span>
        {waitReason ? <span className="unit-wait-badge">{unitWaitLabel(waitReason)}</span> : null}
      </span>
    </span>
  );
}

function DeckStack({ count, drawing }: { count: number; drawing: boolean }) {
  // U3: только публичный deck_count — состав и порядок колоды сюда не приходят.
  return (
    <div
      aria-label={`Колода: осталось карт — ${count}`}
      className={`deck-stack${count === 0 ? " empty" : ""}`}
      role="img"
      style={{ ["--deck-draw-ms" as string]: `${DECK_DRAW_MS}ms` } as React.CSSProperties}
    >
      {drawing ? <span aria-hidden="true" className="deck-draw-fly" /> : null}
      <strong>{count}</strong>
      <span>колода</span>
    </div>
  );
}

function PlannedPreview({ card }: { card?: CombatCatalogCard }) {
  // U5/W6: превью строится из данных каталога, а не из живого юнита — у него
  // нет unit id, оно не попадает в visibleUnits и в анимационный дедуп.
  return (
    <span className="planned-preview">
      <span className="planned-preview-art">
        <CardArt cardId={card?.id ?? ""} label={card?.name ?? "?"} rarity="common" />
      </span>
      {card?.stats ? (
        <span className="planned-preview-stats">
          <span title="Здоровье">
            <HeartIcon />
            {card.stats.hp}
          </span>
          <span title="Урон">
            <BurstIcon />
            {card.stats.damage}
          </span>
        </span>
      ) : null}
      <span className="planned-badge">План</span>
    </span>
  );
}

function coverageCellsFor(
  unit: CombatUnit,
  card: CombatCatalogCard,
  rows: number,
  cols: number,
): Set<string> {
  const pattern = unit.stance === "defense" ? card.coverage_defense : card.coverage_attack;
  const direction = unit.side === "top" ? 1 : -1;
  return new Set(
    (pattern ?? [])
      .map(({ forward, col }) => ({ row: unit.row + forward * direction, col: unit.col + col }))
      .filter(({ row, col }) => row >= 0 && row < rows && col >= 0 && col < cols)
      .map(({ row, col }) => `${row}:${col}`),
  );
}

function UnitInspector({
  card,
  placement,
  showRemainingActions,
  statusCatalog,
  unit,
}: {
  card: CombatCatalogCard | undefined;
  placement: InspectorPlacement;
  showRemainingActions: boolean;
  statusCatalog: Map<string, CombatStatusDefinition>;
  unit: CombatUnit;
}) {
  const placementStyle = placement.side === "bottom"
    ? undefined
    : { left: placement.left, top: placement.top };
  const stanceLabel = stanceTitle(unit);
  const stats = [
    { icon: <HeartIcon />, label: "Здоровье", value: Math.max(0, unit.current_hp) },
    { icon: <BurstIcon />, label: "Урон", value: unit.damage },
    {
      icon: <BootIcon />,
      label: showRemainingActions ? "Шаги осталось" : "Шаги",
      value: showRemainingActions ? unit.remaining_steps : unit.move_steps,
    },
    {
      icon: <SwordIcon />,
      label: showRemainingActions ? "Атаки осталось" : "Атаки",
      value: showRemainingActions ? unit.remaining_attacks : unit.attacks_per_turn,
    },
  ];

  return (
    <aside
      className={`unit-inspector ${placement.side}`}
      id="unit-inspector"
      role="region"
      aria-label={`Инспектор: ${card?.name ?? "юнит"}`}
      style={placementStyle}
    >
      <div className="unit-inspector-heading">
        <strong>{card?.name ?? "Юнит"}</strong>
        <span className={`unit-inspector-stance ${unit.stance}`}>
          {unit.stance === "defense" ? "🛡" : "⚔"} {stanceLabel}
        </span>
      </div>
      <dl className="unit-inspector-stats">
        {stats.map(({ icon, label, value }) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>
              {icon}
              {value}
            </dd>
          </div>
        ))}
      </dl>
      <section className="unit-inspector-statuses" aria-label="Статус-эффекты">
        <strong>Статусы</strong>
        {unit.statuses.length ? (
          <ul>
            {unit.statuses.map((status) => {
              const definition = statusCatalog.get(status.id);
              const duration = status.ttl !== null
                ? ` · ещё ходов: ${status.ttl}`
                : definition?.decay === "permanent"
                  ? " · постоянно"
                  : "";
              return (
                <li key={status.id}>
                  <span>
                    <b>{definition?.name ?? status.id}</b>
                    {` · стаков: ${status.stacks}${duration}`}
                  </span>
                  {definition ? <small>{definition.description}</small> : null}
                </li>
              );
            })}
          </ul>
        ) : (
          <span className="muted">Нет</span>
        )}
      </section>
    </aside>
  );
}

function stanceTitle(unit: Pick<CombatUnit, "stance" | "stance_turns_left">): string {
  const base = unit.stance === "defense" ? "Защита" : "Атака";
  return unit.stance_turns_left !== null
    ? `${base} · ещё ходов: ${unit.stance_turns_left}`
    : base;
}

function stanceAria(unit: Pick<CombatUnit, "stance" | "stance_turns_left">): string {
  return `Стойка: ${stanceTitle(unit).toLowerCase()}`;
}

function unitWaitLabel(reason: NonNullable<CombatEvent["wait_reason"]>) {
  switch (reason) {
    case "defense_no_target":
      return "🛡 Защита: нет цели";
    case "attack_no_target":
      return "⚔ Атака: нет цели";
    case "path_blocked":
      return "Путь заблокирован";
    case "no_action_budget":
      return "Нет действий";
  }
}

function DamagePopupView({
  popup,
  statusLabel,
}: {
  popup: BattlePopup;
  statusLabel?: string;
}) {
  const positionStyle = {
    ["--col" as string]: popup.col,
    ["--row" as string]: popup.row,
  } as React.CSSProperties;
  if (popup.kind === "status") {
    // V9: наложение статуса всплывает над целью текстом («Яд +3»).
    return (
      <span className="damage-popup status" style={positionStyle}>
        <span className="damage-popup-text">
          {statusLabel}
          {popup.amount > 0 ? ` +${popup.amount}` : ""}
        </span>
      </span>
    );
  }
  return (
    <span className={`damage-popup ${popup.kind}`} style={positionStyle}>
      {popup.kind === "damage" ? <BurstIcon /> : <HeartIcon />}
      <span className="damage-popup-text">
        {popup.kind === "damage" ? "−" : "+"}
        {popup.amount}
      </span>
    </span>
  );
}

function CellPulseView({ pulse }: { pulse: CellPulse }) {
  return (
    <span
      aria-hidden="true"
      className={`cell-effect-pulse ${pulse.kind}`}
      style={
        {
          ["--col" as string]: pulse.col,
          ["--row" as string]: pulse.row,
        } as React.CSSProperties
      }
    />
  );
}

function ResultOverlay({ match, onClose }: { match: CombatMatch; onClose: () => void }) {
  if (match.result.status === "expired") {
    return (
      <div className="result-backdrop" onClick={onClose}>
        <section className="result-panel" onClick={(e) => e.stopPropagation()}>
          <strong>Матч завершён</strong>
          <span>Правила боя обновились — начни новый бой.</span>
          <button onClick={onClose}>Понятно</button>
        </section>
      </div>
    );
  }
  const viewer = match.players.find((p) => p.id === match.viewer_id);
  const didWin = viewer != null && match.result.winner_team === viewer.team;
  return (
    <div className="result-backdrop" onClick={onClose}>
      <section className="result-panel" onClick={(e) => e.stopPropagation()}>
        <strong>{didWin ? "Победа" : "Поражение"}</strong>
        <span>{didWin ? "Башни врага пали." : "Твои башни пали."}</span>
        <b>+{match.result.reward_coins} монет</b>
        <button onClick={onClose}>Забрать</button>
      </section>
    </div>
  );
}
