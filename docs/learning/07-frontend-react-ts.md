# Модуль 7. Фронтенд: TypeScript, React 19, Vite

> Самый большой модуль — это фактически вторая профессия. Цель для
> фулл-стэка: уверенно читать весь `VladStoneWeb/`, самостоятельно делать
> средние фичи UI и понимать, как работает наша анимационная машина.

## Что нужно знать на выходе

- **JS/TS-база**: замыкания, промисы, `async/await`, модули ESM; TypeScript —
  типы, интерфейсы, дженерики, union types, narrowing.
- **React**: компоненты как функции, props/state, рендер как функция от
  состояния, хуки (`useState`, `useEffect`, `useRef`, `useMemo`,
  `useCallback`), подъём состояния, ключи списков. В React 19 компилятор сам
  мемоизирует — но понимать, зачем мемоизация, всё равно нужно.
- **Vite**: dev-сервер, HMR, сборка (`tsc -b && vite build`),
  `import.meta.glob` (наш авто-подхват артов карт).
- **CSS**: flexbox/grid, CSS-переменные, transform/transition/animation — вся
  наша боёвка анимируется CSS-ами, синхронизированными с серверными событиями.
- Работа с сервером без библиотек: `fetch`, куки, WebSocket в браузере.

## Ресурсы

1. [learn.javascript.ru](https://learn.javascript.ru/) — лучший учебник JS,
   на русском. База перед всем остальным (части 1–2 выборочно).
2. [TypeScript Handbook](https://www.typescriptlang.org/docs/handbook/intro.html) —
   официальный учебник TS; практиковать в
   [TS Playground](https://www.typescriptlang.org/play).
3. [react.dev: Learn React](https://react.dev/learn) — **главный ресурс**;
   официальный учебник с интерактивными примерами, покрывает мышление
   «UI = функция от состояния».
4. [Документация Vite](https://vitejs.dev/guide/) — короткая, прочитать Guide.
5. [MDN: CSS animations](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_animations) +
   [flexbox](https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/CSS_layout/Flexbox) —
   по мере надобности.
6. [roadmap.sh/react](https://roadmap.sh/react) — сверка покрытия тем.
7. Опционально: [React 19 гайд по новым фичам](https://medium.com/@sulmanahmed135/react-19-new-features-a-comprehensive-guide-for-react-js-typescript-developers-715d6542dd0d).

## Где это у нас

- `VladStoneWeb/src/features/battle/BattleV4.tsx` — сердце UI боя (самый
  сложный файл; читать в конце модуля).
- `useTurnPlayback.ts`, `turnPlayback.ts` — покадровый реплей серверных
  событий: применение снапшотов, тайминги.
- `battleAnimations.ts` + `animationConfig.ts` — анимации и их тайминги.
- `src/shared/Card.tsx`, `cardArt.tsx`, `icons.tsx`, `apiClient.ts` — общие
  кирпичи; `cardArt.tsx` — живой пример `import.meta.glob`.
- `src/features/collection/`, `dashboard/`, `auth/` — более простые фичи,
  с них начинать чтение.
- `package.json`, `vite.config.ts`, `tsconfig*.json` — сборка.

## Практика (по нарастающей)

1. Пройти первые главы react.dev, параллельно читая `Collection.tsx` —
   находить в нём каждую изученную концепцию (state, список с key, условный
   рендер).
2. Написать с нуля мини-приложение на Vite + React + TS вне проекта:
   список карт с фильтром по редкости (данные — захардкоженный массив).
   Это закрепит create-project → компоненты → state → рендер списка.
3. Трассировка анимации: выбрать одно боевое событие (например, атаку) и
   пройти путь: WS-сообщение → turnPlayback → изменение state → CSS-класс →
   визуальный выпад. Выписать цепочку.
4. Сделать маленькую UI-правку в песочной ветке (например, изменить подсветку
   клетки) и убедиться через dev-сервер, что HMR подхватывает.
5. Прочитать `useTurnPlayback.ts` целиком с разбором (с Claude) — это экзамен
   модуля: там хуки, тайминги, watchdog и работа с сервером в одном месте.

## Вопросы для самопроверки

- Почему нельзя мутировать state напрямую и что делает `setState`?
- Когда срабатывает `useEffect` и зачем ему массив зависимостей?
- Почему анимации строятся от серверных событий, а не «фронт сам догадался»?
  Что сломается, если фронт начнёт предсказывать исходы?
- Что делает `tsc -b` в нашем `npm run build`, если код запускает Vite?
