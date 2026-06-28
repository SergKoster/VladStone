import React from "react";

import { type CollectionCard, type Placement } from "../../api";

export function useBattleUiState() {
  const [selectedCard, setSelectedCard] = React.useState<CollectionCard | null>(null);
  const [placements, setPlacements] = React.useState<Placement[]>([]);
  const [battleMessage, setBattleMessage] = React.useState("");
  const [secondsLeft, setSecondsLeft] = React.useState(30);
  const [isTimerRunning, setIsTimerRunning] = React.useState(false);
  const [isResolving, setIsResolving] = React.useState(false);
  const [resultDismissed, setResultDismissed] = React.useState(false);

  return {
    battleMessage,
    isResolving,
    isTimerRunning,
    placements,
    resultDismissed,
    secondsLeft,
    selectedCard,
    setBattleMessage,
    setIsResolving,
    setIsTimerRunning,
    setPlacements,
    setResultDismissed,
    setSecondsLeft,
    setSelectedCard,
  };
}
