#!/usr/bin/env python3
"""GHL workflow JSON -> n8n workflow JSON translator.

Follows the established n8n patterns (S2.1/S2.5/S3.1 templates, pilot B.C/S1.1-E/L.4/E.1):
- Entry: webhook (POST, onReceived) -> Get Contact (Entry) -> first real step
- GHL API via httpRequest + HighLevel Bearer Auth (GS6kXBLE1ooZqLap)
- AI (chatgpt) -> Anthropic httpRequest (zbTTcix6JfkcbdFi), claude-sonnet-4-6
- Unknown action types -> noOp stub + node note + flag (never crash)

Returns (workflow_dict, meta) where meta has flags/stubs/brandlaw/actions.
"""
import json, hashlib, re

GHL_CRED = ("GS6kXBLE1ooZqLap", "HighLevel Bearer Auth")
ANTH_CRED = ("zbTTcix6JfkcbdFi", "Anthropic API Key")
LOC = "SsBG7j5KQAIP1SFP2Sca"
FROMNUM = "+19542808890"
RANDY_NAME = "Randy Reece"
RANDY_EMAIL = "randy@getreecewindows.com"
GC = "$('Get Contact (Entry)').first().json.contact"
TAGS = "(($('Get Contact (Entry)').first().json.contact?.tags)||[])"
CFS = "(($('Get Contact (Entry)').first().json.contact?.customFields)||[])"
CONTACT_ID = "{{ $('Get Contact (Entry)').first().json.contact.id }}"
STANDARD_FIELDS = {"firstName","lastName","name","email","phone","companyName","address1","city","state",
                   "postalCode","country","source","dnd","tags","timezone","website","type"}

def _nid(seed):
    h = hashlib.md5(seed.encode()).hexdigest()
    return "%s-%s-4%s-8%s-%s" % (h[:8], h[8:12], h[13:16], h[17:20], h[20:32])

