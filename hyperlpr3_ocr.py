from __future__ import annotations

import numbers
from typing import Any

import numpy as np

from plate_rec_ocr import PlateRecONNX


class HyperLPR3OCR:
    """Small adapter around hyperlpr3.LicensePlateCatcher."""

    def __init__(self) -> None:
        try:
            import hyperlpr3 as lpr3
        except ImportError as exc:
            raise ImportError(
                "HyperLPR3 is not installed. Install it with: python -m pip install hyperlpr3"
            ) from exc
        self.catcher = lpr3.LicensePlateCatcher()

    def recognize(self, image: np.ndarray) -> tuple[str | None, float | None]:
        results = self.catcher(image)
        return self._parse_results(results)

    @staticmethod
    def _parse_results(results: Any) -> tuple[str | None, float | None]:
        if not results:
            return None, None

        best_text = None
        best_conf = None
        for item in results:
            text = None
            confidence = None
            if isinstance(item, dict):
                text = item.get("code") or item.get("plate") or item.get("text")
                confidence = item.get("confidence") or item.get("score") or item.get("text_confidence")
            elif isinstance(item, (list, tuple)) and item:
                text = item[0]
                if len(item) > 1 and isinstance(item[1], numbers.Real):
                    confidence = float(item[1])
                else:
                    for value in item[1:]:
                        if isinstance(value, numbers.Real):
                            confidence = float(value)
                            break

            if not text:
                continue
            text = PlateRecONNX.clean_plate_text(str(text))
            if not text:
                continue
            if best_text is None or (confidence is not None and (best_conf is None or confidence > best_conf)):
                best_text = text
                best_conf = confidence

        return best_text, best_conf
