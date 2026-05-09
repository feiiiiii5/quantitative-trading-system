from quantcore_ai.factor_mining import FactorMiner
from quantcore_ai.risk_detector import AIRiskDetector

__all__ = [
    "FactorMiner",
    "AIRiskDetector",
]

try:
    from quantcore_ai.transformer_predict import TransformerPredictor

    __all__.append("TransformerPredictor")
except ImportError:
    pass

try:
    from quantcore_ai.rl_trading import TradingEnvironment, RLTrainer

    __all__.extend(["TradingEnvironment", "RLTrainer"])
except ImportError:
    pass

__version__ = "1.0.0"
