"""繁体中文单行 OCR（PP-OCRv3 rec，ONNX Runtime）。

为什么自己写：仓库的 `module/ocr` 走 cnocr 1.x + mxnet，cnocr 自带的
`tw` 模型在卡面白字上错字很多（劍光→創光），而 PaddleOCR 的
`chinese_cht_PP-OCRv3` 识别模型只有 ONNX 版、cnocr 1.x 用不了。
这里只做**识别**（不做检测），输入是一行已经切好的行图，所以只需要
onnxruntime + 模型 + 字典，不牵扯 cnstd / rapidocr / paddle。

预处理与 PaddleOCR 的 `RecImgDecode` 一致：等比缩放到高 48，归一化到 [-1,1]，
按 (1,3,48,W) 送入；输出 (1,T,C) 取 argmax 后按 CTC 去重、去 blank。
"""

import os

import cv2
import numpy as np

from module.logger import logger

MODEL_FILE = './bin/ocr_models/chinese_cht_PP-OCRv3_rec_infer.onnx'
DICT_FILE = './bin/ocr_models/ppocr_keys_v1.txt'

REC_HEIGHT = 48
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


class ChtOcr:
    """繁体单行 OCR。第一次调用时才加载模型，缺模型/缺 onnxruntime 就返回 None。"""

    def __init__(self, model=MODEL_FILE, dictionary=DICT_FILE):
        self.model_file = model
        self.dict_file = dictionary
        self.session = None
        self.chars = None
        self.failed = False

    def available(self):
        """模型和 onnxruntime 都在才算可用。"""
        if self.failed:
            return False
        if not os.path.exists(self.model_file) or not os.path.exists(self.dict_file):
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
        # 这个模型把字符表写在 ONNX metadata 的 `character` 里（8423 类），
        # 和 ppocr_keys_v1.txt（6624）不是一套，用文件字典会全部错位。
        meta = self.session.get_modelmeta().custom_metadata_map or {}
        self.chars = None
        if meta.get('character'):
            chars = meta['character'].splitlines()
            self.chars = [''] + chars
            logger.info('Traditional OCR model loaded, %s chars from metadata' % len(self.chars))
        else:
            self.chars = load_dict(self.dict_file)
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
        for item in index:
            item = int(item)
            if item != last and item != 0:
                if item < len(self.chars):
                    result.append(self.chars[item])
            last = item
        return ''.join(result)
