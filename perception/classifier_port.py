"""Compatibility alias: the single Lane B/Lane C classifier port lives in ``perception.fusion``.

Older command lines used ``--classifier perception.classifier_port:create_classifier``;
keep them working without a second implementation (spec 6.6: one stack).
"""
from .fusion import PerceptronClassifierPort, create_classifier  # noqa: F401

__all__ = ["PerceptronClassifierPort", "create_classifier"]
