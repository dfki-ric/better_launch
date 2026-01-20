from typing import Any, Iterable
import signal
import time
import re
from threading import Event
from rclpy import Parameter
# NOTE message types are imported late because the composer is not always used

from better_launch.utils.better_logging import LogSink
from .abstract_node import AbstractNode
from .live_params_mixin import LiveParamsMixin
from .lifecycle_manager import LifecycleStage


class Component(AbstractNode, LiveParamsMixin):
    def __init__(
        self,
        composer: "Composer",
        package: str,
        plugin: str,
        name: str,
        namespace: str,
        *,
        output: LogSink | Iterable[LogSink] | Iterable[str] | str = LogSink.SCREEN,
        remaps: dict[str, str] = None,
        params: str | dict[str, Any] = None,
    ):
        """Representation of a component, a composable object that can be loaded into a running process. Components will always use their composer's namespace.

        Note that in ROS2 launch files you can reference existing composers by name when creating components. This is a clutch because ROS2 does not have a way to retrieve a reference to an already existing node. Since in better_launch we have actual node instances, referring to composers by name is not supported. Use :py:meth:`BetterLaunch.component` or construct your own component and pass a :py:class:`Composer` instance.

        Also note that since components are loaded via a service call there are some additional restrictions on the types of `params`. In particular, they must be compatible with the `ROS2 Parameter message type <https://github.com/ros2/rcl_interfaces/blob/rolling/rcl_interfaces/msg/ParameterValue.msg>`_. This is *not* verified on construction.

        In addition, note that new nodes created by a component are using the composer's remaps. See the `related issue <https://github.com/ros2/rclcpp/issues/2404>`_ in rclcpp.

        .. seealso::

            `ROS2 About Composition <https://docs.ros.org/en/jazzy/Concepts/Intermediate/About-Composition.html>`_

        Parameters
        ----------
        composer : Composer
            The composer this component will be associated with.
        package : str
            The package providing this component.
        plugin : str
            The special string that can be used for loading the component.
        name : str
            The name of the component in ROS.
        namespace : str
            The node's namespace. Must be absolute, i.e. start with a '/'.
        remaps : dict[str, str], optional
            Tells the node to replace any topics it wants to interact with according to the provided dict.
        params : str | dict[str, Any], optional
            Any arguments you want to provide to the node. These are the args you would typically have to declare in your launch file. A string will be interpreted as a path to a yaml file which will be lazy loaded using :py:meth:`BetterLaunch.load_params`.
        output : LogSink | Iterable[LogSink] | Iterable[str] | str, optional
            Determines if and where this node's output should be directed. Common choices are `screen` to print to terminal, `log` to write to a common log file, `own_log` to write to a node-specific log file, and `none` to not write any output anywhere. See :py:meth:`configure_logger` for details.

        Raises
        ------
        RuntimeError
            If the component does not reside in the same namespace as its composer.
        """
        if not namespace.startswith(composer.namespace):
            raise ValueError("Components must reside in the same namespace as their composer.")

        super().__init__(package, plugin, name, namespace, remaps, params, output=output)

        self._component_id: int = None
        self._composer = composer

        self._terminated_event = Event()
        self._terminated_event.set()

    @property
    def composer(self) -> "Composer":
        """The composer this component is associated with."""
        return self._composer

    @property
    def component_id(self) -> int:
        """The ID this component got assigned when it was loaded into the composer. Will be None if the component is not loaded."""
        return self._component_id

    @property
    def is_loaded(self) -> bool:
        """True if the component is loaded, False otherwise."""
        return self._component_id is not None

    @property
    def plugin(self) -> str:
        """The special string that is used for loading the component. :py:meth:`executable` will return the same."""
        return self._exec

    @property
    def is_running(self) -> bool:
        if not self.is_loaded:
            return False

        return self.is_ros2_connected()

    def join(self, timeout: float = None) -> None:
        self._terminated_event.wait(timeout)

    def start(
        self,
        use_intra_process_comms: bool = True,
        **composer_extra_params,
    ) -> None:
        """Load this component into its composer.

        Additional keyword arguments will be passed as ROS parameters to the component.

        Parameters
        ----------
        use_intra_process_comms : bool, optional
            If True, the component will use intra process communication for exchanging messages with other components within the same composer.
        """
        self._component_id = self.composer.load_component(
            self,
            use_intra_process_comms=use_intra_process_comms,
            **composer_extra_params,
        )
        self._terminated_event.clear()

    def shutdown(self, reason: str, signum: int = signal.SIGTERM, timeout: float = 0.0) -> None:
        """Unload this component if it was loaded.

        Parameters
        ----------
        reason : str
            A human-readable string describing why the component is being unloaded.
        signum : int, optional
            Ignored for components.
        """
        if not self.is_loaded:
            return

        if signum == signal.SIGTERM and self._lifecycle_manager:
            try:
                self._lifecycle_manager.transition(LifecycleStage.FINALIZED)
            except Exception as e:
                self.logger.warning(f"Lifecycle transition to FINALIZED failed: {e}")

        self.logger.warning(f"Unloading component {self.name}: {reason}")
        self.composer.unload_component(self, timeout=timeout)
        self._component_id = None
        self._terminated_event.set()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__} {self.package}/{self.plugin}"


