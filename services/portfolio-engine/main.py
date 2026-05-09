import logging
import signal
import sys
from pathlib import Path

import uvloop

uvloop.install()

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quantcore_portfolio.account import AccountManager
from quantcore_portfolio.pnl import PnLCalculator
from quantcore_portfolio.server import create_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

GRPC_PORT = 50055
MAX_WORKERS = 10


def main() -> None:
    account_manager = AccountManager()
    pnl_calculator = PnLCalculator()

    server = create_server(
        account_manager=account_manager,
        pnl_calculator=pnl_calculator,
        port=GRPC_PORT,
        max_workers=MAX_WORKERS,
    )
    server.start()
    logger.info("Portfolio Engine gRPC server started on port %d", GRPC_PORT)

    def _shutdown(signum: int, frame: object) -> None:
        logger.info("Received signal %s, shutting down gracefully...", signal.Signals(signum).name)
        server.stop(grace=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    server.wait_for_termination()


if __name__ == "__main__":
    main()
