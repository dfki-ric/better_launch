from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from better_launch.launcher import BetterLaunch

def test_root_params_ignore_qualifier(
    bl: "BetterLaunch", root_params: Path
) -> None:
    result = bl.load_params(
        None, str(root_params), qualifier="robot/controller"
    )

    assert result == {
        "use_sim_time": True,
        "retries": 3,
        "robot_name": "rover",
    }


def test_plain_returns_all(
    bl: "BetterLaunch", plain_params: Path
) -> None:
    result = bl.load_params(None, str(plain_params))

    assert result == {
        "log_level": "info",
        "enabled": False,
        "limits": {"max_speed": 1.5, "max_accel": 0.25},
    }


def test_plain_filters_with_qualifier(
    bl: "BetterLaunch", plain_params: Path
) -> None:
    result = bl.load_params(None, str(plain_params), qualifier="limits")

    assert result == {
        "limits/max_speed": 1.5,
        "limits/max_accel": 0.25,
    }


def test_nested_collects_all_sections(
    bl: "BetterLaunch", nested_params: Path
) -> None:
    result = bl.load_params(None, str(nested_params), qualifier=None)

    assert result == {
        "robot/controller/ros__parameters": {"kp": 1.2, "kd": 0.1},
        "robot/monitor/ros__parameters": {"hz": 30},
    }


def test_nested_filters_under_robot(
    bl: "BetterLaunch", nested_params: Path
) -> None:
    result = bl.load_params(
        None, str(nested_params), qualifier="robot"
    )

    assert result == {
        "robot/controller/ros__parameters": {"kp": 1.2, "kd": 0.1},
        "robot/monitor/ros__parameters": {"hz": 30},
    }


def test_mixed_keeps_scalar_and_ros(
    bl: "BetterLaunch", mixed_params: Path
) -> None:
    result = bl.load_params(None, str(mixed_params), qualifier="robot")

    assert result == {
        "robot/malformed_value": 10,
        "robot/node/ros__parameters": {"enabled": True},
    }


def test_wild_includes_global_and_specific(
    bl: "BetterLaunch", wild_params: Path
) -> None:
    result = bl.load_params(None, str(wild_params))

    assert result == {
        "ros__parameters": {"default_timeout": 10},
        "fleet/alpha/ros__parameters": {"id": 1},
        "fleet/beta/ros__parameters": {"id": 2},
    }
