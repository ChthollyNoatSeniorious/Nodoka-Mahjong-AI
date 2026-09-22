raw = open('config.toml', encoding='utf-8-sig').read()
out = raw.replace("log_dir = './output/1v3'", "log_dir = './output/1v3_speed'")
out = out.replace('games_per_iter = 40', 'games_per_iter = 4')
out = out.replace(
    "state_file = './output/my_finetuned_model/mortal.pth'",
    "state_file = './output/my_finetuned_model/distill_snaps_v3/step344000.pth'",
)
open('config_speed.toml', 'w', encoding='utf-8', newline='\n').write(out)
import toml
cfg = toml.load(open('config_speed.toml', encoding='utf-8'))
print('toml ok, games_per_iter =', cfg['1v3']['games_per_iter'])
print('challenger =', cfg['1v3']['challenger']['state_file'])
print('champion =', cfg['1v3']['champion']['state_file'])
print('log_dir =', cfg['1v3']['log_dir'])