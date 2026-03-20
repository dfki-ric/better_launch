#!/usr/bin/env python3
from pprint import pformat
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rcl_interfaces.msg import SetParametersResult


class ParamEchoNode(Node):
    def __init__(self):
        super().__init__(
            "param_printer",
            allow_undeclared_parameters=True,
            automatically_declare_parameters_from_overrides=True,
        )

        params = [
            f"### [PARAM] {name} = {p.value!r}"
            for name, p in self.get_parameters_by_prefix("").items()
        ]
        self.get_logger().info(pformat(params, width=120))

        self.add_on_set_parameters_callback(self._on_params_set)

    def _on_params_set(self, params: list[Parameter]) -> SetParametersResult:
        for p in params:
            self.get_logger().info(f"### [UPDATE] {p.name} = {p.value!r}")
        return SetParametersResult(successful=True)


def main(args=None):
    rclpy.init(args=args)
    node = ParamEchoNode()
    rclpy.spin(node)
    rclpy.shutdown()


if __name__ == "__main__":
    main()