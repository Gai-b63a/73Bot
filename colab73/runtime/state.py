"""Runtime status persistence without process or GPU dependencies."""
from ..contracts import RuntimePaths, RuntimeStatus
from ..storage.json import read_json, write_json


class StateFile:
    def __init__(self, paths: RuntimePaths):
        self.path = paths.state

    def read(self) -> RuntimeStatus:
        return read_json(self.path) if self.path.exists() else {"phase": "未起動"}

    def write(self, value: RuntimeStatus) -> None:
        write_json(self.path, value)
