#!/usr/bin/env python3
from better_launch import BetterLaunch, launch_this
from std_srvs.srv import Trigger
import json
from pathlib import Path


def run(bl: BetterLaunch, params: dict) -> str:
    node_path = bl.find("better_launch", "param_echo_node.py")
    node = bl.node(
        "better_launch",
        node_path,
        "param_node",
        params=params,
    )

    svc = Path(node.namespace) / "get_params"
    res = bl.call_service(str(svc), Trigger).message
    found = json.loads(res)
    print(f"Found: {found}")

    node.shutdown("terminated")
    return found


def verify(bl: BetterLaunch, found: dict, required: list[str], forbidden: list[str]) -> bool:
    valid = True

    for item in required:
        if item not in found:
            bl.logger.error(f"### Required item '{item}' not found")
            valid = False

    for item in forbidden:
        if item in found:
            bl.logger.error(f"### Forbidden item '{item}' found")
            valid = False

    if valid:
        bl.logger.info("### Found params valid")

    return valid


@launch_this
def do_the_deed():
    bl = BetterLaunch()

    #params = bl.find("better_launch", "test_params.yaml")
    params = bl.load_params("better_launch", "test_params.yaml")
    print(f"Params: {params}")

    found = run(bl, params)
    verify(bl, found, ["always_around"], ["pleasure_to_bug_you"])
    
    with bl.group("test"):
        found = run(bl, params)
        verify(bl, found, ["always_around", "pleasure_to_bug_you"], [])
