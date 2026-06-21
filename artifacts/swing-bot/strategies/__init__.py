from .swing1 import check as swing1
from .swing2 import check as swing2
from .swing3 import check as swing3

STRATEGIES: list[tuple[str, callable]] = [
    ("SW1 D1 Fib Reversal",          swing1),
    ("SW2 D1 Pullback",              swing2),
    ("SW3 Zone Bounce Continuation", swing3),
]