"""
Image helpers shared by the tasks of this game.

`Button.match()` matches with the template and the screenshot the wrong way
round (upstream does too), so it only works when both pieces have the same size
and the search area is decided by `Button.area`. Anything that has to look for a
small label at an arbitrary position -- the 「购买成功」 of a shop cell, which
moves with the cell -- needs the helper here instead.

`LostswordUI` has the same helper in `module/lostsword/utils.py`; the two games
do not import each other's code on purpose, so each keeps its own copy.
"""
import cv2


def match(image, button, region):
    """
    Template match a button inside a region.

    `Button.match()` calls `cv2.matchTemplate(self.image, crop(image, ...))`,
    with the template and the screenshot the wrong way round, so it only works
    when both have the same size. This helper does it the right way round and
    searches a narrow region, which keeps a generic label such as 「购买成功」
    from matching somewhere else on the screen.

    Args:
        image (np.ndarray): Screenshot.
        button (Button): Template to look for.
        region (tuple): (x1, y1, x2, y2) to search in.

    Returns:
        float: Similarity of the best match, 0 when the region is too small.
    """
    button.ensure_template()
    template = button.image
    if isinstance(template, list):
        template = template[0]
    x1, y1, x2, y2 = region
    x1, y1 = max(0, int(x1)), max(0, int(y1))
    x2, y2 = min(image.shape[1], int(x2)), min(image.shape[0], int(y2))
    patch = image[y1:y2, x1:x2]
    if patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
        return 0.0
    res = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(res)[1])