class Builder:
    def __init__(self, code, name, templates):
        self.code=code; self.name=name; self.templates=templates or {}
        self.nodes=[]; self.conns={}; self.meta={"flags":[],"stubs":[],"brandlaw":[],"actions":set()}
        self._names=set()
    def flag(self,m): self.meta["flags"].append(m)
    def stub_flag(self,wf,st): self.meta["stubs"].append("%s (%s)"%(wf,st))
    def uniq(self,name):
        n=name[:120]; i=2
        while n in self._names: n="%s #%d"%(name[:110],i); i+=1
        self._names.add(n); return n
    def add(self,node): self.nodes.append(node); return node["name"]
    def connect(self,a,b,out=0,bi=0):
        if not a or not b: return
        m=self.conns.setdefault(a,{}).setdefault("main",[])
        while len(m)<=out: m.append([])
        m[out].append({"node":b,"type":"main","index":bi})
    # ---- node factories ----
    def webhook(self,path):
        nm=self.uniq("Webhook: %s Entry"%self.code)
        self.add({"id":_nid(self.code+"wh"),"name":nm,"type":"n8n-nodes-base.webhook","typeVersion":2,
            "position":[0,0],"webhookId":_nid(self.code+"whid"),
            "parameters":{"httpMethod":"POST","path":path,"responseMode":"onReceived","options":{}}}); return nm
    def get_contact(self):
        nm=self.uniq("Get Contact (Entry)")
        self.add(self._http(nm,_nid(self.code+"gc"),"GET",
            "=https://services.leadconnectorhq.com/contacts/{{ $json.body.contactId || $json.body.contact_id || $json.contactId }}",
            onerror="continueRegularOutput")); return nm
    def _http(self,name,nid,method,url,body=None,conv=False,onerror=None,cred=GHL_CRED,anthropic=False,pos=None):
        if anthropic:
            p={"method":"POST","url":"https://api.anthropic.com/v1/messages",
               "authentication":"predefinedCredentialType","nodeCredentialType":"httpMultipleHeadersAuth",
               "sendHeaders":True,"headerParameters":{"parameters":[{"name":"Content-Type","value":"application/json"}]},
               "sendBody":True,"specifyBody":"json","jsonBody":body,"options":{}}
            n={"id":nid,"name":name,"type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":pos or [0,0],
               "credentials":{"httpMultipleHeadersAuth":{"id":cred[0],"name":cred[1]}},"parameters":p,
               "retryOnFail":True,"maxTries":3,"waitBetweenTries":5000}
            return n
        ver = ("Version","2021-04-15") if conv else ("Version","2021-07-28")
        hs=[ver]; p={"method":method,"url":url,"authentication":"genericCredentialType",
                     "genericAuthType":"httpBearerAuth","sendHeaders":True}
        if body is not None:
            p["sendBody"]=True; p["specifyBody"]="json"; p["jsonBody"]=body; hs.append(("Content-Type","application/json"))
        hs.append(("Accept","application/json"))
        p["headerParameters"]={"parameters":[{"name":n,"value":v} for n,v in hs]}; p["options"]={}
        n={"id":nid,"name":name,"type":"n8n-nodes-base.httpRequest","typeVersion":4.2,"position":pos or [0,0],
           "credentials":{"httpBearerAuth":{"id":cred[0],"name":cred[1]}},"parameters":p,
           "retryOnFail":True,"maxTries":3,"waitBetweenTries":5000}
        if onerror: n["onError"]=onerror
        return n
    def http(self,name,method,url,body=None,conv=False,onerror=None,seed=""):
        nm=self.uniq(name); self.add(self._http(nm,_nid(self.code+seed+name),method,url,body,conv,onerror)); return nm
    def anthropic(self,name,system,user,maxtok,temp,seed=""):
        nm=self.uniq(name)
        body=json.dumps({"model":"claude-sonnet-4-6","max_tokens":maxtok,"temperature":float(temp or 0.2),
            "system":system or "","messages":[{"role":"user","content":user or ""}]})
        self.add(self._http(nm,_nid(self.code+seed+name),"POST",None,body=body,anthropic=True)); return nm
    def noop(self,name,note=None,seed=""):
        nm=self.uniq(name); n={"id":_nid(self.code+seed+name),"name":nm,"type":"n8n-nodes-base.noOp",
            "typeVersion":1,"position":[0,0],"parameters":{}}
        if note: n["notes"]=note
        self.add(n); return nm
    def wait(self,name,amount,unit,seed=""):
        nm=self.uniq(name); self.add({"id":_nid(self.code+seed+name),"name":nm,"type":"n8n-nodes-base.wait",
            "typeVersion":1.1,"position":[0,0],"parameters":{"amount":amount,"unit":unit}}); return nm
    def ifnode(self,name,expr,seed=""):
        nm=self.uniq(name); self.add({"id":_nid(self.code+seed+name),"name":nm,"type":"n8n-nodes-base.if",
            "typeVersion":2.2,"position":[0,0],"parameters":{"conditions":{"options":{"caseSensitive":True,
            "typeValidation":"loose"},"conditions":[{"id":_nid(name+"c"),"leftValue":expr,"rightValue":True,
            "operator":{"type":"boolean","operation":"equals"}}],"combinator":"and"},"options":{}}}); return nm
    def code_node(self,name,js,seed=""):
        nm=self.uniq(name); self.add({"id":_nid(self.code+seed+name),"name":nm,"type":"n8n-nodes-base.code",
            "typeVersion":2,"position":[0,0],"parameters":{"jsCode":js}}); return nm
    def sticky(self,content):
        nm=self.uniq("Note: %s"%self.code); self.add({"id":_nid(self.code+"sticky"),"name":nm,
            "type":"n8n-nodes-base.stickyNote","typeVersion":1,"position":[-80,-360],
            "parameters":{"content":content,"width":620,"height":420}}); return nm

