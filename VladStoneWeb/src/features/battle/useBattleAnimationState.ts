import React from "react";

import { type CombatEvent } from "../../api";

export function useBattleAnimationState() {
  const [isAnimating, setIsAnimating] = React.useState(false);
  const [activeEvent, setActiveEvent] = React.useState<CombatEvent | null>(null);

  return {
    activeEvent,
    isAnimating,
    setActiveEvent,
    setIsAnimating,
  };
}
