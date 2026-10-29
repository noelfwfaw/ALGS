"""Coupon codes (兑换码) shared by the games of this fork.

Three pieces, none of them tied to one game:

- `gamekee` - the list, fetched from GameKee's JSON endpoint. Same endpoint for
  every game, only the `game-alias` header and the wiki page differ.
- `codes` - the local ledger, one JSON file per game under `config/state/`.
- `text` - OCR of the Chinese the games print back.

What stays in each game's package is the part that is really about that game:
walking its menus, typing into its input, reading its answer.
"""
