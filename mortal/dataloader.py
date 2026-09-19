import random
import torch
import numpy as np
from torch.utils.data import IterableDataset
from model import GRP
from reward_calculator import RewardCalculator
from libriichi.dataset import GameplayLoader
from config import config

# Action-space permutation induced by Mortal's 180-degree augmentation, which is
# a man<->pin swap (libriichi/src/tile.rs).  Actions 0-8 (1m..9m) trade places
# with 9-17 (1p..9p) and aka 5m <-> aka 5p.  Everything else is unchanged:
# sou/honors are untouched, and chi low/mid/high depends only on the called
# tile's position WITHIN its suit, which a suit swap preserves.  Self-inverse.
ACTION_PERM = list(range(46))
for _i in range(9):
    ACTION_PERM[_i], ACTION_PERM[_i + 9] = _i + 9, _i
ACTION_PERM[34], ACTION_PERM[35] = 35, 34


class FileDatasetsIter(IterableDataset):
    def __init__(
        self,
        version,
        file_list,
        pts,
        oracle = False,
        file_batch_size = 20, # hint: around 660 instances per file
        reserve_ratio = 0,
        player_names = None,
        excludes = None,
        num_epochs = 1,
        enable_augmentation = False,
        augmented_first = False,
    ):
        super().__init__()
        self.version = version
        self.file_list = file_list
        self.pts = pts
        self.oracle = oracle
        self.file_batch_size = file_batch_size
        self.reserve_ratio = reserve_ratio
        self.player_names = player_names
        self.excludes = excludes
        self.num_epochs = num_epochs
        self.enable_augmentation = enable_augmentation
        self.augmented_first = augmented_first
        self.iterator = None

    def build_iter(self):
        # do not put it in __init__, it won't work on Windows
        self.grp = GRP(**config['grp']['network'])
        grp_state = torch.load(config['grp']['state_file'], weights_only=True, map_location=torch.device('cpu'))
        self.grp.load_state_dict(grp_state['model'])
        self.reward_calc = RewardCalculator(self.grp, self.pts)

        for _ in range(self.num_epochs):
            yield from self.load_files(self.augmented_first)
            if self.enable_augmentation:
                yield from self.load_files(not self.augmented_first)

    def load_files(self, augmented):
        # shuffle the file list for each epoch
        random.shuffle(self.file_list)

        self.loader = GameplayLoader(
            version = self.version,
            oracle = self.oracle,
            player_names = self.player_names,
            excludes = self.excludes,
            augmented = augmented,
        )
        self.buffer = []

        for start_idx in range(0, len(self.file_list), self.file_batch_size):
            old_buffer_size = len(self.buffer)
            self.populate_buffer(self.file_list[start_idx:start_idx + self.file_batch_size])
            buffer_size = len(self.buffer)

            reserved_size = int((buffer_size - old_buffer_size) * self.reserve_ratio)
            if reserved_size > buffer_size:
                continue

            random.shuffle(self.buffer)
            yield from self.buffer[reserved_size:]
            del self.buffer[reserved_size:]
        random.shuffle(self.buffer)
        yield from self.buffer
        self.buffer.clear()

    def populate_buffer(self, file_list):
        data = self.loader.load_gz_log_files(file_list)
        for file in data:
            for game in file:
                # per move
                obs = game.take_obs()
                if self.oracle:
                    invisible_obs = game.take_invisible_obs()
                actions = game.take_actions()
                masks = game.take_masks()
                at_kyoku = game.take_at_kyoku()
                dones = game.take_dones()
                apply_gamma = game.take_apply_gamma()

                # per game
                grp = game.take_grp()
                player_id = game.take_player_id()

                game_size = len(obs)

                grp_feature = grp.take_feature()
                rank_by_player = grp.take_rank_by_player()
                kyoku_rewards = self.reward_calc.calc_delta_pt(player_id, grp_feature, rank_by_player)
                assert len(kyoku_rewards) >= at_kyoku[-1] + 1 # usually they are equal, unless there is no action in the last kyoku

                final_scores = grp.take_final_scores()
                scores_seq = np.concatenate((grp_feature[:, 3:] * 1e4, [final_scores]))
                rank_by_player_seq = (-scores_seq).argsort(-1, kind='stable').argsort(-1, kind='stable')
                player_ranks = rank_by_player_seq[:, player_id]

                steps_to_done = np.zeros(game_size, dtype=np.int64)
                for i in reversed(range(game_size)):
                    if not dones[i]:
                        steps_to_done[i] = steps_to_done[i + 1] + int(apply_gamma[i])

                for i in range(game_size):
                    entry = [
                        obs[i],
                        actions[i],
                        masks[i],
                        steps_to_done[i],
                        kyoku_rewards[at_kyoku[i]],
                        player_ranks[at_kyoku[i] + 1],
                    ]
                    if self.oracle:
                        entry.insert(1, invisible_obs[i])
                    self.buffer.append(entry)

    def __iter__(self):
        if self.iterator is None:
            self.iterator = self.build_iter()
        return self.iterator


