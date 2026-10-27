from module.base.button import Button
from module.base.decorator import cached_property
from module.base.points import fit_points
from module.base.timer import Timer
from module.base.utils import *
from module.config.config import AlasConfig
from module.config.server import set_server, to_package
from module.device.device import Device
from module.device.method.utils import HierarchyButton
from module.logger import logger
from module.webui.setting import cached_class_property


class ModuleBase:
    config: AlasConfig
    device: Device

    EARLY_OCR_IMPORT = False

    def __init__(self, config, device=None, task=None):
        """
        Args:
            config (AlasConfig, str):
                Name of the user config under ./config
            device (Device, str):
                To reuse a device.
                If None, create a new Device object.
                If str, create a new Device object and use the given device as serial.
            task (str):
                Bind a task only for dev purpose. Usually to be None for auto task scheduling.
                If None, use default configs.
        """
        if isinstance(config, AlasConfig):
            self.config = config
            if task is not None:
                self.config.init_task(task)
        elif isinstance(config, str):
            self.config = AlasConfig(config, task=task)
        else:
            logger.warning('Alas ModuleBase received an unknown config, assume it is AlasConfig')
            self.config = config

        if isinstance(device, Device):
            self.device = device
        elif device is None:
            self.device = Device(config=self.config)
        elif isinstance(device, str):
            self.config.override(Emulator_Serial=device)
            self.device = Device(config=self.config)
        else:
            logger.warning('Alas ModuleBase received an unknown device, assume it is Device')
            self.device = device

        self.interval_timer = {}
        self.early_ocr_import()

    def early_ocr_import(self):
        """
        Start a thread to import cnocr and mxnet while the Alas instance just starting to take screenshots
        The import is paralleled since taking screenshot is I/O-bound while importing is CPU-bound,
        thus would speed up the startup 0.5 ~ 1.0s and even 5s on slow PCs.
        """
        if ModuleBase.EARLY_OCR_IMPORT:
            return
        if not self.config.is_actual_task:
            logger.info('No actual task bound, skip early_ocr_import')
            return
        if self.config.task.command in ['Daemon', 'OpsiDaemon']:
            logger.info('No ocr in daemon task, skip early_ocr_import')
            return

        def do_ocr_import():
            # Wait first image
            import time
            while 1:
                if self.device.has_cached_image:
                    break
                time.sleep(0.01)

            logger.info('early_ocr_import start')
            from module.ocr.al_ocr import AlOcr
            _ = AlOcr
            logger.info('early_ocr_import finish')

        logger.info('early_ocr_import call')
        import threading
        thread = threading.Thread(target=do_ocr_import, daemon=True)
        thread.start()
        ModuleBase.EARLY_OCR_IMPORT = True

    @cached_class_property
    def worker(self):
        """
        A thread pool to run things at background

        Examples:
        ```
        def func(image):
            logger.info('Update thread start')
            with self.config.multi_set():
                self.dungeon_get_simuni_point(image)
                self.dungeon_update_stamina(image)
        ModuleBase.worker.submit(func, self.device.image)
        ```
        """
        logger.hr('Creating worker')
        from concurrent.futures import ThreadPoolExecutor
        pool = ThreadPoolExecutor(1)
        return pool

    def ensure_button(self, button):
        if isinstance(button, str):
            button = HierarchyButton(self.device.hierarchy, button)

        return button

    def loop(self, skip_first=True, timeout=None):
        """
        A syntactic sugar to start a state loop

        Args:
            skip_first (bool): Usually to be True to reuse the previous screenshot
            timeout (int | float | Timer): Seconds of timeout or a Timer object

        Yields:
            np.ndarray: screenshot

        Examples:
            # state machine that handle clicking until destination
            for _ in self.loop():
                if self.appear(...):
                    break
                if self.appear_then_click(...):
                    continue

        Examples:
            # state machine with timeout
            for _ in self.loop(timeout=2):
                if self.appear(...):
                    logger.info('Wait success')
                    break
            else:
                logger.warning('Wait timeout')
        """
        if timeout is not None:
            if isinstance(timeout, Timer):
                timeout.reset()
            else:
                timeout = Timer.from_seconds(timeout).start()

        while 1:
            if timeout is not None:
                if timeout.reached():
                    return

            if skip_first:
                skip_first = False
            else:
                self.device.screenshot()

            try:
                yield self.device.image
            except AttributeError:
                self.device.screenshot()
                yield self.device.image

    def loop_hierarchy(self, skip_first=True):
        """
        A syntactic sugar to start a hierarchy state loop

        Args:
            skip_first (bool): Usually to be True to reuse the previous hierarchy

        Yields:
            etree._Element: hierarchy
        """
        while 1:
            if skip_first:
                skip_first = False
            else:
                self.device.dump_hierarchy()
            yield self.device.hierarchy

    def loop_screenshot_hierarchy(self, skip_first=True):
        """
        A syntactic sugar to start a state loop that takes screenshots and dump hierarchy

        Args:
            skip_first (bool): Usually to be True to reuse the previous screenshot

        Yields:
            tuple[np.ndarray, etree._Element]: screenshot, hierarchy
        """
        while 1:
            if skip_first:
                skip_first = False
            else:
                self.device.screenshot()
                self.device.dump_hierarchy()
            yield self.device.image, self.device.hierarchy

    def appear(self, button, offset=0, interval=0, similarity=0.85, threshold=10):
        """
        Args:
            button (Button, Template, HierarchyButton, str):
            offset (bool, int):
            interval (int, float): interval between two active events.
            similarity (int, float): 0 to 1.
            threshold (int, float): 0 to 255 if not use offset, smaller means more similar

        Returns:
            bool:

        Examples:
            Image detection:
            ```
            self.device.screenshot()
            self.appear(Button(area=(...), color=(...), button=(...))
            self.appear(Template(file='...')
            ```

            Hierarchy detection (detect elements with xpath):
            ```
            self.device.dump_hierarchy()
            self.appear('//*[@resource-id="..."]')
            ```
        """
        button = self.ensure_button(button)
        self.device.stuck_record_add(button)

        if interval:
            if button.name in self.interval_timer:
                if self.interval_timer[button.name].limit != interval:
                    self.interval_timer[button.name] = Timer(interval)
            else:
                self.interval_timer[button.name] = Timer(interval)
            if not self.interval_timer[button.name].reached():
                return False

        if isinstance(button, HierarchyButton):
            appear = bool(button)
        elif offset:
            if isinstance(offset, bool):
                offset = self.config.BUTTON_OFFSET
            appear = button.match(self.device.image, offset=offset, similarity=similarity)
        else:
            appear = button.appear_on(self.device.image, threshold=threshold)

        if appear and interval:
            self.interval_timer[button.name].reset()

        return appear

    def match_template_color(self, button, offset=(20, 20), interval=0, similarity=0.85, threshold=30):
        """
        Args:
            button (Button):
            offset (bool, int):
            interval (int, float): interval between two active events.
            similarity (int, float): 0 to 1.
            threshold (int, float): 0 to 255 if not use offset, smaller means more similar

        Returns:
            bool:
        """
        button = self.ensure_button(button)
        self.device.stuck_record_add(button)

        if interval:
            if button.name in self.interval_timer:
                if self.interval_timer[button.name].limit != interval:
                    self.interval_timer[button.name] = Timer(interval)
            else:
                self.interval_timer[button.name] = Timer(interval)
            if not self.interval_timer[button.name].reached():
                return False

        appear = button.match_template_color(
            self.device.image, offset=offset, similarity=similarity, threshold=threshold)

        if appear and interval:
            self.interval_timer[button.name].reset()

        return appear

    def appear_then_click(self, button, screenshot=False, genre='items', offset=0, interval=0, similarity=0.85,
                          threshold=30):
        button = self.ensure_button(button)
        appear = self.appear(button, offset=offset, interval=interval, similarity=similarity, threshold=threshold)
        if appear:
            if screenshot:
                self.device.sleep(self.config.WAIT_BEFORE_SAVING_SCREEN_SHOT)
                self.device.screenshot()
                self.device.save_screenshot(genre=genre)
            self.device.click(button)
        return appear

    def wait_until_appear(self, button, offset=0, skip_first_screenshot=False, timeout=None, settle=1):
        """
        Poll until `button` shows up.

        Args:
            button (Button, Template, str):
            offset (bool, int, tuple):
            skip_first_screenshot (bool): Reuse the current image at first try.
            timeout (int, float, None): Seconds before giving up. None polls
                forever, which is what upstream does and what a task that cannot
                continue without the button wants, so prefer a number.
            settle (int): Consecutive frames that have to match. A fading in
                element matches from its first frame on but swallows clicks
                until the animation ends, so a click right after a plain match
                is lost. 1 keeps the old behaviour.

        Returns:
            bool: If the button appeared.

        Examples:
            ```
            if self.wait_until_appear(REWARD_CHECK, offset=(20, 20), timeout=5):
                self.handle_reward()
            ```
        """
        timeout = None if timeout is None else Timer(timeout).start()
        present = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.appear(button, offset=offset):
                present += 1
                if present >= settle:
                    return True
            else:
                present = 0
            if timeout is not None and timeout.reached():
                logger.warning(f'wait_until_appear({button}) timeout')
                return False

    def wait_until_appear_then_click(self, button, offset=0, timeout=None):
        """
        Args:
            button (Button, Template, str):
            offset:
            timeout (int, float, None):

        Returns:
            bool: If clicked.
        """
        if self.wait_until_appear(button, offset=offset, timeout=timeout):
            self.device.click(button)
            return True
        return False

    def wait_until_disappear(self, button, offset=0, skip_first_screenshot=False, timeout=None, settle=1):
        """
        Poll until `button` is off screen.

        Args:
            button (Button, Template, str):
            offset:
            skip_first_screenshot (bool):
            timeout (int, float, None): Seconds before giving up.
            settle (int): Consecutive frames that have to miss. An element stops
                matching on the first frame of its fade-out but still eats the
                clicks aimed at what is underneath, so the absence has to hold
                before anything below may be pressed.

        Returns:
            bool: If the button disappeared.
        """
        timeout = None if timeout is None else Timer(timeout).start()
        absent = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if not self.appear(button, offset=offset):
                absent += 1
                if absent >= settle:
                    return True
            else:
                absent = 0
            if timeout is not None and timeout.reached():
                logger.warning(f'wait_until_disappear({button}) timeout')
                return False

    def wait_until_still(self, area, timeout=3, threshold=1.0, skip_first_screenshot=True):
        """
        Wait until an area of the screen stops changing.

        Gestures and panel animations have no check point of their own - there
        is nothing to match while a card list snaps to its new position - so the
        usual answer is `device.sleep(pause)`, which is a guess: too short on a
        slow emulator, wasted time on a fast one. Watching the area until two
        consecutive frames agree is the same wait without the guess.

        Args:
            area (Button, tuple): Button or area to watch.
            timeout (int, float): Seconds before giving up.
            threshold (float): Mean absolute difference per channel, in 0-255,
                below which two frames count as the same.
            skip_first_screenshot (bool): Reuse the current image as the first
                frame of the comparison.

        Returns:
            bool: If the area stopped changing.
        """
        timeout = Timer(timeout).start()
        previous = None
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
                if not self.device.has_cached_image:
                    self.device.screenshot()
            else:
                self.device.screenshot()

            current = self.image_crop(area, copy=True)
            if previous is not None:
                diff = np.mean(np.abs(current.astype(np.int16) - previous.astype(np.int16)))
                if diff < threshold:
                    return True
            previous = current

            if timeout.reached():
                logger.warning(f'Area {area} is still changing')
                return False

    def wait_until_settled(self, button, timeout=3, skip_first_screenshot=True, offset=None):
        """
        Wait until a check point appears on a frame that is fully drawn.

        `ui_page_appear()` matches a template with an offset, which is loose
        enough to fire while the page is still fading in, and a color check
        point (`offset=None`) compares the mean color of its area, which a half
        drawn frame always fails because it is dimmer. Both are useful, and both
        are wrong right after a page switch: the first says "arrived" too early,
        the second says "not here" on the frame it is given.

        This polls until the check point matches, so the image left in
        `device.image` is a settled one and the next state loop may start with
        `skip_first_screenshot=True`.

        Args:
            button (Button): Check point.
            timeout (int, float): Seconds to wait before giving up.
            skip_first_screenshot (bool): Reuse the current image at first try.
            offset (tuple, int, None): Template match offset, or None to match
                by mean color.

        Returns:
            bool: If the check point appeared.
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

    def wait_until_stable(self, button, timer=Timer(0.3, count=1), timeout=Timer(5, count=10), skip_first_screenshot=True):
        button._match_init = False
        timeout.reset()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if button._match_init:
                if button.match(self.device.image, offset=(0, 0)):
                    if timer.reached():
                        break
                else:
                    button.load_color(self.device.image)
                    timer.reset()
            else:
                button.load_color(self.device.image)
                button._match_init = True

            if timeout.reached():
                logger.warning(f'wait_until_stable({button}) timeout')
                break

    def image_crop(self, button, copy=True):
        """Extract the area from image.

        Args:
            button(Button, tuple): Button instance or area tuple.
            copy:
        """
        if isinstance(button, Button):
            return crop(self.device.image, button.area, copy=copy)
        elif hasattr(button, 'area'):
            return crop(self.device.image, button.area, copy=copy)
        else:
            return crop(self.device.image, button, copy=copy)

    def image_color_count(self, button, color, threshold=30, count=50):
        """
        Args:
            button (Button, tuple): Button instance or area.
            color (tuple): RGB.
            threshold: 0 means colors are the same, the higher the worse.
            count (int): Pixels count.

        Returns:
            bool:
        """
        if isinstance(button, np.ndarray):
            image = button
        else:
            image = self.image_crop(button, copy=False)
        mask = color_mask(image, color, threshold=threshold)
        sum_ = cv2.countNonZero(mask)
        return sum_ > count

    def image_color_button(self, area, color, threshold=5, encourage=5, name='COLOR_BUTTON'):
        """
        Find an area with pure color on image, convert into a Button.

        Args:
            area (tuple[int]): Area to search from
            color (tuple[int]): Target color
            threshold (int): 0-255, 0 means exact match
            encourage (int): Radius of button
            name (str): Name of the button

        Returns:
            Button: Or None if nothing matched.
        """
        mask = color_mask(self.image_crop(area, copy=False), color=color, threshold=threshold)
        points = np.array(np.where(mask > 0)).T[:, ::-1]
        if points.shape[0] < encourage ** 2:
            # Not having enough pixels to match
            return None

        point = fit_points(points, mod=image_size(mask), encourage=encourage)
        point = ensure_int(point + area[:2])
        button_area = area_offset((-encourage, -encourage, encourage, encourage), offset=point)
        color = get_color(self.device.image, button_area)
        return Button(area=button_area, color=color, button=button_area, name=name)

    def get_interval_timer(self, button, interval=5, renew=False) -> Timer:
        if hasattr(button, 'name'):
            name = button.name
        elif callable(button):
            name = button.__name__
        else:
            name = str(button)

        try:
            timer = self.interval_timer[name]
            if renew and timer.limit != interval:
                timer = Timer(interval)
                self.interval_timer[name] = timer
            return timer
        except KeyError:
            timer = Timer(interval)
            self.interval_timer[name] = timer
            return timer

    def interval_reset(self, button, interval=3):
        if isinstance(button, (list, tuple)):
            for b in button:
                self.interval_reset(b)
            return

        if button is not None:
            if button.name in self.interval_timer:
                self.interval_timer[button.name].reset()
            else:
                self.interval_timer[button.name] = Timer(interval).reset()

    def interval_clear(self, button, interval=3):
        if isinstance(button, (list, tuple)):
            for b in button:
                self.interval_clear(b)
            return

        if button is not None:
            if button.name in self.interval_timer:
                self.interval_timer[button.name].clear()
            else:
                self.interval_timer[button.name] = Timer(interval).clear()

    _image_file = ''

    @property
    def image_file(self):
        return self._image_file

    @image_file.setter
    def image_file(self, value):
        """
        For development.
        Load image from local file system and set it to self.device.image
        Test an image without taking a screenshot from emulator.
        """
        if isinstance(value, Image.Image):
            value = np.array(value)
        elif isinstance(value, str):
            value = load_image(value)

        self.device.image = value

    def set_server(self, server):
        """
        For development.
        Change server and this will effect globally,
        including assets and server specific methods.
        """
        package = to_package(server)
        self.device.package = package
        set_server(server)
        logger.attr('Server', self.config.SERVER)
