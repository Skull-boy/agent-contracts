"""Stranger-test shape: a DL training run with a hardcoded W&B API token."""
import wandb


def train() -> None:
    wandb.login(key="wb_aBcDeFgHiJkLmNoPqRsTuVwXyZ012345")
    wandb.init(project="duplicate-issue-detector")
