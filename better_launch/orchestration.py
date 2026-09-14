from typing import Callable
from threading import Thread
from subprocess import Popen
import signal
import time

from .utils.random_names import get_unique_word


class Performer:
    def __init__(self, args: str | list[str], name: str = None):
        if isinstance(args, str):
            args = [args]

        self.args = [str(a) for a in args]
        self.process: Popen = None
        self.name = name or get_unique_word()

    def state(self) -> int:
        if self.process:
            return self.process.poll()

        return 0

    @property
    def running(self) -> bool:
        return self.state() is None

    @property
    def pid(self) -> int:
        if self.running:
            return self.process.pid
        
        return -1

    def start(self, kill: bool = False) -> None:
        if self.running:
            if not kill:
                return

            self.process.terminate()
        
        self.process = Popen(self.args)

    def stop(self, sig: int = signal.SIGTERM, timeout: float = None) -> int:
        if self.running:
            self.process.send_signal(sig)
            return self.process.wait(timeout)

        return 0

    def __str__(self) -> str:
        args = [self.args[0]]

        for a in self.args[1:]:
            if len(a) > 50:
                a = f"{a[:50]}..."
            args.append(a)

        return f"Performer '{self.name}': {args}"


class Orchestrator:
    def __init__(
        self,
        name: str = None,
        port: int = 27072,
        check_frequency: float = 1.0,
    ):
        self.name = name or get_unique_word()
        self.port = port
        self.check_frequency = check_frequency
        self._conductor: Thread = None
        self._performers: list[Performer] = None
        self._running = False

        if port is not None and port > 0:
            self.start_server()

    @property
    def running(self) -> bool:
        return self._running

    def start_server(self) -> None:
        # TODO setup RPC server, write tool to talk to orchestrator remotely
        # Use ros rmw as backend?
        pass

    def find(
        self,
        package: str,
        filename: str = None,
        subdir: str = None,
    ) -> str:
        # TODO refactor bl.find and use it here
        pass

    def launch(
        self, launchfile: str, name: str = None, *, autostart: bool = True, **launch_args
    ) -> Performer:
        perf = Performer([launchfile, *launch_args], name)
        self._performers.append(perf)

        if autostart:
            perf.start()

    def watch(self) -> None:
        if (self._conductor and self._conductor.is_alive()):
            return

        self._conductor = Thread(target=self._check_performers)
        self._conductor.start()

    def _check_performers(self) -> None:
        while self.running:
            for perf in self._performers:
                state = perf.state()
                if state is not None:
                    self.logger.warning(f"{perf} has ended with status {state}, restarting")
                    perf.start()

            time.sleep(1.0 / self.check_frequency)

    def join(self, timeout: float = None) -> None:
        if not (self._conductor and self._conductor.is_alive()):
            return

        self._conductor.join(timeout=timeout)
