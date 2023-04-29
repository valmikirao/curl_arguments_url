from typing import TextIO, Dict, Any

from typing_extensions import Protocol


class LoadYamlFunc(Protocol):
    def __call__(self, fh: TextIO) -> Dict[str, Any]:
        ...


load_yaml: LoadYamlFunc

try:
    import ryaml  # type: ignore

    def load_yaml(fh):
        return ryaml.loads(fh.read())
except ModuleNotFoundError:
    import yaml

    def load_yaml(fh: TextIO) -> Dict[str, Any]:
        return yaml.safe_load(fh)
