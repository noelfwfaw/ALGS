"""Pages of starsavior.

Every page is identified by a unique button, and `link()` records "click this
-> go there"; `UI.ui_goto()` then finds the shortest path from wherever the game
currently is.
"""

from module.ui.page import Page
