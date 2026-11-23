"""繁体中文单行 OCR（优先专用 ONNX 模型，缺失时回退 PP-OCRv3 ONNX）。

为什么自己写：仓库的 `module/ocr` 走 cnocr 1.x + mxnet，cnocr 自带的
`tw` 模型在卡面白字上错字很多（劍光→創光），而新版 cnocr / PaddleOCR
导出为 ONNX 后只需要 onnxruntime 即可离线推理，不牵扯 cnstd / rapidocr / torch。

支持两种 ONNX 元数据格式：
1. 自训卡厄思专用模型（`preprocess == 'cnocr_gray_32_01'`）：灰度缩放到高 32，
   归一化到 [0, 1]，inputs `x` + `input_lengths`，blank = len(vocab)。
2. 通用繁体 `chinese_cht_PP-OCRv3_rec_infer.onnx`：等比缩放到高 48，
   归一化到 [-1, 1]，按 (1, 3, 48, W) 送入，blank = 0。
"""

import os
import time

import cv2
import numpy as np

from module.base.button import Button
from module.base.utils import float2str
from module.logger import logger

MODEL_FILE = './bin/ocr_models/chaoszero_cht_rec.onnx'
FALLBACK_MODEL_FILE = './bin/ocr_models/chinese_cht_PP-OCRv3_rec_infer.onnx'
DICT_FILE = './bin/ocr_models/ppocr_keys_v1.txt'

REC_HEIGHT = 48
CNOCR_HEIGHT = 32
REC_MAX_WIDTH = 1200
# 单行图的高度下限，太扁的行（装饰线）不送进去，否则会读出一个字
MIN_LINE_HEIGHT = 8


def load_dict(file=DICT_FILE):
    """读字典，返回 index → 字符 的列表（index 0 是 blank）。"""
    with open(file, encoding='utf-8') as f:
        chars = [line.rstrip('\n') for line in f]
    return [''] + chars


def preprocess(image):
    """RGB/gray 单行图 → (1,3,48,W) float32，[-1,1]。"""
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    elif image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2RGB)
    height, width = image.shape[:2]
    ratio = width / float(height)
    target = int(round(REC_HEIGHT * ratio))
    target = max(8, min(REC_MAX_WIDTH, target))
    resized = cv2.resize(image, (target, REC_HEIGHT), interpolation=cv2.INTER_LINEAR)
    array = resized.astype(np.float32) / 255.0
    array = (array - 0.5) / 0.5
    array = np.transpose(array, (2, 0, 1))
    return np.expand_dims(array, axis=0)


def preprocess_cnocr(image):
    """RGB/gray 单行图 → ((1,1,32,W) float32 [0,1], target_width)。"""
    if image.ndim == 3:
        if image.shape[2] == 4:
            gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        else:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image
    height, width = gray.shape[:2]
    target = int(round(CNOCR_HEIGHT * (width / float(height))))
    target = max(16, min(REC_MAX_WIDTH, target))
    resized = cv2.resize(gray, (target, CNOCR_HEIGHT), interpolation=cv2.INTER_LINEAR)
    array = (resized.astype(np.float32) / 255.0)[None, None, :, :]
    return array, target


