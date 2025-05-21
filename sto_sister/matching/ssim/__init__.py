from .match import SSIMMatchEngine


class SSIMEngine:
    def __init__(
        self, debug=False, icon_loader=None, overlay_loader=None, hash_index=None
    ):
        """
        Composite SSIM engine that delegates prefiltering, quality, and matching.
        """
        self.match_engine = SSIMMatchEngine(
            debug, icon_loader, overlay_loader, hash_index
        )

    def match_all(
        self,
        icon_slots,
        icon_dir_map,
        overlays,
        predicted_qualities,
        filtered_icons,
        found_icons,
        threshold=0.8,
    ):
        return self.match_engine.match_all(
            icon_slots,
            icon_dir_map,
            overlays,
            predicted_qualities,
            filtered_icons,
            found_icons,
            threshold,
        )
