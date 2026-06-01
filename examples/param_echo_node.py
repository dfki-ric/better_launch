#!/usr/bin/env python3
import json

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rcl_interfaces.msg import SetParametersResult
from std_srvs.srv import Trigger


class ParamEchoNode(Node):
    def __init__(self):
        super().__init__(
            "param_echo_node",
            allow_undeclared_parameters=True,
            automatically_declare_parameters_from_overrides=True,
        )

        self.params = {
            name: param.value
            for name, param in self.get_parameters_by_prefix("").items()
        }
        self._svc = self.create_service(
            Trigger, "get_params", self._get_params_callback
        )

        params_str = "\n".join([
            f"  [PARAM] {name} = {param!r}" for name, param in self.params.items()
        ])
        self.get_logger().info(params_str)

        self.add_on_set_parameters_callback(self._on_params_set)

    def _on_params_set(self, params: list[Parameter]) -> SetParametersResult:
        for p in params:
            self.get_logger().info(f"  [UPDATE] {p.name} = {p.value!r}")
            self.params[p.name] = p.value

        return SetParametersResult(successful=True)

    def _get_params_callback(self, req, res) -> None:
        res.message = json.dumps(self.params)
        res.success = True
        return res


def main(args=None):
    rclpy.init(args=args)
    node = ParamEchoNode()
    rclpy.spin(node)
    rclpy.shutdown()


if __name__ == "__main__":
    main()
