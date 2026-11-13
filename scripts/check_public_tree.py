"""Inspect the files that will be published, without printing sensitive matches."""
import argparse,hashlib,json,re,subprocess,struct
from pathlib import Path
PRIVATE_IP=re.compile(r'(?<!\d)(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?!\d)')
EMAIL=re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
HOME=re.compile(r'(?i)[a-z]:[/\\]+users[/\\]+[^\s\'"]+|/(?:Users|home)/[^/\s\'"]+')
BLOCKED_SUFFIX={'.wewf','.exml','.zip','.skill','.class','.jar','.clixml','.pfx','.p12','.pem','.key','.pdf','.csv','.html','.log'}
BLOCKED_NAMES={'connection.json','credential.clixml','workflow.json','evidence.json','agent-context.json','module.json','technical-evidence.json'}
SKIP={'.git','.local','.venv','venv','__pycache__','dist','build','.pytest_cache'}
def png_metadata(raw):
 if not raw.startswith(b'\x89PNG\r\n\x1a\n'):return True
 p=8
 while p<len(raw):
  n=struct.unpack('>I',raw[p:p+4])[0];kind=raw[p+4:p+8]
  if kind not in {b'IHDR',b'PLTE',b'tRNS',b'sRGB',b'gAMA',b'cHRM',b'pHYs',b'IDAT',b'IEND'}:return True
  p+=12+n
 return p!=len(raw)
def inspect_bytes(name,raw,markers=()):
 path=Path(name);issues=[]
 if path.suffix.lower() in BLOCKED_SUFFIX or path.name in BLOCKED_NAMES or any(x in SKIP for x in path.parts):issues.append('excluded_artifact')
 if path.suffix.lower()=='.png':
  if png_metadata(raw):issues.append('image_metadata')
  return issues
 try:text=raw.decode('utf-8-sig')
 except UnicodeError:return issues+['unreviewed_binary']
 if any(x and x.casefold() in text.casefold() for x in markers):issues.append('local_marker')
 if PRIVATE_IP.search(text):issues.append('private_address')
 if HOME.search(text):issues.append('personal_home_path')
 if any(not m[0].lower().endswith(('.invalid','.test','@example.com','@example.org','@example.net')) for m in EMAIL.finditer(text)):issues.append('nonexample_email')
 if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',text):issues.append('private_key')
 if re.search(r'(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])',text):issues.append('access_key')
 return issues
def inspect_tree(root,staged=False,markers=()):
 root=Path(root).resolve();issues=[]
 if staged:
  names=[x for x in subprocess.check_output(['git','-C',str(root),'ls-files','-z']).decode().split('\0') if x]
 else:names=[p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and not any(x in SKIP or x.endswith('.egg-info') for x in p.relative_to(root).parts)]
 for name in names:
  raw=subprocess.check_output(['git','-C',str(root),'show',':'+name]) if staged else (root/name).read_bytes()
  found=inspect_bytes(name,raw,markers)
  if found:issues.append({'file':name,'categories':found})
 return len(names),issues
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--staged',action='store_true');p.add_argument('--local-policy',type=Path);p.add_argument('--check-history',action='store_true');a=p.parse_args()
 markers=json.loads(a.local_policy.read_text('utf-8'))['forbidden_markers'] if a.local_policy else ()
 count,issues=inspect_tree(a.root,a.staged,markers)
 if a.check_history:
  identities=subprocess.check_output(['git','-C',str(a.root),'log','--all','--format=%an <%ae>|%cn <%ce>']).decode().splitlines()
  allowed='Ecology9AI Maintainers <maintainers@example.invalid>'
  if any(x!=allowed+'|'+allowed for x in identities):issues.append({'file':'git-history','categories':['nonproject_identity']})
 print(json.dumps({'status':'passed' if not issues else 'failed','files_checked':count,'issues':issues},ensure_ascii=True))
 return bool(issues)
if __name__=='__main__':raise SystemExit(main())
