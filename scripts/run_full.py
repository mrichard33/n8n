#!/usr/bin/env python3
import json, os, subprocess, urllib.request, sys
sys.path.insert(0,'/home/user/n8n/scripts')
import ghl_to_n8n as T

REPO="/home/user/n8n"; WFDIR=REPO+"/workflows"; GHL="/home/user/GHL-Workflows"
BASE="https://n8n-main-instance-production-981e.up.railway.app"
KEY=os.environ["N8N_API_KEY"]
templates=json.load(open("/tmp/templates.json"))
q=json.load(open("/tmp/queue.json")); order=q["order"]; code2file=q["code2file"]
TRAILER="\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_01FirPTXFHk3BrniEVe1fumD"

def post(wf):
    data=json.dumps(wf).encode()
    req=urllib.request.Request(BASE+"/api/v1/workflows",data=data,
        headers={"X-N8N-API-KEY":KEY,"Content-Type":"application/json"},method="POST")
    try:
        r=urllib.request.urlopen(req,timeout=120); d=json.load(r); return r.status,d.get("id"),d.get("active")
    except urllib.error.HTTPError as e:
        return e.code, None, e.read().decode()[:300]
    except Exception as e:
        return -1, None, str(e)[:300]

report=[]
start=int(sys.argv[1]) if len(sys.argv)>1 else 0
end=int(sys.argv[2]) if len(sys.argv)>2 else len(order)
for code in order[start:end]:
    fn=code2file[code]; src=json.load(open(GHL+"/"+fn))
    name=src.get("canonical_name") or code
    try:
        wf,meta=T.translate(src,templates)
    except Exception as e:
        report.append({"code":code,"error":"translate:%s"%e}); print("TRANSLATE FAIL",code,e); continue
    outpath=WFDIR+"/"+fn
    json.dump(wf,open(outpath,"w"),indent=2)
    # validate
    try: json.load(open(outpath))
    except Exception as e:
        report.append({"code":code,"error":"invalidjson:%s"%e}); print("BADJSON",code,e); continue
    status,wid,extra=post(wf)
    ok = status in (200,201) and wid
    # commit regardless (preserve), note import status
    subprocess.run(["git","-C",REPO,"add",outpath],check=True)
    msg="feat(%s): translate from GHL — %s%s"%(code,name,TRAILER)
    if not ok: msg="feat(%s): translate from GHL — %s [import:%s]%s"%(code,name,status,TRAILER)
    subprocess.run(["git","-C",REPO,"commit","-q","-m",msg],check=True)
    rec={"code":code,"name":name,"file":fn,"nodes":len(wf["nodes"]),"wid":wid,"active":extra if not ok else False,
         "import_status":status,"flags":meta["flags"],"stubs":meta["stubs"],"brandlaw":meta["brandlaw"],"actions":meta["actions"]}
    if not ok: rec["import_error"]=extra
    report.append(rec)
    print("%-9s nodes=%-3d import=%s id=%s stubs=%d flags=%d bl=%d"%(code,len(wf["nodes"]),status,wid,len(meta["stubs"]),len(meta["flags"]),len(meta["brandlaw"])))

old=[]
if os.path.exists("/tmp/report.json"):
    try: old=json.load(open("/tmp/report.json"))
    except: old=[]
json.dump(old+report,open("/tmp/report.json","w"),indent=2)
print("\nBATCH DONE: %d processed"%len(report))