class ChtOcr:
    """繁体单行 OCR。第一次调用时才加载模型，缺模型/缺 onnxruntime 就返回空串。"""

    def __init__(self, model=None, dictionary=DICT_FILE):
        if model is None:
            model = MODEL_FILE if os.path.exists(MODEL_FILE) else FALLBACK_MODEL_FILE
        self.model_file = model
        self.dict_file = dictionary
        self.session = None
        self.chars = None
        self.mode = 'ppocr'
        self.blank = 0
        self.failed = False

    def available(self):
        """模型和 onnxruntime 都在才算可用。"""
        if self.failed:
            return False
        if not os.path.exists(self.model_file):
            return False
        if self.model_file == FALLBACK_MODEL_FILE and not os.path.exists(self.dict_file):
            return False
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            return False
        return True

    def _load(self):
        import onnxruntime

        options = onnxruntime.SessionOptions()
        options.log_severity_level = 3
        options.intra_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(self.model_file, sess_options=options)
        meta = self.session.get_modelmeta().custom_metadata_map or {}
        if meta.get('preprocess') == 'cnocr_gray_32_01' and meta.get('character'):
            chars = [' ' if ch == '<space>' else ch for ch in meta['character'].splitlines()]
            self.chars = chars
            self.mode = 'cnocr'
            self.blank = len(chars)
            logger.info('Chaos Zero dedicated OCR model loaded, %s chars' % len(self.chars))
        elif meta.get('character'):
            # PP-OCRv3 cht 把字符表写在 ONNX metadata 的 `character` 里（8423 类），
            # 和 ppocr_keys_v1.txt（6624）不是一套，用文件字典会全部错位。
            chars = meta['character'].splitlines()
            self.chars = [''] + chars
            self.mode = 'ppocr'
            self.blank = 0
            logger.info('Traditional OCR model loaded, %s chars from metadata' % len(self.chars))
        else:
            self.chars = load_dict(self.dict_file)
            self.mode = 'ppocr'
            self.blank = 0
            logger.info('Traditional OCR model loaded, %s chars from dict file' % len(self.chars))

    def line(self, image):
        """读一行，返回字符串。"""
        if image is None or image.shape[0] < MIN_LINE_HEIGHT:
            return ''
        if self.session is None:
            if not self.available():
                self.failed = True
                return ''
            self._load()
        if self.mode == 'cnocr':
            batch, target_w = preprocess_cnocr(image)
            output = self.session.run(
                None,
                {'x': batch, 'input_lengths': np.array([target_w], dtype=np.int64)},
            )[0]
        else:
            batch = preprocess(image)
            output = self.session.run(None, {self.session.get_inputs()[0].name: batch})[0]
        return self.decode(output)

    def lines(self, images):
        return [self.line(image) for image in images]

    def decode(self, output):
        """argmax → CTC 去重 → 查字典。"""
        index = output.argmax(axis=2)[0]
        result = []
        last = -1
        blank = self.blank
        for item in index:
            item = int(item)
            if item != last and item != blank:
                if item < len(self.chars):
                    result.append(self.chars[item])
            last = item
        return ''.join(result)


_CHT_OCR = None


def get_cht_ocr():
    """Return the process-wide cached `ChtOcr` instance."""
    global _CHT_OCR
    if _CHT_OCR is None:
        _CHT_OCR = ChtOcr()
    return _CHT_OCR


class ChaoszeroOcr:
    """Drop-in `Ocr` adapter backed by `chaoszero_cht_rec.onnx` with `Ocr` fallback."""

    SHOW_LOG = True

    def __init__(self, buttons, lang='cnocr', letter=(255, 255, 255), threshold=128,
                 alphabet=None, scale=1.0, name=None):
        self.name = str(buttons) if isinstance(buttons, Button) else name
        self._buttons = buttons
        self.lang = lang
        self.letter = letter
        self.threshold = threshold
        self.alphabet = alphabet
        self.scale = scale
        self._fallback = None

    def _area(self):
        return self._buttons.area if isinstance(self._buttons, Button) else self._buttons

    def _get_fallback(self):
        if self._fallback is None:
            from module.ocr.ocr import Ocr

            self._fallback = Ocr(
                self._buttons,
                lang=self.lang,
                letter=self.letter,
                threshold=self.threshold,
                alphabet=self.alphabet,
                name=self.name,
            )
            self._fallback.SHOW_LOG = self.SHOW_LOG
        return self._fallback

    def ocr(self, image, direct_ocr=False):
        """Recognize one single-line region and return the text string."""
        cht = get_cht_ocr()
        if not cht.available():
            return self._get_fallback().ocr(image, direct_ocr=direct_ocr)

        start_time = time.time()
        if direct_ocr:
            crop = image
        else:
            x1, y1, x2, y2 = self._area()
            crop = image[y1:y2, x1:x2]
        if crop is not None and crop.size and self.scale and self.scale != 1.0:
            crop = cv2.resize(crop, None, fx=self.scale, fy=self.scale,
                              interpolation=cv2.INTER_CUBIC)
        text = cht.line(crop)
        if self.alphabet:
            allowed = set(self.alphabet)
            text = ''.join(ch for ch in text if ch in allowed)
        if self.SHOW_LOG:
            logger.attr(name='%s %ss' % (self.name, float2str(time.time() - start_time)),
                        text=str(text))
        return text
