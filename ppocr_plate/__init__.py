"""Training and deployment utilities for the plate-specific PP-OCR recognizer."""

from .runtime import PlateCTCRecognizer, ctc_decode, preprocess_plate

__all__ = ["PlateCTCRecognizer", "ctc_decode", "preprocess_plate"]
