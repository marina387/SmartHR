"""Проверки контракта обучения и установки чат-модели."""

import json
from pathlib import Path

import pytest

from src.chat.training import TrainingConfig, install_model_artifact, token_f1, validate_model_artifact


def make_adapter(path: Path, marker: str = "new") -> Path:
    path.mkdir(parents=True)
    (path / "adapter_config.json").write_text('{"base_model_name_or_path":"base"}', encoding="utf-8")
    (path / "adapter_model.safetensors").write_bytes(marker.encode())
    (path / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    (path / "smarthr_model_metadata.json").write_text(json.dumps({
        "model_type": "causal_lm", "base_model": "base/model", "format_version": "1.0",
        "language": ["ru"], "context_length": 4096,
    }), encoding="utf-8")
    return path


def test_training_config_loads_and_resolves_paths(tmp_path: Path):
    configs = tmp_path / "configs"
    configs.mkdir()
    path = configs / "train.yaml"
    path.write_text(
        "base_model: test/model\ntrain_file: data/train.jsonl\nvalidation_file: data/validation.jsonl\n"
        "output_dir: models/output\nmethod: lora\n",
        encoding="utf-8",
    )
    config = TrainingConfig.from_yaml(path)
    assert config.base_model == "test/model"
    assert config.train_file == tmp_path / "data/train.jsonl"
    assert config.output_dir == tmp_path / "models/output"


def test_training_config_rejects_placeholder_model(tmp_path: Path):
    config = TrainingConfig(
        "replace-with-model", tmp_path / "train.jsonl", tmp_path / "validation.jsonl", tmp_path / "out"
    )
    with pytest.raises(ValueError, match="base_model"):
        config.validate(require_files=False)


def test_training_config_reads_synthetic_opt_in(tmp_path: Path):
    configs = tmp_path / "configs"
    configs.mkdir()
    path = configs / "train.yaml"
    path.write_text(
        "base_model: test/model\ntrain_file: data/train.jsonl\n"
        "validation_file: data/validation.jsonl\noutput_dir: models/output\n"
        "allow_unapproved_synthetic: true\n",
        encoding="utf-8",
    )
    assert TrainingConfig.from_yaml(path).allow_unapproved_synthetic is True


def test_model_artifact_validation_and_install_with_backup(tmp_path: Path):
    source = make_adapter(tmp_path / "source")
    destination = make_adapter(tmp_path / "installed", marker="old")
    metadata = validate_model_artifact(source)
    result = install_model_artifact(source, destination)
    assert metadata["artifact_type"] == "adapter"
    assert (destination / "adapter_model.safetensors").read_bytes() == b"new"
    assert result["backup"] is not None
    assert Path(result["backup"]).exists()


def test_invalid_artifact_is_not_installed(tmp_path: Path):
    source = tmp_path / "broken"
    source.mkdir()
    with pytest.raises(ValueError, match="metadata"):
        install_model_artifact(source, tmp_path / "destination")


def test_token_f1_handles_partial_overlap():
    assert token_f1("кандидат подходит", "кандидат подходит") == 1.0
    assert 0 < token_f1("кандидат подходит", "кандидат подходит полностью") < 1
