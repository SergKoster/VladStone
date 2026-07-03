/**
 * Stat icons used on cards, board units and combat popups.
 *
 * These are placeholder glyphs drawn with `currentColor` so colour is driven by
 * CSS. To swap in generated artwork later, replace the `<path>` data in each
 * component (keep `currentColor` for theming), or point the component at an
 * imported SVG/PNG. The mapping the rest of the app uses is `STAT_ICONS` below,
 * so individual call sites never hard-code an icon.
 */
import React from "react";

type IconProps = { className?: string };

function Svg({ className, children }: React.PropsWithChildren<IconProps>) {
  return (
    <svg
      aria-hidden="true"
      className={className ? `ico ${className}` : "ico"}
      focusable="false"
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
    >
      {children}
    </svg>
  );
}

/** HP — heart. */
export function HeartIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path
        fill="currentColor"
        d="M12 21s-6.7-4.35-9.33-8.07C1.1 10.5 1.7 7 4.6 5.7 6.85 4.7 9.2 5.5 12 8.2c2.8-2.7 5.15-3.5 7.4-2.5 2.9 1.3 3.5 4.8 1.93 7.23C18.7 16.65 12 21 12 21z"
      />
    </Svg>
  );
}

/** Damage — explosion burst. */
export function BurstIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path
        fill="currentColor"
        d="M12 1.5l2.4 5.1 5.1-2.1-2.1 5.1 5.1 2.4-5.1 2.4 2.1 5.1-5.1-2.1L12 22.5l-2.4-5.1-5.1 2.1 2.1-5.1L1.5 11.5l5.1-2.4-2.1-5.1 5.1 2.1z"
      />
    </Svg>
  );
}

/** Move steps — boot. */
export function BootIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path
        fill="currentColor"
        d="M7 3h3.2v8.2l6.3 2.3a3.5 3.5 0 0 1 2.3 3.3V20a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"
      />
    </Svg>
  );
}

/** Number of attacks — sword. */
export function SwordIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path
        fill="currentColor"
        d="M19.8 3.5l.7.7-8.4 8.4 1.3 1.3-1.4 1.4-1.3-1.3-1.8 1.8 1.4 1.4-1.4 1.4-1.4-1.4-1.5 1.5-1.6-.2-.2-1.6 1.5-1.5-1.4-1.4 1.4-1.4 1.4 1.4 1.8-1.8-1.3-1.3 1.4-1.4 1.3 1.3 8.4-8.4z"
      />
    </Svg>
  );
}

/** Attack range — target. */
export function RangeIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <circle cx="12" cy="12" fill="none" r="8.5" stroke="currentColor" strokeWidth="2" />
      <circle cx="12" cy="12" fill="none" r="4" stroke="currentColor" strokeWidth="2" />
      <circle cx="12" cy="12" fill="currentColor" r="1.6" />
    </Svg>
  );
}

/** Mana cost — droplet. */
export function ManaIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path fill="currentColor" d="M12 2.5c3.8 4.8 6 8 6 11a6 6 0 0 1-12 0c0-3 2.2-6.2 6-11z" />
    </Svg>
  );
}

/** Canonical icon per stat so call sites stay icon-agnostic. */
export const STAT_ICONS = {
  cost: ManaIcon,
  hp: HeartIcon,
  damage: BurstIcon,
  range: RangeIcon,
  steps: BootIcon,
  attacks: SwordIcon,
} as const;
