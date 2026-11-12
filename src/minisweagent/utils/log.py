import logging


def _setup_root_logger() -> None:
    logger = logging.getLogger("minisweagent")
    logger.setLevel(logging.DEBUG)
    _handler = logging.StreamHandler()
    _formatter = logging.Formatter("%(name)s: %(levelname)s: %(message)s")
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)


_setup_root_logger()
logger = logging.getLogger("minisweagent")


__all__ = ["logger"]
