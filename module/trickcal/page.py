"""Page graph of 嘟嘟脸恶作剧 (Trickcal).

Only one page is declared: the lobby. The login flow is a button-driven chain
(`TrickcalLogin`), not a page graph, because the exported card spec has no
`exits` at all - every `ui_goto()` edge would be missing and `ui_ensure()`
would wait 60 seconds on a page it can never reach.

`page_main` is checked with `E_7_1`, the 「剧院」 lobby button at
(790, 600)-(920, 715). The first local check point cropped the whole bottom
button row, which also contains the animated character: a real lobby frame
scored only 0.72 on it and the boot loop timed out. The 11-frame matrix now
reads 1.000 on the exported lobby, 0.99 on a real lobby frame and at most
0.31 on the title / sign-in / reward / return / announcement screens. It is a
fixed UI icon: no player name, level or animated art in the template.

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
