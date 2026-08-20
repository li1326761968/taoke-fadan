# 自动构建脚本
python -m pip install --upgrade pip
pip install requests pyinstaller
pyinstaller --noconfirm --clean --noupx --onefile --windowed --name "taoke-fadan" --hidden-import=zhetaoke_api --hidden-import=copy_generator --hidden-import=napcat_sender --hidden-import=qq_monitor --hidden-import=jd_union_api --hidden-import=auto_updater --hidden-import=license main.py
if (Test-Path config.json) { Copy-Item config.json dist/config.json }
