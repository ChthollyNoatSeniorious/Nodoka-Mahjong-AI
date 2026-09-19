"""Prepare a finetune checkpoint: pretrained model weights + a fresh optimizer/scheduler/scaler.

Loads `pretrained/mortal.pth` (which cannot be loaded with weights_only=True because of
numpy scalars) and writes a weights_only-safe working checkpoint to
`output/my_finetuned_model/mortal.pth`, using the *current* config.toml's optimizer/scheduler
settings (constant lr 2e-5), with steps reset to 0.

This mirrors exactly how train.py constructs the models/optimizer/scheduler.
Run from the `mortal` directory:  ..\\.venv\\Scripts\\python.exe _prepare_ckpt.py
"""
import os
import sys
import torch
from datetime import datetime
from torch import optim, nn
from torch.amp import GradScaler

from model import Brain, DQN, AuxNet
from lr_scheduler import LinearWarmUpCosineAnnealingLR
from config import config

version = config['control']['version']
device = torch.device('cpu')  # preparation is device-independent

mortal = Brain(version=version, **config['resnet'])
dqn = DQN(version=version)
aux_net = AuxNet((4,))
all_models = (mortal, dqn, aux_net)

mortal.freeze_bn(config['freeze_bn']['mortal'])

# replicate train.py param-group construction (decay vs no-decay)
weight_decay = config['optim']['weight_decay']
betas = config['optim']['betas']
eps = config['optim']['eps']
decay_params = []
no_decay_params = []
for model in all_models:
    params_dict = {}
    to_decay = set()
    for mod_name, mod in model.named_modules():
        for name, param in mod.named_parameters(prefix=mod_name, recurse=False):
            params_dict[name] = param
            if isinstance(mod, (nn.Linear, nn.Conv1d)) and name.endswith('weight'):
                to_decay.add(name)
    decay_params.extend(params_dict[name] for name in sorted(to_decay))
    no_decay_params.extend(params_dict[name] for name in sorted(params_dict.keys() - to_decay))
param_groups = [
    {'params': decay_params, 'weight_decay': weight_decay},
    {'params': no_decay_params},
]
optimizer = optim.AdamW(param_groups, lr=1, weight_decay=0, betas=betas, eps=eps)
scheduler = LinearWarmUpCosineAnnealingLR(optimizer, **config['optim']['scheduler'])
scaler = GradScaler(config['control']['device'].split(':')[0], enabled=config['control']['enable_amp'])

# load pretrained weights (weights_only=False: official checkpoint contains numpy scalars)
# usage: _prepare_ckpt.py [source.pth]   (default: pretrained/mortal.pth)
src = sys.argv[1] if len(sys.argv) > 1 else 'pretrained/mortal.pth'
pret = torch.load(src, weights_only=False, map_location='cpu')
mortal.load_state_dict(pret['mortal'])
dqn.load_state_dict(pret['current_dqn'])
aux_net.load_state_dict(pret['aux_net'])
print('pretrained weights loaded; steps was', pret.get('steps'))

state = {
    'mortal': mortal.state_dict(),
    'current_dqn': dqn.state_dict(),
    'aux_net': aux_net.state_dict(),
    'optimizer': optimizer.state_dict(),
    'scheduler': scheduler.state_dict(),
    'scaler': scaler.state_dict(),
    'steps': 0,
    'timestamp': datetime.now().timestamp(),
    'best_perf': {'avg_rank': 4.0, 'avg_pt': -135.0},
    'config': config,
}

os.makedirs('output/my_finetuned_model', exist_ok=True)
out = 'output/my_finetuned_model/mortal.pth'
torch.save(state, out)
print('saved working checkpoint ->', out)

# sanity: reload with weights_only=True (as train.py does)
chk = torch.load(out, weights_only=True, map_location='cpu')
print('weights_only=True reload OK; keys:', list(chk.keys()))
print('scheduler peak/final/max_steps:', chk['scheduler']['peak'], chk['scheduler']['final'], chk['scheduler']['max_steps'])
print('optimizer lr:', [g['lr'] for g in chk['optimizer']['param_groups']])
print('scaler:', chk['scaler'])
