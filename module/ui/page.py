import traceback

"""
Generic game page graph.

A Page is a game screen identified by a unique check button. Pages are linked
into a graph by `link(button, destination)`, and `Page.init_connection()` builds
an A* route to the destination at runtime, so a script can start from almost any
screen and still reach the target page.

Game specific page instances are defined in the game package, not here.
"""


class Page:
    # Key: str, page name like "page_main"
    # Value: Page, page instance
    all_pages = {}

    @classmethod
    def clear_connection(cls):
        for page in cls.all_pages.values():
            page.parent = None

    @classmethod
    def init_connection(cls, destination):
        """
        Initialize an A* path finding among pages.

        Args:
            destination (Page):
        """
        cls.clear_connection()

        visited = [destination]
        visited = set(visited)
        while 1:
            new = visited.copy()
            for page in visited:
                for link in cls.iter_pages():
                    if link in visited:
                        continue
                    if page in link.links:
                        link.parent = page
                        new.add(link)
            if len(new) == len(visited):
                break
            visited = new

    @classmethod
    def iter_pages(cls):
        return cls.all_pages.values()

    @classmethod
    def iter_check_buttons(cls):
        for page in cls.all_pages.values():
            if isinstance(page.check_button, (list, tuple)):
                for button in page.check_button:
                    yield button
            else:
                yield page.check_button

    def __init__(self, check_button):
        """
        Args:
            check_button (Button, list[Button]): A button that only appears on
                this page, or several of them, any of which identifies it.
        """
        self.check_button = check_button
        self.links = {}
        (filename, line_number, function_name, text) = traceback.extract_stack()[-2]
        self.name = text[:text.find('=')].strip()
        self.parent = None
        Page.all_pages[self.name] = self

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return self.name

    def link(self, button, destination):
        """
        Args:
            button (Button): Click this button to go to destination.
            destination (Page): Destination page.
        """
        self.links[destination] = button
