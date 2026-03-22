import sys
from types import ModuleType
from unittest.mock import MagicMock


# Mock rclpy and other ROS2 dependencies before importing better_launch
def mock_package(name):
    m = ModuleType(name)
    m.__path__ = []
    sys.modules[name] = m
    return m


mock_rclpy = mock_package("rclpy")
mock_rclpy.Parameter = MagicMock()
sys.modules["rclpy.node"] = MagicMock()
sys.modules["rclpy.qos"] = MagicMock()
sys.modules["rclpy.action"] = MagicMock()
sys.modules["rclpy.parameter"] = MagicMock()
sys.modules["rclpy.executors"] = MagicMock()
sys.modules["rclpy.logging"] = MagicMock()
sys.modules["rclpy.signals"] = MagicMock()
sys.modules["rclpy.context"] = MagicMock()

mock_package("ament_index_python")
sys.modules["ament_index_python.packages"] = MagicMock()

mock_package("launch")
sys.modules["launch.actions"] = MagicMock()
sys.modules["launch.launch_description_sources"] = MagicMock()
sys.modules["launch.substitutions"] = MagicMock()
sys.modules["launch.conditions"] = MagicMock()
sys.modules["launch.event_handlers"] = MagicMock()
sys.modules["launch.events"] = MagicMock()

mock_package("launch_ros")
sys.modules["launch_ros.actions"] = MagicMock()
sys.modules["launch_ros.substitutions"] = MagicMock()

mock_package("lifecycle_msgs")
sys.modules["lifecycle_msgs.msg"] = MagicMock()
sys.modules["lifecycle_msgs.srv"] = MagicMock()

mock_package("rcl_interfaces")
sys.modules["rcl_interfaces.msg"] = MagicMock()
sys.modules["rcl_interfaces.srv"] = MagicMock()

mock_package("std_msgs")
sys.modules["std_msgs.msg"] = MagicMock()

mock_package("std_srvs")
sys.modules["std_srvs.srv"] = MagicMock()

mock_package("ros2param")
sys.modules["ros2param.api"] = MagicMock()

mock_package("osrf_pycommon")
sys.modules["osrf_pycommon.process_utils"] = MagicMock()

mock_click = mock_package("click")
mock_click.Option = MagicMock()
mock_click.Context = MagicMock()
mock_click.Parameter = MagicMock()
mock_click.Command = MagicMock()
mock_click.types = MagicMock()
mock_click.pass_context = lambda x: x

mock_doc = mock_package("docstring_parser")
mock_doc.parse = MagicMock()

import pytest
from better_launch.utils.click import parse_node_params, args_to_dict


def test_parse_node_params():
    # empty kwargs
    assert parse_node_params({}) == ({}, {})

    # no node params
    kwargs = {"foo": "bar", "baz": 1}
    assert parse_node_params(kwargs) == (kwargs, {})

    # single node param
    kwargs = {"node1.param1": "val1", "foo": "bar"}
    assert parse_node_params(kwargs) == ({"foo": "bar"}, {"node1": {"param1": "val1"}})

    # multiple params same node
    kwargs = {"node1.param1": "val1", "node1.param2": 2}
    assert parse_node_params(kwargs) == ({}, {"node1": {"param1": "val1", "param2": 2}})

    # multiple nodes
    kwargs = {"node1.p1": 1, "node2.p2": 2}
    assert parse_node_params(kwargs) == ({}, {"node1": {"p1": 1}, "node2": {"p2": 2}})

    # mixed kwargs
    kwargs = {"node1.p1": 1, "foo": "bar", "node2.p2": 2, "baz": 3}
    assert parse_node_params(kwargs) == (
        {"foo": "bar", "baz": 3},
        {"node1": {"p1": 1}, "node2": {"p2": 2}},
    )

    # various value types
    kwargs = {
        "n.s": "string",
        "n.f": 1.5,
        "n.b": True,
        "n.l": [1, 2, 3],
        "n.d": {"a": 1},
    }
    assert parse_node_params(kwargs) == (
        {},
        {"n": {"s": "string", "f": 1.5, "b": True, "l": [1, 2, 3], "d": {"a": 1}}},
    )

    # nested param names
    kwargs = {"node1.param.subparam": "val"}
    assert parse_node_params(kwargs) == ({}, {"node1": {"param.subparam": "val"}})


def test_args_to_dict():
    # basic parsing
    args = ["--foo", "bar", "--baz", "1.0"]
    assert args_to_dict(args) == {"foo": "bar", "baz": 1.0}

    # JSON type inference
    args = [
        "--s",
        "str",
        "--i",
        "1",
        "--f",
        "1.5",
        "--b",
        "true",
        "--l",
        "[1, 2]",
        "--d",
        '{"a": 1}',
    ]
    assert args_to_dict(args) == {
        "s": "str",
        "i": 1,
        "f": 1.5,
        "b": True,
        "l": [1, 2],
        "d": {"a": 1},
    }

    # missing value error
    with pytest.raises(ValueError, match="Missing value for argument '--foo'"):
        args_to_dict(["--foo"])

    # no-dash-prefix error
    with pytest.raises(ValueError, match="Argument 'foo' does not start with '-'"):
        args_to_dict(["foo", "bar"])
