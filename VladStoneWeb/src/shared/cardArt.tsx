/**
 * Card / unit artwork.
 *
 * The art is square (1:1) and built from two layers:
 *   1. a rarity background (solid colour for now, swap for a nicer gradient
 *      later) from `src/assets/rarities/<rarity>.png`;
 *   2. the card's icon on top, a transparent PNG named after the card id in
 *      `src/assets/cards/<card_id>.png` (any of png/jpg/jpeg/webp/svg).
 *
 * Both layers are picked up automatically at build time (no registration). The
 * exact same composition is reused on the card face and on the board token.
 * Until a card icon exists, the card's initials are shown over the rarity tint.
 */
import React from "react";

import { type Rarity } from "../api";

const iconModules = import.meta.glob("../assets/cards/*.{png,jpg,jpeg,webp,svg}", {
  eager: true,
  query: "?url",
  import: "default",
}) as Record<string, string>;

const rarityModules = import.meta.glob("../assets/rarities/*.{png,jpg,jpeg,webp,svg}", {
  eager: true,
  query: "?url",
  import: "default",
}) as Record<string, string>;

function byBaseName(modules: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [path, url] of Object.entries(modules)) {
    const name = path.split("/").pop()!.replace(/\.[^.]+$/, "");
    out[name] = url;
  }
  return out;
}

const ICON_BY_ID = byBaseName(iconModules);
const RARITY_BG = byBaseName(rarityModules);

export function hasCardArt(cardId: string): boolean {
  return cardId in ICON_BY_ID;
}

function initials(label: string): string {
  const words = label.trim().split(/\s+/).filter(Boolean);
  if (!words.length) {
    return "?";
  }
  if (words.length === 1) {
    return words[0].slice(0, 2).toUpperCase();
  }
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

export function CardArt({
  cardId,
  label,
  rarity,
}: {
  cardId: string;
  label: string;
  rarity: Rarity;
}) {
  const iconUrl = ICON_BY_ID[cardId];
  const bgUrl = RARITY_BG[rarity] ?? RARITY_BG.common;
  return (
    // draggable=false: images are natively draggable, and that browser drag
    // (ghost image + no-drop cursor) swallows the pointer events our
    // hand-to-board drag-n-drop is built on when grabbing a card by its art.
    <div className="card-art" data-rarity={rarity}>
      {bgUrl ? (
        <img aria-hidden="true" alt="" className="card-art-bg" draggable={false} src={bgUrl} />
      ) : null}
      {iconUrl ? (
        <img alt="" className="card-art-icon" draggable={false} src={iconUrl} />
      ) : (
        <span aria-hidden="true" className="card-art-glyph">
          {initials(label)}
        </span>
      )}
    </div>
  );
}
