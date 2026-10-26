from module.base.base import ModuleBase
from module.base.button import Button
from module.base.decorator import run_once
from module.base.timer import Timer
from module.exception import GameNotRunningError, GamePageUnknownError
from module.logger import logger
from module.ocr.ocr import Ocr
from module.ui.page import Page

"""
Generic UI navigation built on the `Page` graph.

Everything here is game independent: pages are registered by declaring
`Page(check_button)` in your game package, and linked with `page.link(...)`.
Subclasses only need to override `page_main` with their own home page and may
override `ui_additional()` to handle their own popups.
"""


class UI(ModuleBase):
    ui_current: Page
    # Home page of the current game, set by subclass
    page_main: Page = None

    def ui_page_appear(self, page, offset=(30, 30), interval=0):
        """
        Check whether the given page is on screen.

        A page may carry more than one check point, and is on screen if any of
        them matches. That is for pages whose single obvious check point is a
        small icon that the game redraws with a badge or a highlight, where one
        check point fails now and then while another stays still.

        Args:
            page (Page):
            offset:
            interval:

        Returns:
            bool: If the given page appears.
        """
        if page.check_button is None:
            return False

        if isinstance(page.check_button, (list, tuple)):
            for button in page.check_button:
                if self.appear(button, offset=offset, interval=interval):
                    return True
            return False

        return self.appear(page.check_button, offset=offset, interval=interval)

    def is_in_main(self, offset=(30, 30), interval=0):
        """
        Returns:
            bool: If in the home page.
        """
        if self.page_main is None:
            raise GamePageUnknownError('page_main is not set, please define it in your game UI class')
        return self.ui_page_appear(self.page_main, offset=offset, interval=interval)

    def ui_any_page_appear(self, offset=(30, 30)):
        """
        Check every registered page.

        Used when the game may already be past its boot screens, where the only
        thing that matters is "am I inside the game at all".

        Args:
            offset:

        Returns:
            bool: If any registered page appears.
        """
        if not self.device.has_cached_image:
            self.device.screenshot()

        for page in Page.iter_pages():
            if page.check_button is None:
                continue
            if self.ui_page_appear(page, offset=offset):
                logger.attr('UI', page.name)
                return True
        return False

    def appear_settled(self, button, timeout=3, skip_first_screenshot=True, offset=None):
        """
        Wait until a check point appears, tolerating page transitions.

        `ui_page_appear()` matches a template with an offset, which is loose
        enough to fire in the middle of a page switch, while the new page is
        still fading in. A color check point (`appear(button, offset=None)`)
        compares the mean color of its area, and a half drawn frame is dimmer,
        so it does not match. Acting on the screenshot `ui_ensure()` returns
        on therefore reads "nothing here" and silently skips the whole task.

        Use this instead of `appear()` for the first check after a page switch.
        It leaves a settled screenshot in `device.image`, so the following state
        loop can start with `skip_first_screenshot=True`.

        Args:
            button (Button): Check point.
            timeout (int, float): Seconds to wait before giving up.
            skip_first_screenshot (bool): Reuse the current image at first try.
            offset (tuple, int, None): Template match offset. None matches by
                mean color, which is cheaper but needs a page that is already
                drawn and not covered by a modal.

        Returns:
            bool: If the check point appears.
        """
        button = self.ensure_button(button)
        timeout = Timer(timeout).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(button, offset=offset):
                return True
            if timeout.reached():
                logger.warning(f'Wait too long for {button.name}')
                return False

    def ensure_button_execute(self, button, offset=0):
        """
        Args:
            button (Button, callable):

        Returns:
            bool: If appear.
        """
        if isinstance(button, Button) and self.appear(button, offset=offset):
            return True
        elif callable(button) and button():
            return True
        else:
            return False

    def ui_click(
            self,
            click_button,
            check_button,
            appear_button=None,
            additional=None,
            confirm_wait=1,
            offset=(30, 30),
            retry_wait=10,
            skip_first_screenshot=False,
    ):
        """
        Click a button and wait until the check button appears.

        Args:
            click_button (Button):
            check_button (Button, callable):
            appear_button (Button, callable):
            additional (callable):
            confirm_wait (int, float):
            offset (bool, int, tuple):
            retry_wait (int, float):
            skip_first_screenshot (bool):
        """
        logger.hr("UI click")
        if appear_button is None:
            appear_button = click_button

        click_timer = Timer(retry_wait, count=retry_wait // 0.5)
        confirm_wait = confirm_wait if additional is not None else 0
        confirm_timer = Timer(confirm_wait, count=confirm_wait // 0.5).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.ui_process_check_button(check_button, offset=offset):
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

            if click_timer.reached():
                if (isinstance(appear_button, Button) and self.appear(appear_button, offset=offset)) or (
                        callable(appear_button) and appear_button()
                ):
                    self.device.click(click_button)
                    click_timer.reset()
                    continue

            if additional is not None:
                if additional():
                    continue

    def ui_process_check_button(self, check_button, offset=(30, 30)):
        """
        Args:
            check_button (Button, callable, list[Button], tuple[Button]):
            offset:

        Returns:
            bool:
        """
        if isinstance(check_button, Button):
            return self.appear(check_button, offset=offset)
        elif callable(check_button):
            return check_button()
        elif isinstance(check_button, (list, tuple)):
            for button in check_button:
                if self.appear(button, offset=offset):
                    return True
            return False
        else:
            return self.appear(check_button, offset=offset)

    def ui_get_current_page(self, skip_first_screenshot=True):
        """
        Detect which page the game is currently on.

        Args:
            skip_first_screenshot:

        Returns:
            Page:
        """
        logger.info("UI get current page")

        @run_once
        def app_check():
            if not self.device.app_is_running():
                raise GameNotRunningError("Game not running")

        @run_once
        def minicap_check():
            if getattr(self.config, 'Emulator_ControlMethod', None) == "uiautomator2" \
                    and hasattr(self.device, 'uninstall_minicap'):
                self.device.uninstall_minicap()

        orientation_timer = Timer(5)

        timeout = Timer(10, count=20).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            # End
            if timeout.reached():
                break

            # Known pages
            for page in Page.iter_pages():
                if page.check_button is None:
                    continue
                if self.ui_page_appear(page=page):
                    logger.attr("UI", page.name)
                    self.ui_current = page
                    return page

            # Unknown page but able to handle
            logger.info("Unknown ui page")
            if self.ui_additional():
                timeout.reset()
                continue

            app_check()
            minicap_check()
            # continuously check rotation
            if orientation_timer.reached():
                self.device.get_orientation()
                orientation_timer.reset()

        # Unknown page, need manual switching
        logger.warning("Unknown ui page")
        logger.attr("EMULATOR__SCREENSHOT_METHOD", self.config.Emulator_ScreenshotMethod)
        logger.attr("EMULATOR__CONTROL_METHOD", self.config.Emulator_ControlMethod)
        logger.warning("Starting from current page is not supported")
        logger.warning(f"Supported page: {[str(page) for page in Page.iter_pages()]}")
        logger.critical("Please switch to a supported page before starting")
        raise GamePageUnknownError

    def ui_wait_page_leave(self, page, offset=(30, 30), timeout=3):
        """
        Wait until the check button of `page` is off screen.

        Page switches animate. The page that was just left keeps matching while
        it fades out, and a route with more than one hop then fires the second
        hop at a frame that is still showing the first page: three back taps in
        a row leave the game three pages back, the last one landing on whatever
        the home page has at the position of the back arrow.

        Args:
            page (Page): The page just left.
            offset: Template match offset.
            timeout (int, float): Give up after this many seconds.

        Returns:
            bool: If the page left.
        """
        timeout = Timer(timeout).start()
        while not timeout.reached():
            self.device.screenshot()
            if not self.ui_page_appear(page, offset=offset):
                return True

        logger.warning(f'Page {page} still on screen, continue anyway')
        return False

    def ui_goto(self, destination, offset=(30, 30), skip_first_screenshot=True):
        """
        Walk the shortest path to the destination page.

        Args:
            destination (Page):
            offset:
            skip_first_screenshot:
        """
        # Create connection
        Page.init_connection(destination)
        self.interval_clear(list(Page.iter_check_buttons()))

        logger.hr(f"UI goto {destination}")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # Destination page
            if self.ui_page_appear(page=destination, offset=offset):
                logger.info(f'Page arrive: {destination}')
                self.ui_current = destination
                break

            # Other pages
            clicked = False
            for page in Page.iter_pages():
                if page.parent is None or page.check_button is None:
                    continue
                if self.ui_page_appear(page, offset=offset, interval=5):
                    self.ui_current = page
                    logger.info(f'Page switch: {page} -> {page.parent}')
                    button = page.links[page.parent]
                    self.device.click(button)
                    self.interval_reset(button)
                    clicked = True
                    break
            if clicked:
                self.ui_wait_page_leave(page, offset=offset)
                continue

            # Additional
            if self.ui_additional():
                continue

        # Reset connection
        Page.clear_connection()

    def ui_ensure(self, destination, skip_first_screenshot=True):
        """
        Args:
            destination (Page):
            skip_first_screenshot:

        Returns:
            bool: If UI switched.
        """
        logger.hr("UI ensure")
        self.ui_get_current_page(skip_first_screenshot=skip_first_screenshot)
        if self.ui_current == destination:
            logger.info("Already at %s" % destination)
            return False
        else:
            logger.info("Goto %s" % destination)
            self.ui_goto(destination, skip_first_screenshot=True)
            return True

    def app_start(self):
        """
        Launch the game and wait until it is playable.

        The base implementation only launches the app. Games that show boot
        screens override this to walk through them.

        Pages:
            in: any
            out: page_main
        """
        self.device.app_start()

    def ui_goto_main(self):
        """
        Go back to the home page of the current game.
        """
        if self.page_main is None:
            raise GamePageUnknownError('page_main is not set, please define it in your game UI class')
        return self.ui_ensure(destination=self.page_main)

    def ui_ensure_index(
            self,
            index,
            letter,
            next_button,
            prev_button,
            skip_first_screenshot=False,
            fast=True,
            interval=(0.2, 0.3),
    ):
        """
        Args:
            index (int):
            letter (Ocr, callable): OCR button.
            next_button (Button):
            prev_button (Button):
            skip_first_screenshot (bool):
            fast (bool): Default true. False when index is not continuous.
            interval (tuple, int, float): Seconds between two click.
        """
        logger.hr("UI ensure index")
        retry = Timer(1, count=2)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if isinstance(letter, Ocr):
                current = letter.ocr(self.device.image)
            else:
                current = letter(self.device.image)

            logger.attr("Index", current)
            diff = index - current
            if diff == 0:
                break

            if retry.reached():
                button = next_button if diff > 0 else prev_button
                if fast:
                    self.device.multi_click(button, n=abs(diff), interval=interval)
                else:
                    self.device.click(button)
                retry.reset()

    def ui_back(self, click_button, check_button, appear_button=None, offset=(30, 30), retry_wait=10,
                skip_first_screenshot=False):
        """
        Click the back button of the current page.

        Args:
            click_button (Button): Usually the back arrow of the game.
            check_button (Button, callable):
            appear_button (Button, callable):
            offset:
            retry_wait:
            skip_first_screenshot:
        """
        return self.ui_click(
            click_button=click_button,
            check_button=check_button,
            appear_button=appear_button,
            offset=offset,
            retry_wait=retry_wait,
            skip_first_screenshot=skip_first_screenshot,
        )

    def ui_additional(self):
        """
        Hook for game specific popups that may appear on any page.

        Override this in your game UI class. Return True if something was
        handled, so the state loop takes a new screenshot.

        Returns:
            bool: If handled.
        """
        return False
