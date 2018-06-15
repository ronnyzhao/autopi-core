import logging
import parsing
import re
import salt.exceptions

from messaging import EventDrivenMessageClient, msg_pack


# Define the module's virtual name
__virtualname__ = "stn"

UART_WAKE_RULE_PATTERN = "^(?P<min_us>[0-9]+)-(?P<max_us>[0-9]+) us$"
UART_SLEEP_RULE_PATTERN = "^(?P<sec>[0-9]+) s$"
VOLT_LEVEL_RULE_PATTERN = "^(?P<volts>[\<\>][0-9]{1,2}\.[0-9]{1,2})V FOR (?P<sec>[0-9]+) s$"
VOLT_CHANGE_RULE_PATTERN = "^(?P<volts_diff>[+-]?[0-9]{1}\.[0-9]{1,2})V IN (?P<ms>[0-9]+) ms$"

log = logging.getLogger(__name__)

client = EventDrivenMessageClient("elm327")


def __virtual__():
    return __virtualname__


def __init__(opts):
    client.init(opts)


def _parse_rule(value, pattern):
    match = re.match(pattern, value)
    if not match:
        raise salt.exceptions.CommandExecutionError(
            "Failed to parse rule: {:s}".format(value))

    return match.groupdict()


def help():
    """
    This command.
    """

    return __salt__["sys.doc"](__virtualname__)


def _query(cmd, **kwargs):
    """
    Private helper function to perform query commands.
    """

    res = client.send_sync(msg_pack(cmd, force=True, **kwargs))
    res.pop("_type")

    lines = parsing.lines_parser(res.pop("value"))

    # Check if first line is echo
    if lines and lines[0] == cmd:
        lines.pop(0)

    if not lines:
        raise salt.exceptions.CommandExecutionError(
            "Query command '{:s}' returned no value(s)".format(cmd))

    if len(lines) == 1:
        res["value"] = lines[0]
    else:
        res["values"] = lines

    return res


def _change(cmd, **kwargs):
    """
    Private helper function to perform change settings commands.
    """

    res = _query(cmd, **kwargs)

    if res.get("value", None) != "OK":
        raise salt.exceptions.CommandExecutionError(
            "Change settings command '{:s}' failed".format(cmd))

    return res

def get_serial():
    res = _query("STDIX")
    parsing.into_dict_parser(res.pop("values"), root=res)

    return res["Serial #"]


def reset():
    res = _query("ATZ")
    if not res.get("value", "").startswith("ELM"):
        raise salt.exceptions.CommandExecutionError(
            "Reset device command failed")

    return res


def power_config():
    """
    Summarizes active PowerSave configuration.
    """

    res = _query("STSLCS")
    parsing.into_dict_parser(res.pop("values"), root=res)

    return res


def power_trigger_status():
    """
    Reports last active sleep/wakeup triggers since last reset.
    """

    res = _query("STSLLT")
    parsing.into_dict_parser(res.pop("values"), root=res)

    return res


def power_pin_polarity(invert=None):
    """
    Specify whether the pin outputs a logic LOW or HIGH in low power mode.
    """

    ret = {}

    # Read out current settings
    if invert == None:
        res = power_config()
        ret["_stamp"] = res["_stamp"]
        ret["value"] = res["pwr_ctrl"]

        return ret

    # Write settings
    res = _change("STSLPCP {:d}".format(invert))
    ret.update(res)

    # Reset for changes to take effect
    reset()

    return ret


def sleep(delay_sec, keep_conn=False):
    """
    Enter sleep mode after the specified delay time.
    The OBD connection is closed as default in order to prevent STN wake up on UART communication.
    """

    res = _change("STSLEEP {:d}".format(delay_sec), keep_conn=keep_conn)

    return res


def uart_wake(enable=None, min_us=0, max_us=30000, rule=None):
    """
    UART wakeup pulse timing configuration.
    """

    ret = {}

    # Read out current settings
    res = power_config()

    if enable == None:
        ret["_stamp"] = res["_stamp"]
        ret["value"] = res["uart_wake"]

        return ret

    # Enable/disable
    res = _change("STSLU {:s}, {:s}".format(
        "on" if res["uart_sleep"].startswith("ON") else "off",
        "on" if enable else "off")
    )
    ret.update(res)

    # Write rule settings if enabled
    if enable:
        kwargs = _parse_rule(rule, UART_WAKE_RULE_PATTERN) if rule else {
            "min_us": min_us,
            "max_us": max_us
        }
        res = _change("STSLUWP {min_us:}, {max_us:}".format(**kwargs))
        ret.update(res)

    # Reset for changes to take effect
    reset()

    return ret


