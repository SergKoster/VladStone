# Card artwork

Drop square (1:1) card art here, named after the card id:

```
src/assets/cards/test_bruiser.png
src/assets/cards/test_ranger.png
```

Supported extensions: `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`.

Files are picked up automatically (via `import.meta.glob` in
`src/shared/cardArt.tsx`) — no registration step. Until a matching file exists,
the card shows a coloured placeholder with the card's initials.

The same image is reused on the card face (hand/collection) and on the unit
token on the board, so keep it square and readable when small.