class DistillDatasetsIter(IterableDataset):
    """Yields (obs, mask, target) for knowledge distillation from Akino Hana.

    `target` is the teacher's full action distribution pi(a|s), harvested from
    bigcoach and aligned to the replay rows.  Rows the report did not cover (the
    replay emits a few extra kan-selection rows) are skipped.

    There are no rewards or player ranks here: the objective is to match the
    teacher's policy, not to estimate returns.  Observation tensors are
    regenerated from the mjai logs by libriichi on every epoch, so only the
    small logs and target arrays are kept on disk.

    With `enable_augmentation` each log is also replayed in Mortal's 180-degree
    augmented frame.  That frame is a man<->pin swap, so the action space permutes
    by ACTION_PERM and the target is gathered through it.  Verified on real data:
    the mirrored target puts zero mass on illegal actions and its argmax is
    always legal (see _verify_augment.py).
    """

    def __init__(self, version, files, targets, num_epochs=1,
                 enable_augmentation=False):
        super().__init__()
        self.version = version
        self.files = files
        self.targets = targets          # {key: {"target": (n,46), "valid": (n,)}}
        self.num_epochs = num_epochs
        self.enable_augmentation = enable_augmentation
        self.iterator = None

    def build_iter(self):
        import os
        from libriichi.dataset import GameplayLoader
        from torch.utils.data import get_worker_info

        # PyTorch only shards work between workers automatically for map-style
        # datasets.  An IterableDataset is iterated IN FULL by every worker, so
        # without this split num_workers=2 delivers each sample twice (measured:
        # 41 batches with one worker, 82 with two) -- i.e. half the compute is
        # spent on duplicates.  Slice the file list per worker instead
        # (FileDatasetsIter does the same via worker_init_fn).
        info = get_worker_info()
        files = list(self.files)
        if info is not None and info.num_workers > 1:
            per = -(-len(files) // info.num_workers)      # ceil division
            files = files[info.id * per:(info.id + 1) * per]

        frames = (False, True) if self.enable_augmentation else (False,)
        for _ in range(self.num_epochs):
            order = list(files)
            random.shuffle(order)
            for augmented in frames:
                for path in order:
                    key = os.path.basename(path)
                    if key.endswith(".json.gz"):
                        key = key[:-len(".json.gz")]
                    rec = self.targets.get(key)
                    if rec is None:
                        continue
                    # logs are stored as "<canonicalId>_s<seat>"; the target
                    # belongs to THAT player only.  libriichi returns all four
                    # gameplays, so without this filter three of them would be
                    # trained against the wrong player's targets.
                    try:
                        seat = int(key.rsplit("_s", 1)[1])
                    except (IndexError, ValueError):
                        continue
                    loader = GameplayLoader(
                        version=self.version, oracle=False, player_names=[],
                        excludes=[], augmented=augmented,
                    )
                    data = loader.load_gz_log_files([path])
                    for grp in data:
                        for game in grp:
                            if int(game.take_player_id()) != seat:
                                continue
                            obs = game.take_obs()
                            masks = game.take_masks()
                            tgt = rec["target"]
                            val = rec["valid"]
                            for i in range(min(len(obs), len(tgt))):
                                if not bool(val[i]):
                                    continue
                                t = tgt[i]
                                if augmented:
                                    t = t[ACTION_PERM]
                                yield (
                                    np.asarray(obs[i], dtype=np.float32),
                                    np.asarray(masks[i], dtype=bool),
                                    np.asarray(t, dtype=np.float32),
                                )

    def __iter__(self):
        if self.iterator is None:
            self.iterator = self.build_iter()
        return self.iterator

def worker_init_fn(*args, **kwargs):
    worker_info = torch.utils.data.get_worker_info()
    dataset = worker_info.dataset
    per_worker = int(np.ceil(len(dataset.file_list) / worker_info.num_workers))
    start = worker_info.id * per_worker
    end = start + per_worker
    dataset.file_list = dataset.file_list[start:end]