def uart_sleep(enable=None, timeout_sec=1200, rule=None):
    """
    UART inactivity timeout configuration.
    """

    ret = {}

    # Read out current settings
    res = power_config()

    if enable == None:
        ret["_stamp"] = res["_stamp"]
        ret["value"] = res["uart_sleep"]

        return ret

    # Enable/disable
    res = _change("STSLU {:s}, {:s}".format(
        "on" if enable else "off",
        "on" if res["uart_wake"].startswith("ON") else "off"
    ))
    ret.update(res)

    # Write rule settings if enabled
    if enable:
        kwargs = _parse_rule(rule, UART_SLEEP_RULE_PATTERN) if rule else {
            "sec": timeout_sec
        }
        res = _change("STSLUIT {sec:}".format(**kwargs))
        ret.update(res)

    # Reset for changes to take effect
    reset()

    return ret


def volt_calibrate(value=0000):
    """
    Manual calibration of voltage measurement.
    Default value '0000' will restore to the factory calibration.
    """

    res = _change("ATCV {:04d}".format(value))

    return res


def volt_change_wake(enable=None, volts_diff="0.2", ms=1000, rule=None):
    """
    Voltage change wakeup trigger configuration.
    """

    ret = {}

    # Read out current settings
    if enable == None:
        res = power_config()
        ret["_stamp"] = res["_stamp"]
        ret["value"] = res["vchg_wake"]

        return ret

    # Enable/disable
    res = _change("STSLVG {:s}".format("on" if enable else "off"))
    ret.update(res)

    # Write rule settings if enabled
    if enable:
        kwargs = _parse_rule(rule, VOLT_CHANGE_RULE_PATTERN) if rule else {
            "volts_diff": volts_diff,
            "ms": ms
        }
        res = _change("STSLVGW {volts_diff:}, {ms:}".format(**kwargs))
        ret.update(res)

    # Reset for changes to take effect
    reset()

    return ret


def volt_level_wake(enable=None, volts=">13.2", sec=1, rule=None):
    """
    Voltage level wakeup trigger configuration.
    """

    ret = {}

    # Read out current settings
    res = power_config()

    if enable == None:
        ret["_stamp"] = res["_stamp"]
        ret["value"] = res["vl_wake"]

        return ret

    # Enable/disable
    res = _change("STSLVL {:s}, {:s}".format(
        "on" if res["vl_sleep"].startswith("ON") else "off",
        "on" if enable else "off"
    ))
    ret.update(res)

    # Write rule settings if enabled
    if enable:
        kwargs = _parse_rule(rule, VOLT_LEVEL_RULE_PATTERN) if rule else {
            "volts": volts,
            "sec": sec
        }
        res = _change("STSLVLW {volts:}, {sec:}".format(**kwargs))
        ret.update(res)

    # Reset for changes to take effect
    reset()

    return ret


def volt_level_sleep(enable=None, volts="<13.0", sec=600, rule=None):
    """
    Voltage level sleep trigger configuration.
    """

    ret = {}

    # Read out current settings
    res = power_config()

    if enable == None:
        ret["_stamp"] = res["_stamp"]
        ret["value"] = res["vl_sleep"]

        return ret

    # Enable/disable
    res = _change("STSLVL {:s}, {:s}".format(
        "on" if enable else "off",
        "on" if res["vl_wake"].startswith("ON") else "off"
    ))
    ret.update(res)

    # Write rule settings if enabled
    if enable:
        kwargs = _parse_rule(rule, VOLT_LEVEL_RULE_PATTERN) if rule else {
            "volts": volts,
            "sec": sec
        }
        res = _change("STSLVLS {volts:}, {sec:}".format(**kwargs))
        ret.update(res)

    # Reset for changes to take effect
    reset()

    return ret