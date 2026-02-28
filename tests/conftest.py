import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from better_launch.launcher import BetterLaunch


def mock_package(name: str):
    pkg = MagicMock()
    pkg.__path__ = []
    sys.modules[name] = pkg
    return pkg


def mock_ros_dependencies() -> None:
    # Mock ROS dependencies before importing better_launch.
    mock_package("rclpy")
    sys.modules["rclpy.node"] = MagicMock()
    sys.modules["rclpy.logging"] = MagicMock()
    sys.modules["rclpy.qos"] = MagicMock()
    sys.modules["rclpy.task"] = MagicMock()
    sys.modules["rclpy.executors"] = MagicMock()
    sys.modules["rclpy.parameter"] = MagicMock()

    mock_package("ament_index_python")
    sys.modules["ament_index_python.packages"] = MagicMock()

    mock_package("lifecycle_msgs")
    sys.modules["lifecycle_msgs.msg"] = MagicMock()
    sys.modules["lifecycle_msgs.srv"] = MagicMock()

    mock_package("launch")
    sys.modules["launch.actions"] = MagicMock()
    sys.modules["launch.launch_description_sources"] = MagicMock()


@pytest.fixture(scope="session")
def better_launch_cls() -> type["BetterLaunch"]:
    mock_ros_dependencies()
    from better_launch.launcher import BetterLaunch

    return BetterLaunch


@pytest.fixture
def bl(better_launch_cls: type["BetterLaunch"]) -> "BetterLaunch":
    inst = cast("BetterLaunch", MagicMock(spec=better_launch_cls))
    inst.logger = MagicMock()
    inst.find = better_launch_cls.find.__get__(inst, better_launch_cls)
    inst.load_params = better_launch_cls.load_params.__get__(inst, better_launch_cls)
    inst._value_to_yaml = better_launch_cls._value_to_yaml.__get__(inst, better_launch_cls)
    return inst


FIXTURE_DIR = Path(__file__).parent / "config_examples"


@pytest.fixture
def root_params():
    return FIXTURE_DIR / "root.yaml"


@pytest.fixture
def plain_params():
    return FIXTURE_DIR / "plain.yaml"


@pytest.fixture
def nested_params():
    return FIXTURE_DIR / "nested.yaml"


@pytest.fixture
def wild_params():
    return FIXTURE_DIR / "wild.yaml"


@pytest.fixture
def mixed_params():
    return FIXTURE_DIR / "mixed.yaml"
