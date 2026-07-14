from decimal import Decimal

from domain.entities.signal import Signal
from domain.value_objects.confidence import ConfidenceLabel


class SignalEvaluator:
    def evaluate(self, signal: Signal, min_confidence: float = 0.6) -> bool:
        if signal.confidence.score < min_confidence:
            signal.reject(
                f"Confidence {signal.confidence.score:.0%} below minimum {min_confidence:.0%}"
            )
            return False

        signal.approve()
        return True
