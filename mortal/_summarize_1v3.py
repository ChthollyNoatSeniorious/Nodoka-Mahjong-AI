"""Summarize 1v3 battle logs in a directory.

Usage: python _summarize_1v3.py <log_dir> [challenger_name]
Reads every *.json.gz in log_dir, accumulates score deltas per player,
and prints per-game rankings plus aggregate stats for the challenger.
"""
import gzip
import json
import os
import sys


def parse_game(path):
    names = None
    scores = [25000, 25000, 25000, 25000]
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            t = ev.get('type')
            if t == 'start_game':
                names = ev.get('names')
            elif t == 'hora':
                deltas = ev.get('deltas')
                if deltas:
                    scores = [s + d for s, d in zip(scores, deltas)]
            elif t == 'ryukyoku':
                deltas = ev.get('deltas')
                if deltas:
                    scores = [s + d for s, d in zip(scores, deltas)]
            elif t == 'end_game':
                break
    return names, scores


def main():
    log_dir = sys.argv[1]
    chal_name = sys.argv[2] if len(sys.argv) > 2 else 'mortal'
    files = sorted(f for f in os.listdir(log_dir) if f.endswith('.gz'))
    agg = [0, 0, 0, 0]  # rank 1..4 counts
    pts = [90, 45, 0, -135]
    print(f'{"game":<48} {"chal_rank":>9} {"chal_score":>11}  all_scores')
    for fn in files:
        path = os.path.join(log_dir, fn)
        names, scores = parse_game(path)
        if names is None:
            print(f'{fn}: no start_game, skipped')
            continue
        try:
            chal_seat = names.index(chal_name)
        except ValueError:
            print(f'{fn}: challenger {chal_name} not in {names}, skipped')
            continue
        order = sorted(range(4), key=lambda i: -scores[i])
        rank = order.index(chal_seat) + 1
        agg[rank - 1] += 1
        print(f'{fn:<48} {rank:>9} {scores[chal_seat]:>11}  {scores}')
    n = sum(agg)
    if n:
        avg_rank = sum((i + 1) * agg[i] for i in range(4)) / n
        avg_pt = sum(pts[i] * agg[i] for i in range(4)) / n
        print()
        print(f'total games: {n}')
        print(f'challenger [{chal_name}] ranking distribution: 1st={agg[0]} 2nd={agg[1]} '
              f'3rd={agg[2]} 4th={agg[3]}')
        print(f'avg_rank = {avg_rank:.3f}   avg_pt = {avg_pt:+.2f}   '
              f'1st_rate = {agg[0] / n * 100:.1f}%   top2_rate = {(agg[0] + agg[1]) / n * 100:.1f}%')


if __name__ == '__main__':
    main()