# ---------- condition translation ----------
def js_str(s): return json.dumps(s)
def cond_atom(c, code, wh, flagger):
    sub=c.get("conditionSubType"); op=c.get("conditionOperator"); val=c.get("conditionValue")
    ctype=c.get("conditionType")
    vals = val if isinstance(val,list) else ([val] if val is not None else [])
    if ctype=="trigger" or sub=="trigger":
        return "(($('%s').first().json.body.trigger_id||$('%s').first().json.body.triggerId||'') === %s)"%(wh,wh,js_str(vals[0] if vals else ""))
    if sub=="tags":
        if op=="index-of-true":
            return "%s.some(x => %s.includes(x))"%(json.dumps(vals),TAGS)
        if op=="index-of-false":
            return "!%s.some(x => %s.includes(x))"%(json.dumps(vals),TAGS)
    cfid = c.get("conditionSubType") or c.get("field") or ""
    cfval="((%s.find(f => f.id === %s)||{}).value)"%(CFS, js_str(cfid))
    if op in ("string-matches-any-of","is-any-of"):
        return "%s.includes(%s)"%(json.dumps(vals),cfval)
    if op in ("not-in","string-matches-none-of"):
        return "!%s.includes(%s)"%(json.dumps(vals),cfval)
    if op=="==": return "%s == %s"%(cfval,js_str(vals[0] if vals else ""))
    if op=="!=": return "%s != %s"%(cfval,js_str(vals[0] if vals else ""))
    if op in (">","greater-than"): return "parseFloat(%s||'0') > %s"%(cfval,(vals[0] if vals else 0))
    if op in ("<","less-than"): return "parseFloat(%s||'0') < %s"%(cfval,(vals[0] if vals else 0))
    if op=="contains": return "String(%s||'').includes(%s)"%(cfval,js_str(vals[0] if vals else ""))
    flagger("untranslated condition op=%s sub=%s"%(op,sub))
    return "false"
def branch_expr(branch, code, wh, flagger):
    seg_exprs=[]
    for seg in branch.get("segments",[]):
        atoms=[cond_atom(c,code,wh,flagger) for c in seg.get("conditions",[])]
        joiner=" || " if seg.get("operator")=="or" else " && "
        if atoms: seg_exprs.append("("+joiner.join(atoms)+")")
    if not seg_exprs: return "true"
    joiner=" || " if branch.get("operator")=="or" else " && "
    return joiner.join(seg_exprs)

# ---------- main walker ----------
def slugpath(code,name):
    s=(code+" "+name).lower(); s=re.sub(r'[^a-z0-9]+','-',s).strip('-'); return s[:50]

