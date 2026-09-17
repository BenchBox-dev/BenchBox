"""Sequential, bounded CodeT5 full fine-tuning with resumable local checkpoints."""

from __future__ import annotations

import argparse
import json
import random
import signal
from pathlib import Path

import psutil
import torch
from artifacts import checkpoint, inputs as artifact_inputs, runtime
from corpus import SEED
from experiment import MODEL, REVISION, OraclePool, apply_edits, load_lines, write_json
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

from benchbox.utils.clock import elapsed_seconds, mono_time


def tokenized(tokenizer, text: str) -> dict:
    tokens = tokenizer(text, return_tensors="pt", truncation=False)
    if tokens["input_ids"].shape[1] > 1024:
        raise ValueError("input exceeds 1024 tokens")
    return tokens


def infer(model, tokenizer, prompt: str, mode: str, device: str) -> tuple[str, int]:
    tokens = {key: value.to(device) for key, value in tokenized(tokenizer, prompt).items()}
    with torch.no_grad():
        output = model.generate(**tokens, max_new_tokens=1024, max_time=30.0, do_sample=False, num_beams=1)
    ids = output[0].tolist()
    if tokenizer.eos_token_id not in ids[1:]:
        raise ValueError("output length exhausted without EOS")
    raw = tokenizer.decode(ids, skip_special_tokens=True)
    if not raw.strip():
        raise ValueError("empty output")
    sql = raw if mode == "full" else apply_edits(json.loads(prompt)["candidate"], json.loads(raw))
    if len(tokenizer.encode(sql)) > 1024:
        raise ValueError("final SQL exceeds 1024 tokens")
    return sql, len(ids) - 1


def development_accuracy(
    model, tokenizer, records: list, sources: dict, mode: str, device: str, deadline: float
) -> float:
    pool = OraclePool()
    successes = 0
    model.eval()
    try:
        for record in records:
            if mono_time() >= deadline:
                raise TimeoutError("training budget exhausted during development evaluation")
            case = sources[record["case_id"]]
            try:
                sql, _ = infer(model, tokenizer, record["input"], mode, device)
                expected = pool.results(case["sql"], case["source"])
                successes += pool.compare(expected, sql, case)["equivalent"]
            except (ValueError, RuntimeError, json.JSONDecodeError):
                pass
    finally:
        pool.close()
        model.train()
    return successes / len(records)


def training_data(run: Path, mode: str) -> tuple[list, list]:
    if not (run / "preparation-summary.json").exists():
        raise ValueError("preparation is incomplete")
    contract = json.loads((run / "contract.json").read_text(encoding="utf-8"))
    if (contract["model"], contract["revision"]) != (MODEL, REVISION):
        raise ValueError("model/tokenizer identity changed")
    labels = [r for r in load_lines(run / "labels.jsonl") if r["mode"] == mode]
    training = [r for r in labels if r["split"] == "train"][:10000]
    development = [r for r in labels if r["split"] == "development"][:2000]
    if len(training) != 10000 or len(development) != 2000:
        raise ValueError(f"insufficient validated labels: {len(training)} train, {len(development)} development")
    return training, development


