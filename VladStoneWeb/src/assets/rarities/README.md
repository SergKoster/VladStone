# Rarity backgrounds

One square image per rarity, used as the card/unit art background behind the
(transparent) card icon:

```
common.png      grey
uncommon.png    green
rare.png        blue
epic.png        purple
legendary.png   yellow
```

These are flat solid-colour placeholders for now — replace them with nicer
gradient art when ready (keep the same file names). Picked up automatically via
`import.meta.glob` in `src/shared/cardArt.tsx`.