def translate(src, templates):
    code=src.get("canonical_code"); name=src.get("canonical_name") or code
    b=Builder(code,name,templates)
    wh=b.webhook(slugpath(code,name)); gc=b.get_contact()
    steps=src.get("steps") or []
    smap={s["raw_json"]["raw"]["id"]:s for s in steps}
    def raw(s): return s["raw_json"]["raw"]
    def stype(s): return s.get("step_type")
    def nodetype(s): return raw(s).get("nodeType")
    def is_wrapper(s): return stype(s)=="transition" or nodetype(s) in ("branch-yes","branch-no")
    def next_of(s):
        nx=raw(s).get("next")
        if isinstance(nx,list): return nx
        return nx
    def resolve(sid, seen=None):
        seen=seen or set()
        while sid and sid in smap and is_wrapper(smap[sid]) and sid not in seen:
            seen.add(sid); nx=next_of(smap[sid])
            sid = nx[0] if isinstance(nx,list) else nx
        return sid
    info={}  # sid -> routing descriptor
    exit_node=[None]
    def exit_name():
        if exit_node[0] is None: exit_node[0]=b.noop("Exit (End)")
        return exit_node[0]
    last_ai=[None]
    def cid_expr(): return "$('Get Contact (Entry)').first().json.contact.id"
    def email_jsonbody(subj, html_part):
        return ("={{ JSON.stringify({ type:'Email', contactId: %s, subject: %s, html: %s, from: %s, fromName: %s }) }}"
                % (cid_expr(), js_str(subj or ""), html_part, js_str(RANDY_EMAIL), js_str(RANDY_NAME)))
    def build(s):
        t=stype(s); data=raw(s).get("data",{}) or {}; nm=raw(s).get("name") or t
        b.meta["actions"].add(t)
        try:
            if t=="wait":
                amt=raw(s).get("delay") or s.get("delay_minutes") or 0
                du=(raw(s).get("delayUnit") or "minutes").lower()
                unit="hours" if du.startswith("hour") else ("days" if du.startswith("day") else "minutes")
                n=b.wait("Wait %s %s"%(amt,unit),amt,unit,seed=s["raw_json"]["raw"]["id"])
                return {"entry":n,"exit":n,"kind":"linear"}
            if t=="add_contact_tag":
                n=b.http("Add Tags: %s"%(", ".join(data.get("tags",[]))[:60]),"POST",
                    "=https://services.leadconnectorhq.com/contacts/%s/tags"%CONTACT_ID,
                    body="={{ JSON.stringify({ tags: %s }) }}"%json.dumps(data.get("tags",[])),seed=s["raw_json"]["raw"]["id"])
                return {"entry":n,"exit":n,"kind":"linear"}
            if t=="remove_contact_tag":
                n=b.http("Remove Tags: %s"%(", ".join(data.get("tags",[]))[:55]),"DELETE",
                    "=https://services.leadconnectorhq.com/contacts/%s/tags"%CONTACT_ID,
                    body="={{ JSON.stringify({ tags: %s }) }}"%json.dumps(data.get("tags",[])),seed=s["raw_json"]["raw"]["id"])
                return {"entry":n,"exit":n,"kind":"linear"}
            if t in ("update_contact_field","create_update_contact"):
                cf=[]; std={}
                for f in data.get("fields",[]):
                    fid=f.get("field"); val="" if data.get("actionType")=="clear_field_data" else f.get("value")
                    if fid in STANDARD_FIELDS: std[fid]=val
                    else: cf.append({"id":fid,"value":val})
                payload={}
                if cf: payload["customFields"]=cf
                payload.update(std)
                bodyexpr="={{ JSON.stringify(%s) }}"%json.dumps(payload)
                n=b.http(nm[:60],"PUT","=https://services.leadconnectorhq.com/contacts/%s"%CONTACT_ID,body=bodyexpr,seed=s["raw_json"]["raw"]["id"])
                return {"entry":n,"exit":n,"kind":"linear"}
            if t=="add_to_workflow":
                wid=data.get("workflow_id") or data.get("workflowId")
                b.flag("add_to_workflow -> GHL API enroll wf=%s (retarget to n8n once migrated)"%wid)
                n=b.http("Enroll in Workflow %s"%(str(wid)[:8]),"POST",
                    "=https://services.leadconnectorhq.com/contacts/%s/workflow/%s"%(CONTACT_ID,wid),seed=s["raw_json"]["raw"]["id"])
                return {"entry":n,"exit":n,"kind":"linear"}
            if t=="remove_from_workflow":
                wid=data.get("workflow_id"); 
                if data.get("allWorkflows") or (isinstance(wid,list) and len(wid)>1):
                    b.stub_flag(nm,t); 
                    n=b.noop("[STUB] %s"%nm[:50],note="GHL bulk/all remove_from_workflow (%s targets). No single n8n equiv; retarget to orchestrator."%(len(wid) if isinstance(wid,list) else 'all'),seed=s["raw_json"]["raw"]["id"])
                    return {"entry":n,"exit":n,"kind":"linear"}
                single = wid[0] if isinstance(wid,list) else wid
                n=b.http("Remove from Workflow %s"%(str(single)[:8]),"DELETE",
                    "=https://services.leadconnectorhq.com/contacts/%s/workflow/%s"%(CONTACT_ID,single),onerror="continueRegularOutput",seed=s["raw_json"]["raw"]["id"])
                return {"entry":n,"exit":n,"kind":"linear"}
            if t=="chatgpt":
                ai=b.anthropic("AI: %s"%nm[:55],data.get("instructions"),data.get("promptText"),900,data.get("temperature"),seed=s["raw_json"]["raw"]["id"])
                last_ai[0]=ai
                return {"entry":ai,"exit":ai,"kind":"linear"}
            if t=="email":
                fn=(data.get("from_name") or "")
                if "mark" in fn.lower(): b.meta["brandlaw"].append("%s: email from_name=%r -> overridden to Randy Reece"%(code,fn))
                tid=data.get("template_id") or s.get("template_id")
                subj=data.get("subject") or (templates.get(tid,{}).get("subject") if tid else "") or "Reece Windows & Doors"
                bodytext=data.get("html") or data.get("body")
                if bodytext: html_part=js_str(bodytext)
                elif tid and tid in templates and templates[tid].get("body"): html_part=js_str(templates[tid]["body"])
                elif last_ai[0]: html_part="$('%s').first().json.content[0].text"%last_ai[0]
                else:
                    b.flag("email %r has no resolvable body (tid=%s)"%(nm,tid)); html_part=js_str("<p>{{contact.first_name}},</p>")
                n=b.http("Send Email: %s"%nm[:50],"POST","https://services.leadconnectorhq.com/conversations/messages",
                    body=email_jsonbody(subj,html_part),conv=True,seed=s["raw_json"]["raw"]["id"])
                return {"entry":n,"exit":n,"kind":"linear"}
            if t=="sms":
                body=data.get("body") or data.get("message") or ""
                if re.search(r'\brandy\b',body,re.I): b.meta["brandlaw"].append("%s: SMS body references 'Randy' (verify not used as sender)"%code)
                if "{{chatgpt" in body and last_ai[0]:
                    msg="$('%s').first().json.content[0].text"%last_ai[0]
                else: msg=js_str(body)
                jb="={{ JSON.stringify({ type:'SMS', contactId: %s, message: %s, fromNumber: %s }) }}"%(cid_expr(),msg,js_str(FROMNUM))
                n=b.http("Send SMS: %s"%nm[:52],"POST","https://services.leadconnectorhq.com/conversations/messages",body=jb,conv=True,seed=s["raw_json"]["raw"]["id"])
                return {"entry":n,"exit":n,"kind":"linear"}
            if t=="custom_code":
                n=b.code_node("Code: %s"%nm[:55],data.get("code") or "return $input.all();",seed=s["raw_json"]["raw"]["id"])
                return {"entry":n,"exit":n,"kind":"linear"}
            if t=="assign_user":
                ul=data.get("user_list") or []
                uid = ul[0] if ul else (data.get("customUserList") or "")
                val = "={{ JSON.stringify({ assignedTo: %s }) }}"%js_str(uid) if uid and "{{" not in str(uid) else "={{ JSON.stringify({ assignedTo: '%s' }) }}"%uid
                n=b.http("Assign User: %s"%nm[:50],"PUT","=https://services.leadconnectorhq.com/contacts/%s"%CONTACT_ID,body=val,seed=s["raw_json"]["raw"]["id"])
                return {"entry":n,"exit":n,"kind":"linear"}
            if t=="add_notes":
                html=data.get("html") or ""
                n=b.http("Add Note","POST","=https://services.leadconnectorhq.com/contacts/%s/notes"%CONTACT_ID,
                    body="={{ JSON.stringify({ body: %s }) }}"%js_str(re.sub('<[^>]+>','',html)),seed=s["raw_json"]["raw"]["id"])
                return {"entry":n,"exit":n,"kind":"linear"}
            if t in ("webhook","custom_webhook"):
                url=data.get("url"); method=data.get("method","POST")
                hdrs=[]
                for h in (data.get("headers") or []):
                    k=h.get("key"); v=h.get("value")
                    if k and k.lower()=="x-ghl-signature" and v and "{{" not in v:
                        v="={{ $env.LP_WEBHOOK_SIGNATURE }}"; b.flag("%s: inline x-ghl-signature replaced with $env.LP_WEBHOOK_SIGNATURE"%code)
                    if k: hdrs.append((k,v))
                bodyobj=None
                if t=="custom_webhook" and data.get("body",{}).get("rawData"): bodyexpr="="+data["body"]["rawData"]
                else:
                    kv={ (x.get("key")):(x.get("value")) for x in (data.get("customData") or []) }
                    bodyexpr="={{ JSON.stringify(%s) }}"%json.dumps(kv) if kv else None
                nm2=b.uniq(nm[:55]); node=b._http(nm2,_nid(code+s["raw_json"]["raw"]["id"]),method,url if url and url.startswith("http") else (url or ""),body=bodyexpr)
                node["parameters"]["headerParameters"]={"parameters":[{"name":k,"value":(v if v is not None else "")} for k,v in hdrs]} if hdrs else node["parameters"]["headerParameters"]
                b.add(node)
                return {"entry":nm2,"exit":nm2,"kind":"linear"}
            if t in ("create_opportunity","internal_update_opportunity"):
                pid=data.get("pipeline_id") or "x0cxXOkKwqAWVvcPdKZQ"; stg=data.get("pipeline_stage_id") or ""
                status=data.get("opportunity_status") or "open"
                find=b.http("Find Opp: %s"%nm[:45],"GET",
                    "=https://services.leadconnectorhq.com/opportunities/search?location_id=%s&contact_id=%s&pipeline_id=%s"%(LOC,CONTACT_ID,pid),seed=s["raw_json"]["raw"]["id"]+"f")
                iff=b.ifnode("Opp Found? %s"%nm[:35],"={{ (($('%s').first().json.opportunities)||[]).length > 0 }}"%find,seed=s["raw_json"]["raw"]["id"]+"if")
                upd=b.http("Update Opp Stage: %s"%nm[:40],"PUT",
                    "=https://services.leadconnectorhq.com/opportunities/{{ $('%s').first().json.opportunities[0].id }}"%find,
                    body="={{ JSON.stringify({ pipelineId: %s, pipelineStageId: %s, status: %s }) }}"%(js_str(pid),js_str(stg),js_str(status)),seed=s["raw_json"]["raw"]["id"]+"u")
                crt=b.http("Create Opp: %s"%nm[:45],"POST","https://services.leadconnectorhq.com/opportunities/",
                    body="={{ JSON.stringify({ locationId: %s, pipelineId: %s, pipelineStageId: %s, contactId: %s, name: (%s.name||%s), status: %s }) }}"%(js_str(LOC),js_str(pid),js_str(stg),cid_expr(),GC,js_str(code+" Lead"),js_str(status)),seed=s["raw_json"]["raw"]["id"]+"c")
                ready=b.noop("Opp Ready: %s"%nm[:40],seed=s["raw_json"]["raw"]["id"]+"r")
                b.connect(find,iff); b.connect(iff,upd,0); b.connect(iff,crt,1); b.connect(upd,ready); b.connect(crt,ready)
                return {"entry":find,"exit":ready,"kind":"linear"}
            if t=="if_else":
                branches=data.get("branches") or []
                if not branches:  # wrapper-like leaf (shouldn't reach as real); treat passthrough
                    n=b.noop(nm[:55],seed=s["raw_json"]["raw"]["id"]); return {"entry":n,"exit":n,"kind":"linear"}
                if len(branches)>1: b.flag("%s: multi-branch if_else %r collapsed to first branch (+else)"%(code,data.get("conditionName")))
                expr="={{ %s }}"%branch_expr(branches[0],code,wh,b.flag)
                nx=raw(s).get("next") or []
                ifn=b.ifnode("%s"%(data.get("conditionName") or nm)[:55],expr,seed=s["raw_json"]["raw"]["id"])
                yes=nx[0] if len(nx)>0 else None; no=nx[1] if len(nx)>1 else None
                return {"entry":ifn,"kind":"if","ifnode":ifn,"true":yes,"false":no}
            if t=="find_contact":
                ifn=b.ifnode("Contact Found? %s"%nm[:35],"={{ !!%s?.id }}"%GC,seed=s["raw_json"]["raw"]["id"])
                trs=data.get("transitions",[]); found=notf=None
                for tr in trs:
                    if tr.get("condition")=="contact_found": found=tr.get("id")
                    elif tr.get("condition")=="contact_not_found": notf=tr.get("id")
                return {"entry":ifn,"kind":"if","ifnode":ifn,"true":found,"false":notf}
            if t=="find_opportunity":
                find=b.http("Find Opp: %s"%nm[:45],"GET",
                    "=https://services.leadconnectorhq.com/opportunities/search?location_id=%s&contact_id=%s"%(LOC,CONTACT_ID),seed=s["raw_json"]["raw"]["id"]+"f")
                ifn=b.ifnode("Opp Found? %s"%nm[:35],"={{ (($('%s').first().json.opportunities)||[]).length > 0 }}"%find,seed=s["raw_json"]["raw"]["id"])
                b.connect(find,ifn)
                trs=data.get("transitions",[]); found=notf=None
                for tr in trs:
                    nmn=(tr.get("name") or "").lower()
                    if "not" in nmn: notf=tr.get("id")
                    else: found=tr.get("id")
                return {"entry":find,"kind":"if","ifnode":ifn,"true":found,"false":notf}
            if t=="goto":
                n=b.noop("Go To",seed=s["raw_json"]["raw"]["id"])
                return {"entry":n,"exit":n,"kind":"goto","target":data.get("targetNodeId")}
            if t=="workflow_split":
                b.stub_flag(nm,t)
                n=b.noop("[STUB] Split: %s"%nm[:45],note="GHL workflow_split (weighted/random). Routed to first path; implement Code-based split if needed.",seed=s["raw_json"]["raw"]["id"])
                paths=data.get("paths",[]); 
                return {"entry":n,"exit":n,"kind":"linear","_splitfirst":paths[0]["id"] if paths else None}
            # ---- stubbed action types ----
            b.stub_flag(nm,t)
            n=b.noop("[STUB] %s"%nm[:50],note="Unmapped GHL action '%s'. Intended: %s. Implement before go-live."%(t,nm),seed=s["raw_json"]["raw"]["id"])
            return {"entry":n,"exit":n,"kind":"linear"}
        except Exception as e:
            b.stub_flag(nm,"%s ERROR:%s"%(t,e)); n=b.noop("[STUB-ERR] %s"%nm[:45],note="translation error: %s"%e,seed=s["raw_json"]["raw"]["id"]+"err")
            return {"entry":n,"exit":n,"kind":"linear"}
    # build all real steps
    for s in steps:
        if is_wrapper(s): continue
        info[s["raw_json"]["raw"]["id"]]=build(s)
    def entry_of(sid):
        r=resolve(sid)
        if r and r in info: return info[r]["entry"]
        return exit_name()
    # wire
    for s in steps:
        if is_wrapper(s): continue
        sid=s["raw_json"]["raw"]["id"]; d=info[sid]
        if d["kind"]=="if":
            b.connect(d["ifnode"], entry_of(d.get("true")), 0)
            b.connect(d["ifnode"], entry_of(d.get("false")), 1)
        elif d["kind"]=="goto":
            b.connect(d["entry"], entry_of(d.get("target")))
        else:
            nx=next_of(s)
            if isinstance(nx,list): nx=nx[0] if nx else None
            tgt = d.get("_splitfirst") or nx
            if tgt: b.connect(d["exit"], entry_of(tgt))
    # connect entry chain
    b.connect(wh,gc)
    if steps:
        b.connect(gc, entry_of(steps[0]["raw_json"]["raw"]["id"]))
    else:
        b.flag("source has 0 steps (trigger-only or actions not in export)")
        b.connect(gc, b.noop("Exit (No Steps)"))
    # layout: simple grid in creation order
    for i,n in enumerate(b.nodes):
        if n["type"]=="n8n-nodes-base.stickyNote": continue
        n["position"]=[ (i%8)*280, (i//8)*180 ]
    # trigger summary sticky
    trg="; ".join("%s:%s"%(t.get("trigger_event"),(t.get("raw_json",{}).get("name") or '')) for t in (src.get("triggers") or [])) or "none in export"
    b.sticky("## %s\nTranslated from GHL workflow %s.\nGHL triggers: %s\n\nEntry is a webhook (orchestrator-driven). Credentials by ID only; brand law applied to email senders (Randy Reece). See workflow node notes for [STUB] items.\nFlags: %d | Stubs: %d | Brand-law: %d"%(
        name, src.get("workflow_id"), trg[:300], len(b.meta["flags"]), len(b.meta["stubs"]), len(b.meta["brandlaw"])))
    b.meta["actions"]=sorted(b.meta["actions"])
    wf={"name":name,"nodes":b.nodes,"connections":b.conns,"settings":{"executionOrder":"v1"}}
    return wf, b.meta

if __name__=="__main__":
    import sys
    src=json.load(open(sys.argv[1])); templates=json.load(open(sys.argv[2])) if len(sys.argv)>2 else {}
    wf,meta=translate(src,templates)
    json.dump(wf,open(sys.argv[3],"w"),indent=2) if len(sys.argv)>3 else None
    print(json.dumps({"name":wf["name"],"nodes":len(wf["nodes"]),"meta":{k:(v if not isinstance(v,set) else sorted(v)) for k,v in meta.items()}},indent=2))
