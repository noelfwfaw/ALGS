"""Page graph of 嘟嘟脸恶作剧 (Trickcal).

Only one page is declared: the lobby. The login flow is a button-driven chain
(`TrickcalLogin`), not a page graph, because the exported card spec has no
`exits` at all - every `ui_goto()` edge would be missing and `ui_ensure()`
would wait 60 seconds on a page it can never reach.

`page_main` is checked with `E_7_1`, the row of green lobby buttons at
(20, 600)-(1260, 710). Offline matrix on the 7 exported frames (2026-11-11):
1.000 on the lobby, at most 0.117 on the title / sign-in / reward / return /
announcement screens, so the 0.85 default leaves plenty of margin. Those
screens cover the lobby behind a popup, and the template does not match
through them.

When a second page is added:

1. Declare it on ONE line as `page_xxx = Page(CHECK_BUTTON)`; the name is
   read from that source line.
2. Add `page_xxx.link(button=..., destination=...)` here and the reverse
   link explicitly - links are one-way.
3. Add it to `TrickcalUI.pages`, otherwise `ui_get_current_page()` never
   sees it (hard rule 61).
"""

from module.trickcal.assets import E_7_1
from module.ui.page import Page

page_main = Page(E_7_1)
