"""Can we verify policy learning on the TRAINING DOMAIN (Akino Hana self-play)?

The 10-game human test set measures whether we GENERALISE.  But the direct
question "did we learn Akino Hana's policy" is best asked on held-out files from
Akino Hana's own self-play logs, which we have 1765 of.

This splits the training files into fit-set and held-out-set, then measures the
adopted model's greedy agreement on each.  If the two numbers are close, the
model learned a policy.  If fit >> held-out, it memorised.
"""
import glob
import random
import sys

import torch
from torch.utils.data import DataLoader

sys.path.insert(0, ".")
from config import config
from dataloader import FileDatasetsIter
from model import Brain, DQN


def load_state(p):
    try:
        return torch.load(p, weights_only=True, map_location="cpu")
    except Exception:
        return torch.load(p, weights_only=False, map_location="cpu")


def measure(state, files, n_batches=120, batch_size=64, seed=20240915):
    device = torch.device("cuda:0")
    cfg = state["config"]
    version = cfg["control"].get("version", 1)
    mortal = Brain(version=version, **cfg["resnet"]).to(device).eval()
    dqn = DQN(version=version).to(device).eval()
    mortal.load_state_dict(state["mortal"])
    dqn.load_state_dict(state["current_dqn"])

    random.seed(seed)
    ds = FileDatasetsIter(
        version=version, file_list=list(files), pts=config["env"]["pts"],
        file_batch_size=5, reserve_ratio=0.0, player_names=[],
        num_epochs=1, enable_augmentation=False, augmented_first=False,
    )
    loader = iter(DataLoader(ds, batch_size=batch_size, num_workers=0, pin_memory=True))
    agree = total = 0
    for i, (obs, actions, masks, _s, _r, _p) in enumerate(loader):
        if i >= n_batches:
            break
        obs = obs.to(device=device, dtype=torch.float32)
        masks = masks.to(device=device, dtype=torch.bool)
        actions = actions.to(device=device, dtype=torch.int64)
        with torch.inference_mode(), torch.autocast(device.type, enabled=True):
            q = dqn(mortal(obs), masks)
            greedy = q.argmax(-1)
        agree += int((greedy == actions).sum().item())
        total += int(actions.numel())
    return agree, total


def main():
    allf = sorted(glob.glob("./date/*.json.gz"))
    rng = random.Random(20240915)
    shuffled = allf[:]
    rng.shuffle(shuffled)
    held = shuffled[:200]          # never used for this measurement
    fit = shuffled[200:]

    print(f"total files {len(allf)}  |  held-out {len(held)}  |  fit {len(fit)}")
    print()

    for label, ckpt in [
        ("2024v4best (base)", r"..\2024v4best\2024v4best.pth"),
        ("adopted 321,275", r".\output\my_finetuned_model\mortal.pth"),
    ]:
        st = load_state(ckpt)
        a1, t1 = measure(st, fit, n_batches=120)
        a2, t2 = measure(st, held, n_batches=120)
        print(f"{label}")
        print(f"   seen-domain files   (fit)  : {a1}/{t1} = {100.0*a1/t1:.2f}%")
        print(f"   held-out files             : {a2}/{t2} = {100.0*a2/t2:.2f}%")
        print(f"   generalisation gap         : {100.0*a1/t1 - 100.0*a2/t2:+.2f} pts")
        print()


if __name__ == "__main__":
    main()
