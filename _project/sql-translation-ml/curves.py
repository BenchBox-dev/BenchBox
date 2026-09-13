"""Export training measurements as a standalone figure."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def plot(run: Path) -> None:
    figure, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for mode in ("full", "edit"):
        progress = json.loads((run / f"model-{mode}" / "progress.json").read_text(encoding="utf-8"))
        history = progress["history"]
        axes[0].plot([row["examples"] for row in history], [row["loss"] for row in history], label=mode, alpha=0.7)
        development = [row for row in history if "development_execution_accuracy" in row]
        axes[1].plot(
            [row["examples"] for row in development],
            [row["development_execution_accuracy"] for row in development],
            "o-",
            label=mode,
        )
    axes[0].set(xlabel="Training examples processed", ylabel="Training loss", yscale="log")
    axes[1].set(xlabel="Training examples processed", ylabel="Development execution accuracy", ylim=(0, 1))
    for axis in axes:
        axis.legend()
        axis.grid(alpha=0.2)
    figure.savefig(run / "learning-curves.png", dpi=160)
    plt.close(figure)
