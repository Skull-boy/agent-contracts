"""Stranger-test shape: a model upload through the Hugging Face Hub."""
from huggingface_hub import HfApi


def upload(model_path: str) -> None:
    HfApi().upload_file(
        path_or_fileobj=model_path,
        path_in_repo="model.bin",
        repo_id="acme/duplicate-issue-model",
    )
