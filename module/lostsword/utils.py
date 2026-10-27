import re

import cv2

from module.base.button import Button

"""
Image helpers shared by the tasks of this game.

`Button.match()` matches with the template and the screenshot the wrong way
round (upstream does too), so it only works when both pieces have the same size.
Anything that has to search a narrow region for a small label needs the helpers
here instead.
"""


def match(image, button, region):
    """
    Template match a button inside a region.

    `Button.match()` calls `cv2.matchTemplate(self.image, crop(image, ...))`,
    with the template and the screenshot the wrong way round, so it only works
    when both have the same size. This helper does it the right way round and
    searches a narrow region, which keeps a generic label such as 「选择」 from
    matching somewhere else on the screen.

    Args:
        image (np.ndarray): Screenshot.
        button (Button): Template to look for.
        region (tuple): (x1, y1, x2, y2) to search in.

    Returns:
        float: Similarity of the best match, 0 when the region is too small.
    """
    button.ensure_template()
    template = button.image
    x1, y1, x2, y2 = region
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(image.shape[1], int(x2)), min(image.shape[0], int(y2))
    patch = image[y1:y2, x1:x2]
    if patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
        return 0.0
    res = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(res)[1])


def read_text(image, area):
    """
    OCR a piece of the screenshot with the Chinese model.

    The default model of the framework is trained on the Latin names of the other
    game and turns Chinese into noise, so every read of a Chinese label has to ask
    for `cnocr` explicitly. Punctuation never survives the model, and the names of
    this game carry a middle dot (迪安·凯特), so whatever is not a Han character is
    dropped instead of compared.

    Args:
        image (np.ndarray): Screenshot.
        area (tuple): (x1, y1, x2, y2).

    Returns:
        str: What was read, Han characters only.
    """
    from module.ocr.ocr import Ocr

    button = Button(area=area, color=(0, 0, 0), button=area, name='NAME')
    ocr = Ocr(button, lang='cnocr', letter=(255, 255, 255), threshold=170,
              name='CHAR_NAME')
    text = ocr.ocr(image)
    return re.sub(r'[^\u4e00-\u9fa5]', '', str(text))