def train(run: Path, mode: str, feasibility: bool, resume: bool) -> None:
    training, development = training_data(run, mode)
    torch.manual_seed(SEED)
    torch.set_num_threads(4)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    if device != "mps":
        raise RuntimeError("approved MPS backend is unavailable")
    output = run / f"model-{mode}"
    output.mkdir(exist_ok=True)
    state_path = output / "resume.pt"
    if state_path.exists() and not resume:
        raise ValueError("checkpoint exists; supply --resume")
    tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL, revision=REVISION).to(device)
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    if parameter_count >= 100_000_000:
        raise ValueError("model exceeds parameter budget")
    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-5)
    state = {
        "cursor": 0,
        "step": 0,
        "elapsed": 0.0,
        "best_accuracy": -1.0,
        "history": [],
        "input_hashes": artifact_inputs(run),
    }
    if resume:
        saved = torch.load(state_path, map_location="cpu", weights_only=False)
        if saved["state"].get("input_hashes") != state["input_hashes"]:
            raise ValueError("checkpoint input identity missing or changed")
        model.load_state_dict(saved["weights"])
        optimizer.load_state_dict(saved["optimizer"])
        state = saved["state"]
        torch.set_rng_state(saved["rng"])
        torch.mps.set_rng_state(saved["mps_rng"])
    start = mono_time()
    deadline = start + max(0, 86400 - state["elapsed"])
    prior_progress = json.loads((output / "progress.json").read_text(encoding="utf-8")) if resume else {}
    peak_rss = max(state.get("peak_rss", 0), prior_progress.get("peak_rss", 0))
    peak_mps = max(state.get("peak_mps", 0), prior_progress.get("peak_mps", 0))
    sources = {r["case_id"]: r for r in load_lines(run / "source.jsonl")}
    order = []
    for epoch in range(3):
        indices = list(range(len(training)))
        random.Random(SEED + epoch).shuffle(indices)
        order.extend(indices)
    model.train()
    stopping = False

    def request_stop(signum, frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    def save() -> None:
        torch.mps.synchronize()
        snapshot = dict(state, elapsed=state["elapsed"] + elapsed_seconds(start), peak_rss=peak_rss, peak_mps=peak_mps)
        temporary = output / "resume.tmp"
        torch.save(
            {
                "weights": model.state_dict(),
                "optimizer": optimizer.state_dict(),
                "state": snapshot,
                "rng": torch.get_rng_state(),
                "mps_rng": torch.mps.get_rng_state(),
            },
            temporary,
        )
        temporary.replace(state_path)
        write_json(
            output / "progress.json",
            dict(snapshot, parameter_count=parameter_count, peak_rss=peak_rss, peak_mps=peak_mps, device=device),
        )

    try:
        while (
            state["cursor"] < len(order) and (not feasibility or state["step"] < 200) and state["best_accuracy"] < 1.0
        ):
            if stopping:
                raise InterruptedError("stopped at an optimizer boundary; checkpoint saved")
            if mono_time() >= deadline:
                raise TimeoutError("24-hour model budget reached")
            optimizer.zero_grad(set_to_none=True)
            end = min(state["cursor"] + 16, len(order), ((state["cursor"] // 10000) + 1) * 10000)
            batch_loss = 0.0
            for cursor in range(state["cursor"], end):
                record = training[order[cursor]]
                inputs = {k: v.to(device) for k, v in tokenized(tokenizer, record["input"]).items()}
                target = tokenized(tokenizer, record["output"])["input_ids"].to(device)
                loss = model(**inputs, labels=target).loss / (end - state["cursor"])
                if not torch.isfinite(loss):
                    raise ValueError("nonfinite loss")
                loss.backward()
                batch_loss += loss.detach().item()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            torch.mps.synchronize()
            state["cursor"] = end
            state["step"] += 1
            peak_rss = max(peak_rss, psutil.Process().memory_info().rss)
            peak_mps = max(peak_mps, torch.mps.driver_allocated_memory())
            metric = {
                "step": state["step"],
                "examples": end,
                "loss": batch_loss,
                "seconds": state["elapsed"] + elapsed_seconds(start),
            }
            state["history"].append(metric)
            if state["step"] % 10 == 0:
                print(json.dumps(metric), flush=True)
            if end % 10000 == 0:
                accuracy = development_accuracy(model, tokenizer, development, sources, mode, device, deadline)
                metric["development_execution_accuracy"] = accuracy
                if accuracy > state["best_accuracy"]:
                    state["best_accuracy"] = accuracy
                    model.save_pretrained(output / "selected")
                    tokenizer.save_pretrained(output / "selected")
                    state["selected_checkpoint"] = checkpoint(output / "selected")
                    state["selected_step"] = state["step"]
            if state["step"] % 50 == 0 or end % 10000 == 0:
                save()
    finally:
        save()
    write_json(
        output / ("feasibility.json" if feasibility else "training.json"),
        {
            "parameter_count": parameter_count,
            "step": state["step"],
            "examples": state["cursor"],
            "elapsed_seconds": state["elapsed"] + elapsed_seconds(start),
            "peak_rss": peak_rss,
            "peak_mps": peak_mps,
            "best_development_accuracy": state["best_accuracy"],
            "mode": mode,
            "input_hashes": state["input_hashes"],
            "runtime": runtime(),
            "selected_checkpoint": state.get("selected_checkpoint"),
            "selected_step": state.get("selected_step"),
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=["full", "edit"])
    parser.add_argument("--feasibility", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    train(args.run_dir.resolve(), args.mode, args.feasibility, args.resume)
