"""OCR helpers shared by the coupon tasks.

`Ocr` of the framework has to be told the colour of the letters: it turns
everything that matches `letter` black and everything else white, which is the
shape the Chinese model expects. 失落之剑 prints white text on a dark panel,
棕色尘埃2 answers in a system alert, i.e. black text on white - so the colour is
a parameter here, not a constant.
"""
import re

from module.base.button import Button


def read_text(image, area, letter=(255, 255, 255), threshold=170):
    """
    OCR one line of Chinese.

    The default model of the framework is trained on the Latin names of another
    game and turns Chinese into noise, so every read of a Chinese label has to
    ask for `cnocr` explicitly. Punctuation never survives the model, and the
    names in these games carry a middle dot (迪安·凯特), so whatever is not a Han
    character is dropped instead of compared.

    One line at a time: the model is asked to read single lines
    (`atomic_ocr_for_single_lines`), and handing it a two-line crop returns
    noise - measured on the coupon alert of 棕色尘埃2, which is either one line or
    two depending on the answer.

    Args:
        image (np.ndarray): Screenshot.
        area (tuple): (x1, y1, x2, y2).
        letter (tuple(int)): RGB of the text.
        threshold (int): How far from `letter` a pixel may be and still count.

    Returns:
        str: What was read, Han characters only.
    """
    from module.ocr.ocr import Ocr

    button = Button(area=area, color=(0, 0, 0), button=area, name='NAME')
    ocr = Ocr(button, lang='cnocr', letter=letter, threshold=threshold, name='TEXT')
    text = ocr.ocr(image)
    return re.sub(r'[^\u4e00-\u9fa5]', '', str(text))
