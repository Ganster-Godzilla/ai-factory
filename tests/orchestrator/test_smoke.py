import yaml
from pathlib import Path


def test_orchestrator_yaml_loads():
    cfg = yaml.safe_load(Path("orchestrator.yaml").read_text(encoding="utf-8"))
    assert cfg["pool"] == "pool"
    assert cfg["thresholds"]["concurrent_max"] == 2
