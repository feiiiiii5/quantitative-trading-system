import asyncio
import logging
import signal
import sys

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

from quantcore_strategy.server import serve

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

_GRPC_PORT = 50054


async def main() -> None:
    server, servicer = await serve(port=_GRPC_PORT)

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Received shutdown signal")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    logger.info("Strategy Engine running on port %d (pid=%d)", _GRPC_PORT, sys.getpid())
    logger.info("Event loop: %s", type(loop).__module__)

    await stop_event.wait()

    logger.info("Shutting down gracefully...")
    await servicer.graceful_shutdown()
    await server.stop(grace=10)
    logger.info("Server stopped")


if __name__ == "__main__":
    asyncio.run(main())
