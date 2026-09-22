# Run after output/selfplay/ has 500 logs (job pwsh-17):
#   .\distill 混合自对弈谱 v4
# From the `mortal` directory. Sets: epochs 8, lr 1e-5, selfplay 50%,
# selfplay logs = new 500 + old 100 (1v3_100) + old 40 (output/1v3).
$env:HTTP_PROXY=''
$env:HTTPS_PROXY=''
$env:MORTAL_CFG='config.toml'
$out = 'output/my_finetuned_model/distill_ah_v4.pth'
$snap = 'output/my_finetuned_model/distill_snaps_v4'
New-Item -ItemType Directory -Force -Path $snap | Out-Null
..\.venv\Scripts\python.exe -u distill.py `
  --state-file output/my_finetuned_model/distill_snaps_v3/step344000.pth `
  --distill-dir .\distill `
  --out $out `
  --epochs 4 --lr 1e-5 --tau 1.0 `
  --w-distill 1.0 --w-hard 1.0 --grad-clip 1.0 `
  --batch-size 32 `
  --save-every 2000 --snapshot-dir $snap `
  --num-workers 2 --split train --val-frac 0.15 `
  --selfplay-globs "./output/1v3_100/*.json.gz,./output/1v3/*.json.gz,./output/selfplay/*.json.gz" `
  --selfplay-frac 0.5 `
  > ..\reviewer\out\_distill_v4.log 2>&1
Write-Output "EXIT=$LASTEXITCODE"