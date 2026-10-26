import re

import module.config.server as server
from module.base.decorator import cached_property, del_cached_property


def get_assets_from_file(file, regex):
    """
    Collect asset names declared in a python file.

    A missing file yields an empty set: the preserved-asset list references
    modules that a stripped or new game may not have, and a missing file must
    not take down `release_resources()` in the middle of the task queue.

    Args:
        file (str): Path of the file to scan.
        regex (Pattern): Pattern whose group 1 is the asset name.

    Returns:
        set: Asset names.
    """
    assets = set()
    try:
        with open(file, 'r', encoding='utf-8') as f:
            for row in f.readlines():
                result = regex.search(row)
                if result:
                    assets.add(result.group(1))
    except FileNotFoundError:
        pass
    return assets


class PreservedAssets:
    @cached_property
    def ui(self):
        assets = set()
        # Game files may live anywhere, they are scanned by their own modules.
        # Only the framework level page assets are listed here.
        assets |= get_assets_from_file(
            file='./module/ui/ui.py',
            regex=re.compile(r'\(([A-Z][A-Z0-9_]+),')
        )
        return assets


_preserved_assets = PreservedAssets()


class Resource:
    # Class property, record all button and templates
    instances = {}
    # Instance property, record cached properties of instance
    cached = []

    def resource_add(self, key):
        Resource.instances[key] = self

    def resource_release(self):
        for cache in self.cached:
            del_cached_property(self, cache)

    @classmethod
    def is_loaded(cls, obj):
        if hasattr(obj, '_image') and obj._image is None:
            return False
        elif hasattr(obj, 'image') and obj.image is None:
            return False
        return True

    @classmethod
    def resource_show(cls):
        from module.logger import logger
        logger.hr('Show resource')
        for key, obj in cls.instances.items():
            if cls.is_loaded(obj):
                continue
            logger.info(f'{obj}: {key}')

    @staticmethod
    def parse_property(data, s=None):
        """
        Parse properties of Button or Template object input.
        Such as `area`, `color` and `button`.

        Args:
            data: Dict or str
            s (str): Load from given a server or load from global attribute `server.server`
        """
        if s is None:
            s = server.server
        if isinstance(data, dict):
            return data[s]
        else:
            return data


def release_resources(next_task=''):
    # Release all OCR models
    # Usually to have 2 models loaded and each model takes about 20MB
    # This will release 20-40MB
    from module.webui.setting import State
    if State.deploy_config.UseOcrServer:
        if not next_task:
            # Disconnect OCR server on idle
            from module.ocr.ocr import OCR_MODEL
            try:
                OCR_MODEL.close()
            except AttributeError:
                pass
    else:
        # Release only when using per-instance OCR
        from module.ocr.ocr import OCR_MODEL
        if next_task:
            # Keep the default model, the next task will use it right away
            models = ['cnocr', 'jp', 'tw']
        else:
            models = ['azur_lane', 'cnocr', 'jp', 'tw']
        for model in models:
            del_cached_property(OCR_MODEL, model)

    # Release assets cache
    # module.ui has about 80 assets and takes about 3MB
    # Alas has about 800 assets, but they are not all loaded.
    # Template images take more, about 6MB each
    for key, obj in Resource.instances.items():
        # Preserve assets for ui switching
        if next_task and str(obj) in _preserved_assets.ui:
            continue
        # if Resource.is_loaded(obj):
        #     logger.info(f'Release {obj}')
        obj.resource_release()

    # Useless in most cases, but just call it
    # gc.collect()
