"""Verify FileDatasetsIter can consume 1v3 self-play logs (format compat check)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import prelude

from dataloader import FileDatasetsIter
from torch.utils.data import DataLoader

files = [
    r'output/1v3_100/10000_11753734894124178690_a.json.gz',
    r'output/1v3/10000_14808628367605708441_a.json.gz',
]
for f in files:
    print('checking', f)
    ds = FileDatasetsIter(
        version=4,
        file_list=[f],
        pts=[6.0, 4.0, 2.0, 0.0],
        file_batch_size=1,
        reserve_ratio=0.0,
        player_names=[],
        num_epochs=1,
        enable_augmentation=False,
        augmented_first=False,
    )
    loader = iter(DataLoader(ds, batch_size=32, drop_last=True, num_workers=0))
    n = 0
    try:
        while True:
            batch = next(loader)
            obs, actions, masks, steps, kyoku_rew, ranks = batch
            n += len(actions)
            if n >= 64:
                break
    except StopIteration:
        pass
    print(f'  OK: consumed {n} decision rows')