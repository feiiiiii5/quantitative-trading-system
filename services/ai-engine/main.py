import logging
import signal
import sys
import time
from concurrent import futures
from pathlib import Path

import grpc
import numpy as np
import pandas as pd
import uvloop

uvloop.install()

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "generated"))

from ai_engine_pb2 import (
    AnomalyAlert,
    AnomalyStreamRequest,
    FactorMiningRequest,
    FactorMiningResponse,
    FactorResult,
    HealthCheckRequest,
    HealthCheckResponse,
    PredictRequest,
    PredictResponse,
    RiskDetectionRequest,
    RiskDetectionResponse,
)
from ai_engine_pb2_grpc import AIEngineServiceServicer, add_AIEngineServiceServicer_to_server
from quantcore_ai.factor_mining import FactorMiner
from quantcore_ai.risk_detector import AIRiskDetector

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

GRPC_PORT = 50057
MAX_WORKERS = 10


def _check_gpu() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


class AIEngineServicer(AIEngineServiceServicer):

    def __init__(self) -> None:
        self._factor_miner = FactorMiner()
        self._risk_detector = AIRiskDetector()
        self._predictor = None
        self._gpu_available = _check_gpu()

        try:
            from quantcore_ai.transformer_predict import TransformerPredictor
            self._predictor_cls = TransformerPredictor
        except (ImportError, RuntimeError):
            self._predictor_cls = None
            logger.info("TransformerPredictor not available")

    def HealthCheck(self, request: HealthCheckRequest, context: grpc.ServicerContext) -> HealthCheckResponse:
        return HealthCheckResponse(
            healthy=True,
            version="1.0.0",
            gpu_available=self._gpu_available,
            timestamp_ns=time.time_ns(),
        )

    def MineFactors(self, request: FactorMiningRequest, context: grpc.ServicerContext) -> FactorMiningResponse:
        if not request.close:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("close prices required")
            return FactorMiningResponse()

        try:
            n = len(request.close)
            df = pd.DataFrame({
                "close": list(request.close),
                "high": list(request.high) if request.high else list(request.close),
                "low": list(request.low) if request.low else list(request.close),
                "open": list(request.open) if request.open else list(request.close),
                "volume": list(request.volume) if request.volume else [1e6] * n,
            })

            tech_factors = self._factor_miner.generate_technical_factors(df)
            stat_factors = self._factor_miner.generate_statistical_factors(df)

            all_factors = pd.concat([tech_factors, stat_factors], axis=1)

            returns = df["close"].pct_change()
            top_n = request.top_n if request.top_n > 0 else 20
            method = request.rank_method if request.rank_method in ("ic", "mi") else "ic"
            ranked = self._factor_miner.rank_factors(all_factors, returns, method=method)
            top_names = self._factor_miner.select_top_factors(ranked, n=top_n)

            factor_results = []
            for name in top_names:
                ic_val = 0.0
                turnover_val = 0.0
                if not ranked.empty:
                    row = ranked[ranked["factor"] == name]
                    if not row.empty:
                        ic_val = float(row.iloc[0]["score"])
                        turnover_val = float(row.iloc[0]["turnover"])

                values = []
                if name in all_factors.columns:
                    vals = all_factors[name].dropna().tail(100).values
                    values = [float(v) for v in vals]

                factor_results.append(FactorResult(
                    name=name,
                    ic=ic_val,
                    turnover=turnover_val,
                    values=values,
                ))

            return FactorMiningResponse(
                factors=factor_results,
                timestamp_ns=time.time_ns(),
            )

        except Exception as e:
            logger.exception("MineFactors failed")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return FactorMiningResponse()

    def Predict(self, request: PredictRequest, context: grpc.ServicerContext) -> PredictResponse:
        if self._predictor_cls is None:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("TransformerPredictor not available (PyTorch not installed)")
            return PredictResponse()

        if not request.features:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("features required")
            return PredictResponse()

        try:
            feature_dim = request.feature_dim if request.feature_dim > 0 else 1
            seq_len = request.seq_len if request.seq_len > 0 else 30
            horizon = request.horizon if request.horizon > 0 else 1

            data = np.array(list(request.features), dtype=np.float32)
            n_total = len(data)
            if n_total % feature_dim != 0:
                n_rows = n_total // feature_dim
                data = data[: n_rows * feature_dim]
            else:
                n_rows = n_total // feature_dim
            data = data.reshape(n_rows, feature_dim)

            predictor = self._predictor_cls(
                input_dim=feature_dim,
                seq_len=seq_len,
                horizon=horizon,
            )

            predictions = predictor.predict(data)
            confidence = 0.5

            return PredictResponse(
                predictions=[float(p) for p in predictions],
                confidence=confidence,
                timestamp_ns=time.time_ns(),
            )

        except Exception as e:
            logger.exception("Predict failed")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return PredictResponse()

    def DetectRisk(self, request: RiskDetectionRequest, context: grpc.ServicerContext) -> RiskDetectionResponse:
        if not request.returns:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("returns required")
            return RiskDetectionResponse()

        try:
            returns = pd.Series(list(request.returns), dtype=float)
            prices = pd.Series(list(request.prices), dtype=float) if request.prices else pd.Series(dtype=float)
            confidence = request.confidence_level if 0 < request.confidence_level < 1 else 0.95
            window = request.anomaly_window if request.anomaly_window > 0 else 60
            threshold = request.anomaly_threshold if request.anomaly_threshold > 0 else 3.0

            z_scores = self._risk_detector.detect_anomalies(returns, window=window, threshold=threshold)
            anomaly_indices = [int(i) for i in z_scores.index[z_scores.abs() > threshold]]

            regime_changes = []
            if len(prices) > 0:
                regime_changes = self._risk_detector.detect_regime_change(prices)

            var_est = self._risk_detector.estimate_var_ml(returns.to_frame(), confidence=confidence)

            sorted_returns = returns.sort_values()
            cvar_idx = int((1 - confidence) * len(sorted_returns))
            cvar_est = float(sorted_returns.iloc[:max(cvar_idx, 1)].mean())

            return RiskDetectionResponse(
                anomaly_indices=anomaly_indices,
                regime_change_indices=regime_changes,
                var_estimate=var_est,
                cvar_estimate=cvar_est,
                timestamp_ns=time.time_ns(),
            )

        except Exception as e:
            logger.exception("DetectRisk failed")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return RiskDetectionResponse()

    def StreamAnomalies(self, request: AnomalyStreamRequest, context: grpc.ServicerContext) -> None:
        if not request.returns:
            return

        try:
            returns = pd.Series(list(request.returns), dtype=float)
            window = request.window if request.window > 0 else 60
            threshold = request.threshold if request.threshold > 0 else 3.0

            z_scores = self._risk_detector.detect_anomalies(returns, window=window, threshold=threshold)

            for idx in z_scores.index[z_scores.abs() > threshold]:
                if not context.is_active():
                    break

                z = float(z_scores.loc[idx])
                severity = "critical" if abs(z) > 5 else "warning" if abs(z) > 4 else "info"

                yield AnomalyAlert(
                    index=int(idx),
                    z_score=z,
                    value=float(returns.iloc[idx]),
                    severity=severity,
                    timestamp_ns=time.time_ns(),
                )

        except Exception:
            logger.exception("StreamAnomalies failed")


def create_server(port: int = GRPC_PORT, max_workers: int = MAX_WORKERS) -> grpc.Server:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    servicer = AIEngineServicer()
    add_AIEngineServiceServicer_to_server(servicer, server)
    server.add_insecure_port(f"[::]:{port}")
    logger.info("AI Engine gRPC server configured on port %d with %d workers", port, max_workers)
    return server


def main() -> None:
    server = create_server()
    server.start()
    logger.info("AI Engine gRPC server started on port %d", GRPC_PORT)

    def _shutdown(signum: int, frame: object) -> None:
        logger.info("Received signal %s, shutting down gracefully...", signal.Signals(signum).name)
        server.stop(grace=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    server.wait_for_termination()


if __name__ == "__main__":
    main()
