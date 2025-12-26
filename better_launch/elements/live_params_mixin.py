from typing import Any

from rclpy.parameter import Parameter

try:
    # Jazzy
    from rclpy.parameter import parameter_value_to_python
except ImportError:
    # Humble
    from ros2param.api import get_value as get_value_humble

    def parameter_value_to_python(p: Parameter):
        # keyword args only
        return get_value_humble(parameter_value=p)


class LiveParamsMixin:
    """Mixin class to add interactions with ROS parameters for running nodes. This class must be mixed in with an object providing a `fullname` member."""

    def __init__(self):
        super().__init__()

        # NOTE: we should avoid storing services as they rely on the ros_adapter staying alive, as
        # it can be terminated for performance reasons. Better to use call_service instead.
        self._list_params_req_type = None
        self._get_params_req_type = None
        self._set_params_req_type = None
        self._set_params_atomic_req_type = None

    def list_live_params(self, *, timeout: float = 5.0) -> list[str]:
        """List the names of the ROS parameters this node has registered.

        Note that this is different from the `params` used to start the node. This method will directly query the ROS node for its parameters, while `params` is used to pass arguments on startup.

        Parameters
        ----------
        timeout : float, optional
            How long to wait for the service to connect.

        Returns
        -------
        list[str]
            A list of this node's ROS parameters.

        Raises
        ------
        TimeoutError
            If the service fails to connect.
        """
        from better_launch import BetterLaunch

        bl = BetterLaunch.instance()

        if not self._list_params_req_type:
            self._list_params_req_type = bl.get_ros_message_type(
                "rcl_interfaces/srv/ListParameters"
            )

        res = bl.call_service(
            f"{self.fullname}/list_parameters",
            self._list_params_req_type,
            timeout=timeout,
        )

        return res.result.names

    def get_live_params(self, *params: str, timeout: float = 5.0) -> dict[str, Any]:
        """Retrieves the values for the specified ROS parameters of this node. If no parameters are provided, all parameters will be listed.

        Note that this is different from the `params` used to start the node. This method will directly query the ROS node for its parameters, while `params` is used to pass arguments on startup.

        Parameters
        ----------
        *params : str
            ROS parameter names to retrieve.
        timeout : float, optional
            How long to wait for the service to connect.

        Returns
        -------
        Any
            The names and values of the ROS parameters of this node as specified.

        Raises
        ------
        TimeoutError
            If the service fails to connect.
        """
        from better_launch import BetterLaunch

        bl = BetterLaunch.instance()

        if not self._get_params_req_type:
            self._get_params_req_type = bl.get_ros_message_type(
                "rcl_interfaces/srv/GetParameters"
            )
            self._get_params_srv = bl.service_client(
                f"{self.fullname}/get_parameters",
                "rcl_interfaces/srv/GetParameters",
                timeout=timeout,
            )

        if not params:
            params = self.list_live_params(timeout=timeout)

        res = bl.call_service(
            f"{self.fullname}/get_parameters",
            self._get_params_req_type,
            request_args={"names": params},
            timeout=timeout,
        )

        return {
            name: parameter_value_to_python(pval)
            for name, pval in zip(params, res.values)
        }

    def set_live_params(
        self, params: dict[str, Any], *, timeout: float = 5.0
    ) -> dict[str, bool]:
        """Sets the specified ROS parameters on this node.

        Note that this is different from the `params` used to start the node. This method will directly query the ROS node for its parameters, while `params` is used to pass arguments on startup.

        Parameters
        ----------
        params : dict[str, Any]
            The parameters to update.
        timeout : float, optional
            How long to wait for the service to connect.

        Returns
        -------
        dict[str, bool]:
            A dict showing which parameter updates succeeded.

        Raises
        ------
        TimeoutError
            If the service fails to connect.
        """
        from better_launch import BetterLaunch

        bl = BetterLaunch.instance()

        if not self._set_params_req_type:
            self._set_params_req_type = bl.get_ros_message_type(
                "rcl_interfaces/srv/SetParameters"
            )

        res = bl.call_service(
            f"{self.fullname}/set_parameters",
            self._set_params_req_type,
            request_args={
                "parameters": [
                    Parameter(key, value=val).to_parameter_msg()
                    for key, val in params.items()
                ]
            },
            timeout=timeout,
        )

        return {
            param: item.successful for param, item in zip(params.keys(), res.results)
        }

    def set_live_params_atomic(
        self, params: dict[str, Any], *, timeout: float = 5.0
    ) -> bool:
        """Sets the specified ROS parameters on this node. No updates will be performed if any of the operations fail.

        Note that this is different from the `params` used to start the node. This method will directly query the ROS node for its parameters, while `params` is used to pass arguments on startup.

        Parameters
        ----------
        params : dict[str, Any]
            The parameters to update.
        timeout : float, optional
            How long to wait for the service to connect.

        Returns
        -------
        bool:
            True if all updates succeeded, False otherwise.

        Raises
        ------
        TimeoutError
            If the service fails to connect.
        """
        from better_launch import BetterLaunch

        bl = BetterLaunch.instance()

        if not self._set_params_atomic_req_type:
            self._set_params_atomic_req_type = bl.get_ros_message_type(
                "rcl_interfaces/srv/SetParametersAtomically"
            )

        res = bl.call_service(
            f"{self.fullname}/set_parameters_atomically",
            self._set_params_atomic_req_type,
            request_args={
                "parameters": [
                    Parameter(key, value=val).to_parameter_msg()
                    for key, val in params.items()
                ]
            },
            timeout=timeout,
        )

        return res.successful
