"""Create a fresh distribution from an explicit file allowlist. No private data."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from release_info import APP_VERSION

FILES=('START.bat','STOP.bat','TEKSHIRISH.bat','IMPORT_HISTORY.bat',
       'AI_TEST.bat','AI_DIAG.bat','AI_HYBRID_TEST.bat','.env.example',
       'catalog.example.json','README_UZ.md')


def build(root,exe,destination,commit=''):
    root,exe,destination=Path(root),Path(exe),Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Distribution destination must be empty')
    if not exe.is_file() or exe.read_bytes()[:2]!=b'MZ':
        raise ValueError('A real Windows build must be provided')
    for name in FILES:
        if not (root/name).is_file():
            raise ValueError('Missing distribution file: '+name)
    template=(root/'.env.example').read_text(encoding='utf-8-sig')
    for line in template.splitlines():
        if line.strip().startswith('TELEGRAM_BOT_TOKEN=') and line.split('=',1)[1].strip():
            raise ValueError('Template must not contain a token')
    destination.mkdir(parents=True,exist_ok=True)
    for name in FILES:
        shutil.copy2(root/name,destination/name)
    shutil.copy2(exe,destination/'PropanBot.exe')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.iterdir() if p.is_file()}
    manifest={'version':APP_VERSION,'commit':commit,'files_sha256':hashes,
              'private_files_included':False,'ai_in_live_bot':True,
              'keep_from_previous_install':['.env','data/']}
    (destination/'RELEASE_INFO.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe',required=True)
    parser.add_argument('--dest',required=True)
    parser.add_argument('--commit',default='')
    args=parser.parse_args()
    result=build(ROOT,args.exe,args.dest,args.commit)
    print(result['version']+': clean distribution prepared; .env and data excluded.')