class Composer(AbstractNode):
    @classmethod
    def is_composer(cls, node: AbstractNode, timeout: float = 0.0) -> bool:
        """Checks whether a node provides services for loading components.

        For a node to be a composer, it must be running, be registered with ROS and offer the ROS composition services. This method **only** checks whether one of the key services is present.

        If a timeout is specified, the check will be repeated until it succeeds or the specified amount of time has passed. This is to ensure that a freshly started node had enough time to create its topics, especially on slower devices. 

        Parameters
        ----------
        node : AbstractNode
            The node object to check.
        timeout : float
            How long to wait at most for the composition services to appear. Wait forever if None.

        Returns
        -------
        bool
            True if the node supports loading components, False otherwise.
        """
        now = time.time()
        while True:
            # Check if the node provides one of the key composition services
            services = node.get_published_services()
            for srv_name, srv_types in services.items():
                if (
                    srv_name == f"{node.fullname}/_container/load_node"
                    and "composition_interfaces/srv/LoadNode" in srv_types
                ):
                    return True

            if timeout is not None and time.time() > now + timeout:
                break

            time.sleep(0.1)

        return False

    def __init__(
        self,
        wrapped_node: AbstractNode,
        *,
        component_remaps: dict[str, str] = None,
        output: LogSink | Iterable[LogSink] | Iterable[str] | str = LogSink.SCREEN,
    ):
        """A composer is a special ROS2 node that can host other nodes (:py:class:`Component`) within the same process, reducing overhead and enabling efficient intra process communication for message exchange.

        As it is possible to reuse already running composers (even without a reference to the actual process), this is merely a wrapper around another :py:class:`AbstractNode` providing additional functionality. The wrapped node instance is typically a :py:class:`Node` or :py:class:`ForeignNode`. See :py:meth:`BetterLaunch.compose` for the most common use cases. 

        Note that new nodes created by a component are using the composer's remaps. See the `related issue <https://github.com/ros2/rclcpp/issues/2404>`_ in rclcpp.

        .. seealso::

            `ROS2 About Composition <https://docs.ros.org/en/jazzy/Concepts/Intermediate/About-Composition.html>`_

        Parameters
        ----------
        wrapped_node : AbstractNode
            A representation of the actual ROS2 node that will be managed by this composer. This is usually a :py:class:`Node` or :py:class:`ForeignNode` instance.
        component_remaps : dict[str, str], optional
            Any remaps you want to apply to all *components* loaded into this composer.
        output : LogSink | Iterable[LogSink] | Iterable[str] | str, optional
            Determines if and where this node's output should be directed. Common choices are `screen` to print to terminal, `log` to write to a common log file, `own_log` to write to a node-specific log file, and `none` to not write any output anywhere. See :py:meth:`configure_logger` for details.

        Raises
        ------
        ValueError
            If the composer mode is not recognized.
        """
        super().__init__(
            wrapped_node.package,
            wrapped_node.executable,
            wrapped_node.name,
            wrapped_node.namespace,
            output=output,
        )

        self._wrapped_node = wrapped_node

        pkg = self._wrapped_node.package
        m = re.match(r"rcl(.+)_components", pkg)
        if m:
            self._language = m.group(1)
        else:
            self._language = None

        # Remaps are not useful for a composable node, but we can forward them to the components
        self._component_remaps: dict[str, str] = component_remaps or {}
        self._managed_components: dict[int, Component] = {}

    @property
    def is_running(self) -> bool:
        return self._wrapped_node.is_running

    @property
    def is_lifecycle(self) -> bool:
        """Composers are not lifecycle nodes."""
        return False

    @property
    def language(self) -> str:
        """The implementation language of this composer, usually `cpp` or `py`. Corresponds to this composer's package (e.g. *rclcpp_composition*), but will be `None` if it's a custom implementation."""
        self._language

    @property
    def managed_components(self) -> list[Component]:
        """The components that were explicitly loaded through this composer instance. This will not contain components that have been loaded via external service calls."""
        return list(self._managed_components.values())

    def get_live_components(self) -> dict[int, str]:
        """Use a service call to retrieve the components currently loaded into this composer and their IDs.

        Returns
        -------
        dict[int, str]
            A dict mapping component IDs to full node names.
        """
        if not self._wrapped_node.is_running:
            return []

        from better_launch import BetterLaunch
        from composition_interfaces.srv import ListNodes

        bl = BetterLaunch.instance()
        res = bl.call_service(
            f"{self.fullname}/_container/list_nodes",
            ListNodes,
            timeout=5.0,
        )

        return [(uid, name) for uid, name in zip(res.unique_ids, res.full_node_names)]

    def join(self, timeout: float = None) -> None:
        self._wrapped_node.join(timeout)

    def start(self, service_timeout: float = 5.0) -> None:
        """Start this node. Once this succeeds, :py:meth:`is_running` will return True.

        Parameters
        ----------
        service_timeout : float, optional
            How long to wait for each composition service to appear (3 total). Wait forever if set negative. Don't check at all if None or 0.
        """
        try:
            self._wrapped_node.start()
        except NotImplementedError:
            pass

        if service_timeout not in (0.0, None):
            # Check if all expected services are present
            from better_launch import BetterLaunch
            from composition_interfaces.srv import ListNodes, LoadNode, UnloadNode

            services = {
                f"{self.fullname}/_container/list_nodes": ListNodes,
                f"{self.fullname}/_container/load_node": LoadNode,
                f"{self.fullname}/_container/unload_node": UnloadNode
            }

            bl = BetterLaunch.instance()
            for topic, srv_type in services.items():
                srv = bl.service_client(topic, srv_type, timeout=service_timeout)
                srv.destroy()

    def shutdown(self, reason: str, signum: int = signal.SIGTERM, timeout: float = None) -> None:
        """This will shutdown the composer node. Unloading any loaded components is left to the actual composer implementation.

        Parameters
        ----------
        reason : str
            A human-readable string describing why the composer and its components are being shutdown.
        signum : int, optional
            The signal that should be send to the composer.
        timeout : float, optional
            How long to wait for each component and the composer to shutdown before returning. Don't wait if timeout is 0.0. Wait forever if timeout is None. 

        Raises
        ------
        TimeoutError
            If a timeout > 0 was set and any of the components or the composer did not shutdown before then.
        """
        if not self._wrapped_node.is_running:
            # Clear up internal states
            for comp in self.managed_components:
                comp._component_id = None
            self.managed_components.clear()
            return

        for comp in self.managed_components:
            try:
                comp.shutdown(reason, signum, timeout)
            except Exception as e:
                self.logger.warning(f"Failed to unload component {comp}: {e}")

        try:
            self._wrapped_node.shutdown(reason, signum, timeout)
        except NotImplementedError:
            pass
        
        self.managed_components.clear()

    def load_component(
        self,
        component: Component,
        use_intra_process_comms: bool = True,
        **composer_extra_params: dict,
    ) -> int:
        """Load this component into its composer.

        Additional keyword arguments will be passed as ROS parameters to the component. If the component is not associated with this composer yet, a warning will be logged and its association will be updated.

        Note that since components are loaded via a service call that there are some additional restrictions on the types of :py:meth:`Component.params` and `composer_extra_params`. In particular, they must be compatible with the `ROS2 Parameter message type <https://github.com/ros2/rcl_interfaces/blob/rolling/rcl_interfaces/msg/ParameterValue.msg>`_.

        Also note that new nodes created by a component are using the composer's remaps. See the `related issue <https://github.com/ros2/rclcpp/issues/2404>`_ in rclcpp.

        Parameters
        ----------
        component: Component
            The component to load.
        use_intra_process_comms : bool, optional
            If True, the component will use intra process communication for exchanging messages with other components within the same composer.

        Returns
        -------
        int
            The ID the component got assigned by ROS.

        Raises
        ------
        ValueError
            If this composer is not running, if the component is already loaded, or if the parameters could not be serialized.
        RuntimeError
            If loading the component failed.
        """
        if not self.is_running:
            self.logger.error("Cannot load components into stopped composer")
            return -1

        if component.is_running:
            self.logger.error("Cannot load an already running component")
            return -1

        if component.composer != self:
            self.logger.warning(
                f"Component {component.name} was created for a different Composer, updating reference"
            )
            component._composer = self

        # Reference: https://github.com/ros2/launch_ros/blob/rolling/launch_ros/launch_ros/actions/load_composable_nodes.py
        from composition_interfaces.srv import LoadNode

        req = LoadNode.Request()
        req.package_name = component.package
        req.plugin_name = component.plugin
        req.node_name = component.name
        req.node_namespace = component.namespace
        req.parameters = []

        try:
            req.parameters.extend(
                [
                    # Parameter will initialize based on the value's type
                    Parameter(name=k, value=v).to_parameter_msg()
                    for k, v in component._flat_params().items()
                ]
            )
        except Exception as e:
            raise ValueError(f"Could not serialize component parameters: {e}") from e

        remaps = dict(self._component_remaps)
        remaps.update(component.remaps)
        req.remap_rules = [f"{src}:={dst}" for src, dst in remaps.items()]

        composer_params = {}
        composer_params.update(composer_extra_params)
        composer_params["use_intra_process_comms"] = use_intra_process_comms
        try:
            req.extra_arguments = [
                Parameter(name=k, value=v).to_parameter_msg()
                for k, v in composer_params.items()
            ]
        except Exception as e:
            raise ValueError(f"Could not serialize extra parameters: {e}") from e

        # Call the load_node service
        from better_launch import BetterLaunch
        
        self.logger.info(f"Loading component {component.name}")
        bl = BetterLaunch.instance()

        res = bl.call_service(
            f"{self.fullname}/_container/load_node",
            LoadNode,
            req,
            timeout=5.0,
        )

        if res.success:
            if res.full_node_name:
                namespace, name = res.full_node_name.rsplit("/", maxsplit=1)
                component._namespace = namespace
                component._name = name

            # Component.start() takes care of this, but the user can call load_component directly
            cid = res.unique_id
            component._component_id = cid
            component._terminated_event.clear()

            self._managed_components[cid] = component
            return cid
        else:
            self.logger.error(
                f"Loading component {component} failed: {res.error_message}"
            )
            raise RuntimeError(res.error_message)

    def unload_component(self, component: Component | int, timeout: float = None) -> None:
        """Unload the specified component, essentially stopping its node.

        Note that an unload request will be issued even if the component reports it is not loaded.

        Parameters
        ----------
        component : Component | int
            The component or a component's ID to stop.
        timeout : float, optional
            How long to wait for the component to be unloaded before returning. Don't wait if timeout is 0.0. Wait forever if timeout is None. 

        Returns
        -------
        bool
            True if unloading the component succeeded, False otherwise.

        Raises
        ------
        ValueError
            If this composer is not running.
        KeyError
            If the provided component has not been loaded into this node
        """
        if not self.is_running:
            raise ValueError("Cannot unload components from stopped composer")

        if isinstance(component, Component):
            cid = component.component_id
        else:
            cid = component
        
        if cid in self._managed_components:
            cname = self._managed_components[cid].name
        else:
            cname = self.get_live_components()[cid]

        from composition_interfaces.srv import UnloadNode

        req = UnloadNode.Request()
        req.unique_id = cid

        self.logger.warning(f"Unloading component {cid} ({cname})")

        from better_launch import BetterLaunch

        bl = BetterLaunch.instance()
        res = bl.call_service(
            f"{self.fullname}/_container/unload_node",
            UnloadNode,
            req,
            timeout=5.0,
        )

        if res.success:
            # Usually Component.shutdown() takes care of this, but the user can call 
            # unload_component() directly
            if isinstance(component, Component):
                component._component_id = None
                component._terminated_event.set()

            self._managed_components.pop(cid, None)
            return True

        self.logger.error(
            f"Unloading component {cid} ({cname}) failed: {res.error_message}"
        )
        return False

    def _get_info_section_general(self):
        info = super()._get_info_section_general()
        components = "\n".join(
            [f"  - {c.plugin}" for c in self.managed_components]
        )
        return (
            info
            + f"""
\x1b[1mComponents\x1b[0m
{components}
"""
        )
