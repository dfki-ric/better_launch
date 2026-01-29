from enum import IntEnum
from collections import deque
import time

from lifecycle_msgs.msg import TransitionEvent, State, Transition
from lifecycle_msgs.srv import ChangeState as ChangeLifecycleState


class LifecycleStage(IntEnum):
    """Represents the main stages of nodes that support lifecycle management. 
    """
    #There is usually little reason to be exposed to all the intermediate stages and transitions ROS defines.
    PRISTINE = 0
    CONFIGURED = 1
    ACTIVE = 2
    FINALIZED = 3


_stage_to_ros_state = {
    LifecycleStage.PRISTINE: State.PRIMARY_STATE_UNCONFIGURED,
    LifecycleStage.CONFIGURED: State.PRIMARY_STATE_INACTIVE,
    LifecycleStage.ACTIVE: State.PRIMARY_STATE_ACTIVE,
    LifecycleStage.FINALIZED: State.PRIMARY_STATE_FINALIZED,
}


# See https://design.ros2.org/articles/node_lifecycle.html
_transition_map = {
    State.PRIMARY_STATE_UNCONFIGURED: [
        (Transition.TRANSITION_CONFIGURE, State.PRIMARY_STATE_INACTIVE),
        (Transition.TRANSITION_UNCONFIGURED_SHUTDOWN, State.PRIMARY_STATE_FINALIZED),
    ],
    State.PRIMARY_STATE_INACTIVE: [
        (Transition.TRANSITION_INACTIVE_SHUTDOWN, State.PRIMARY_STATE_FINALIZED),
        (Transition.TRANSITION_CLEANUP, State.PRIMARY_STATE_UNCONFIGURED),
        (Transition.TRANSITION_ACTIVATE, State.PRIMARY_STATE_ACTIVE),
    ],
    State.PRIMARY_STATE_ACTIVE: [
        (Transition.TRANSITION_DEACTIVATE, State.PRIMARY_STATE_INACTIVE),
        (Transition.TRANSITION_ACTIVE_SHUTDOWN, State.PRIMARY_STATE_FINALIZED),
    ],
    State.PRIMARY_STATE_FINALIZED: [
        (Transition.TRANSITION_DESTROY, State.PRIMARY_STATE_UNKNOWN)
    ],
}


# Forward declaration to avoid cyclic imports
class AbstractNode:
    ...


