import logging

from messaging import EventDrivenMessageClient, msg_pack


__virtualname__ = "tracking"

log = logging.getLogger(__name__)

client = EventDrivenMessageClient("tracking")


def __virtual__():
    return __virtualname__


def __init__(opts):
    client.init(opts)


def help():
    """
    This command.
    """

    return __salt__["sys.doc"](__virtualname__)


def status(**kwargs):
    """
    Get current status.
    """

    return client.send_sync(msg_pack(_handler="status", **kwargs))


def manage(*args, **kwargs):
    """
    Example: tracking.manage worker list *
    """

    return client.send_sync(msg_pack(*args, _workflow="manage", **kwargs))

