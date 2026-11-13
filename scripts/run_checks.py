"""Run public synthetic suites; logs remain in an ignored local folder."""
import json,subprocess,sys,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SUITES=['tools/oa-workflow-analyzer','tools/oa-module-analyzer','tools/oa-foundation','tools/oa-audit','workbuddy-experts','scripts']
def main():
 logdir=ROOT/'.local/test-logs';logdir.mkdir(parents=True,exist_ok=True);results=[]
 env={**os.environ,'PYTHONUTF8':'1','PYTHONIOENCODING':'utf-8','PYTHONPATH':str(ROOT/'tools/oa-workflow-analyzer/src')+os.pathsep+os.environ.get('PYTHONPATH','')}
 for suite in SUITES:
  r=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/suite/'tests'),'-q'],cwd=ROOT,env=env,capture_output=True)
  name=suite.replace('/','-');(logdir/(name+'.txt')).write_bytes(r.stdout+r.stderr)
  summary=[line for line in (r.stdout+r.stderr).decode('utf-8','replace').splitlines() if line.startswith(('Ran ','OK','FAILED','ERROR:','FAIL:'))]
  results.append({'suite':suite,'passed':r.returncode==0,'summary':summary})
 privacy=subprocess.run([sys.executable,str(ROOT/'scripts/check_public_tree.py')],cwd=ROOT,capture_output=True)
 print(json.dumps({'suites':results,'privacy_check_passed':privacy.returncode==0},ensure_ascii=True,indent=2))
 return 0 if all(x['passed'] for x in results) and privacy.returncode==0 else 1
if __name__=='__main__':raise SystemExit(main())