class LifecycleManager:
    @classmethod
    def is_lifecycle(cls, node: AbstractNode, timeout: float = None) -> bool:
        """Checks whether a node supports lifecycle management. 

        For a node to support lifecycle management, it must be running, be registered with ROS and offer the ROS lifecycle management services. This method **only** checks whether one of the key services is present.

        If a timeout is specified, the check will be repeated until it succeeds or the specified amount of time has passed. This is to ensure that a freshly started node had enough time to create its topics, especially on slower devices. See [AbstractNode.is_lifecycle_node][better_launch.elements.abstract_node.AbstractNode.is_lifecycle_node] for additional information.

        Parameters
        ----------
        node : AbstractNode
            The node object to check for lifecycle support.
        timeout : float
            How long to wait at most for the lifecycle services to appear. Wait forever if None.

        Returns
        -------
        bool
            True if the node supports lifecycle management, False otherwise.
        """
        now = time.time()
        while True:
            # Check if the node provides one of the key lifecycle services
            services = node.get_published_services()
            for srv_name, srv_types in services.items():
                if (
                    srv_name == f"{node.fullname}/get_available_transitions"
                    and "lifecycle_msgs/srv/GetAvailableTransitions" in srv_types
                ):
                    return True

            if timeout is not None and time.time() > now + timeout:
                break

            time.sleep(0.1)

        return False

    @classmethod
    def find_transition_path(cls, start_ros_state: int, goal_ros_state: int) -> list[int]:
        """Finds a sequence of transitions that will bring a node from an initial lifecycle state (the ROS state, not our LifecycleStage enum) to a target lifecycle state. 

        This is fairly low level and probably never needed.

        Parameters
        ----------
        start_ros_state : int
            The initial ROS lifecycle state.
        goal_ros_state : int
            The final ROS lifecycle state.

        Returns
        -------
        list[int]
            A sequence of ROS lifecycle transitions that form a path from the start state to the goal state.
        """
        if start_ros_state == goal_ros_state:
            return []

        # Queue for BFS: (current_state, path_to_state)
        queue = deque([(start_ros_state, [])])
        visited = set()

        while queue:
            current_state, path = queue.popleft()

            if current_state == goal_ros_state:
                return path

            if current_state in visited:
                continue

            visited.add(current_state)

            # Explore transitions from the current state
            for transition, next_state in _transition_map.get(current_state, []):
                if next_state not in visited:
                    queue.append((next_state, path + [transition]))

        # No path found
        return []

    def __init__(self, node: AbstractNode):
        """Offers additional functionality to manage a node's lifecycle. Verification whether a node supports lifecycle management should happen **before** this is instantiated.

        Parameters
        ----------
        node : AbstractNode
            The node who's lifecycle should be managed.

        Raises
        ------
        RuntimeError
            If the transition service failed to connect.
        """
        self._current_stage = LifecycleStage.PRISTINE
        self._current_ros_state: int = State.PRIMARY_STATE_UNCONFIGURED
        self._node = node

        from better_launch import BetterLaunch

        launcher = BetterLaunch.instance()
        self._state_sub = launcher.shared_node.create_subscription(
            TransitionEvent,
            f"{self._node.fullname}/transition_event",
            self._on_transition_event,
            10,
        )

        self._transition_client = launcher.shared_node.create_client(
            ChangeLifecycleState, f"{self._node.fullname}/change_state"
        )
        if not self._transition_client.wait_for_service(5.0):
            raise RuntimeError("Could not connect to lifecycle transition service")

    @property
    def current_stage(self) -> LifecycleStage:
        """The node's current (that is, last known) lifecycle stage.
        """
        return self._current_stage

    @property
    def ros_state(self) -> int:
        """The node's current (that is, last known) ROS lifecycle state ID.
        """
        return self._current_ros_state

    def transition(self, target_stage: LifecycleStage | str) -> bool:
        """Transition the managed node into the target lifecycle stage. Does nothing if the node is already in the desired stage. 
        
        Note that you **don't** have to do step-by-step transitions - simply specify the stage you want the node to end up in and it will go through all the intermediate steps (assuming a path exists).

        Parameters
        ----------
        target_stage : LifecycleStage | str
            The lifecycle stage you want the node to end up in.

        Returns
        -------
        bool
            True if the transition sequence succeeded, False if one of the steps failed.

        Raises
        ------
        ValueError
            If no path to the target stage could be found.
        """
        if isinstance(target_stage, str):
            target_stage = LifecycleStage[target_stage.upper()]

        if target_stage == self.current_stage:
            return True

        # Figure out if and how we can get from our current state to the target state
        target_ros_state = _stage_to_ros_state[target_stage]
        transition_path = LifecycleManager.find_transition_path(
            self._current_ros_state, target_ros_state
        )

        if not transition_path:
            raise ValueError(
                f"Could not find a valid transition sequence for {self._current_stage} -> {target_stage}"
            )

        for transition in transition_path:
            if not self._do_transition(transition):
                self._node.logger.error(
                    f"Lifecycle transition {transition} for {self._node.name} towards stage {target_stage} failed"
                )
                return False

        # TODO we may not have received the transition update yet
        return True

    def _on_transition_event(self, evt: TransitionEvent) -> None:
        """Update the current state ID and stage.
        """
        self._current_ros_state = evt.goal_state.id
        for key, val in _stage_to_ros_state.items():
            if val == evt.goal_state.id:
                self._current_stage = key
                break
        else:
            self._current_stage = -1

    def _do_transition(self, transition_id: int) -> bool:
        """Issue a transition service request.
        """
        req = ChangeLifecycleState.Request()
        req.transition.id = transition_id

        # TODO should make this async, this can take a few seconds
        res = self._transition_client.call(req)
        return res.success
