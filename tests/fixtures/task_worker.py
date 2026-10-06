"""Deterministic subprocess for lifecycle tests; no network calls."""
import json
import subprocess
import sys
import time
from pathlib import Path

folder, mode = Path(sys.argv[1]), sys.argv[2]
folder.mkdir(parents=True, exist_ok=True)
if mode == 'tree':
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    (folder / 'child.pid').write_text(str(child.pid))
print('harbor-processing:' + json.dumps('测试后处理'), flush=True)
if mode == 'error':
    print('测试后处理失败', flush=True)
    sys.exit(1)
deadline = time.monotonic() + 15
while not (folder / 'release').exists():
    if time.monotonic() > deadline:
        sys.exit(2)
    time.sleep(0.01)
target = folder / 'complete.mp4'
target.write_bytes(b'test-media')
print('harbor-file:' + json.dumps(str(target)), flush=True)
