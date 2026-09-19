"""Measure how well a Mortal checkpoint fits the training dataset.

"Fit" here = the fraction of decision points where the model's greedy action
(argmax of the masked Q values) equals the action actually taken in the log.
This is the same notion as mjai-reviewer's agreement / Mortal's rating.

Run from the `mortal` directory:

    ..\\.venv\\Scripts\\python.exe _measure_fit.py <checkpoint.pth> [n_batches] [batch_size]
"""
import glob
import random
import sys

import torch
from torch.utils.data import DataLoader

from config import config
from dataloader import FileDatasetsIter
from model import Brain, DQN


def load_state(ckpt_path):
    """Official checkpoints contain numpy scalars, so weights_only=True may fail."""
    try:
        return torch.load(ckpt_path, weights_only=True, map_location="cpu")
    except Exception:
        return torch.load(ckpt_path, weights_only=False, map_location="cpu")


def measure(ckpt_path, n_batches=300, batch_size=64, device_name="cuda:0"):
    device = torch.device(device_name)
    state = load_state(ckpt_path)
    cfg = state["config"]
    version = cfg["control"].get("version", 1)
    resnet = cfg["resnet"]

    mortal = Brain(version=version, **resnet).to(device).eval()
    dqn = DQN(version=version).to(device).eval()
    mortal.load_state_dict(state["mortal"])
    dqn.load_state_dict(state["current_dqn"])

    files = sorted(glob.glob("./date/*.json.gz"))
    # Deterministic sampling: the dataset shuffles its file list internally, so
    # seed the RNG to make every checkpoint get measured on the *same* samples.
    random.seed(20240915)
    ds = FileDatasetsIter(
        version=version,
        file_list=files,
        pts=config["env"]["pts"],
        file_batch_size=5,
        reserve_ratio=0.0,
        player_names=[],
        num_epochs=1,
        enable_augmentation=False,
        augmented_first=False,
    )
    loader = iter(DataLoader(ds, batch_size=batch_size, num_workers=0, pin_memory=True))

    agree = 0
    total = 0
    for i, (obs, actions, masks, _s, _r, _p) in enumerate(loader):
        if i >= n_batches:
            break
        obs = obs.to(device=device, dtype=torch.float32)
        masks = masks.to(device=device, dtype=torch.bool)
        actions = actions.to(device=device, dtype=torch.int64)
        with torch.inference_mode(), torch.autocast(device.type, enabled=True):
            phi = mortal(obs)
            q = dqn(phi, masks)
            greedy = q.argmax(-1)
        agree += int((greedy == actions).sum().item())
        total += int(actions.numel())

    return agree, total


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    ckpt = sys.argv[1]
    n_batches = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    batch_size = int(sys.argv[3]) if len(sys.argv) > 3 else 64

    agree, total = measure(ckpt, n_batches=n_batches, batch_size=batch_size)
    print(f"checkpoint : {ckpt}")
    print(f"samples    : {total}")
    print(f"agreement  : {agree}/{total} = {agree / total:.4f}")
    # Mortal's "rating" is the squared agreement ratio
    print(f"rating     : {(agree / total) ** 2:.4f}")


if __name__ == "__main__":
    main()
