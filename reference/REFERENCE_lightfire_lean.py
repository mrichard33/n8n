#!/usr/bin/env python3
"""Reece Windows & Doors — Lightfire Partner Performance Review (lean edition), 18 Aug 2026."""

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, PageBreak,
                               PageTemplate, Paragraph, Spacer, Table, TableStyle)

OUT = "/mnt/user-data/outputs/Lightfire_Partner_Performance_Review_2026-08-17.pdf"

INK=colors.HexColor("#12181F"); SLATE=colors.HexColor("#5A6673")
RULE=colors.HexColor("#D4DAE0"); BAND=colors.HexColor("#F1F4F7")
NAVY=colors.HexColor("#12395B"); RED=colors.HexColor("#A3231C")
AMBER=colors.HexColor("#8A5A05"); GREEN=colors.HexColor("#1D6236"); LF=colors.HexColor("#1F6F8B")
G="#1D6236"; R="#A3231C"; A="#8A5A05"; N="#12395B"; LFH="#1F6F8B"

def st(n,**k):
    b=dict(name=n,fontName="Helvetica",fontSize=9.3,leading=13,textColor=INK,alignment=TA_LEFT)
    b.update(k); return ParagraphStyle(**b)
S={"title":st("title",fontName="Helvetica-Bold",fontSize=20,leading=23,textColor=NAVY,spaceAfter=2),
 "sub":st("sub",fontSize=10.5,leading=14,textColor=SLATE,spaceAfter=1),
 "h1":st("h1",fontName="Helvetica-Bold",fontSize=13,leading=16,textColor=NAVY,spaceBefore=10,spaceAfter=4),
 "h2":st("h2",fontName="Helvetica-Bold",fontSize=10,leading=13,spaceBefore=8,spaceAfter=3),
 "body":st("body",spaceAfter=5.0),
 "bullet":st("bullet",leftIndent=12,bulletIndent=3,spaceAfter=3),
 "small":st("small",fontSize=7.8,leading=10.0,textColor=SLATE,spaceAfter=3),
 "cell":st("cell",fontSize=8.1,leading=10.5),
 "cellb":st("cellb",fontSize=8.1,leading=10.5,fontName="Helvetica-Bold"),
 "cellh":st("cellh",fontSize=7.9,leading=10,fontName="Helvetica-Bold",textColor=colors.white),
 "kpin":st("kpin",fontName="Helvetica-Bold",fontSize=15,leading=17,textColor=NAVY),
 "kpil":st("kpil",fontSize=7.2,leading=9,textColor=SLATE),
 "call":st("call",fontSize=9.2,leading=12.8,leftIndent=8,rightIndent=6,spaceBefore=2,spaceAfter=2),
 "cap":st("cap",fontSize=7.6,leading=9.6,textColor=SLATE,spaceBefore=2,spaceAfter=6)}
def P(t,s="body"): return Paragraph(t,S[s])
def bl(x): return [Paragraph(t,S["bullet"],bulletText="\u2022") for t in x]
def C(c,t): return Paragraph('<b><font color="%s">%s</font></b>'%(c,t),S["cell"])

def table(header,rows,widths,aligns=None,hl=None,hlc=None):
    body=[[Paragraph(h,S["cellh"]) for h in header]]
    for r in rows: body.append([c if isinstance(c,Paragraph) else Paragraph(str(c),S["cell"]) for c in r])
    cmds=[("BACKGROUND",(0,0),(-1,0),NAVY),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
          ("TOPPADDING",(0,0),(-1,-1),3.0),("BOTTOMPADDING",(0,0),(-1,-1),3.0),
          ("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5),
          ("LINEBELOW",(0,0),(-1,-2),0.4,RULE),("LINEBELOW",(0,-1),(-1,-1),0.7,RULE)]
    for i in range(1,len(body)):
        if i%2==0: cmds.append(("BACKGROUND",(0,i),(-1,i),BAND))
    for c,a in (aligns or []): cmds.append(("ALIGN",(c,0),(c,-1),a))
    for i in (hl or []): cmds.append(("BACKGROUND",(0,i),(-1,i),hlc or colors.HexColor("#E8F1F5")))
    t=Table(body,colWidths=widths,hAlign="LEFT",repeatRows=1); t.setStyle(TableStyle(cmds)); return t

def kpis(items,w):
    cmds=[("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7),
          ("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),5),
          ("BACKGROUND",(0,0),(-1,-1),BAND),("BOX",(0,0),(-1,-1),0.4,RULE),
          ("BOTTOMPADDING",(0,0),(-1,0),1),("TOPPADDING",(0,1),(-1,1),0)]
    for i in range(1,len(items)): cmds.append(("LINEBEFORE",(i,0),(i,-1),0.4,RULE))
    t=Table([[Paragraph(f'<font color="{c}">{v}</font>',S["kpin"]) for v,l,c in items],
             [Paragraph(l,S["kpil"]) for v,l,c in items]],
            colWidths=[w/len(items)]*len(items),hAlign="LEFT")
    t.setStyle(TableStyle(cmds)); return t

def callout(title,text,accent):
    t=Table([[Paragraph(f'<b><font color="{accent}">{title}</font></b><br/>{text}',S["call"])]],
            colWidths=[6.9*inch],hAlign="LEFT")
    t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),BAND),("LINEBEFORE",(0,0),(0,-1),2.4,accent),
      ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6),
      ("LEFTPADDING",(0,0),(-1,-1),7),("RIGHTPADDING",(0,0),(-1,-1),7)])); return t

def chart(p,w=6.9*inch):
    from PIL import Image as PI
    iw,ih=PI.open(p).size; return Image(p,width=w,height=w*ih/iw)

def furn(c,d):
    c.saveState(); w,h=letter
    c.setStrokeColor(RULE); c.setLineWidth(0.5)
    c.line(0.75*inch,h-0.6*inch,w-0.75*inch,h-0.6*inch)
    c.setFont("Helvetica",7.3); c.setFillColor(SLATE)
    c.drawString(0.75*inch,h-0.53*inch,"Reece Windows & Doors  \u00b7  Lightfire Partner Performance Review")
    c.drawRightString(w-0.75*inch,h-0.53*inch,"18 August 2026")
    c.line(0.75*inch,0.58*inch,w-0.75*inch,0.58*inch)
    c.setFont("Helvetica",7.3)
    c.drawString(0.75*inch,0.42*inch,"Six-week review to 15 August 2026  \u00b7  Confidential")
    c.drawRightString(w-0.75*inch,0.42*inch,f"Page {c.getPageNumber()}")
    c.restoreState()

doc=BaseDocTemplate(OUT,pagesize=letter,leftMargin=0.75*inch,rightMargin=0.75*inch,
  topMargin=0.8*inch,bottomMargin=0.75*inch,
  title="Reece Windows & Doors — Lightfire Partner Performance Review, 18 August 2026",
  author="Reece Windows & Doors — Call Center Operations")
doc.addPageTemplates([PageTemplate(id="s",frames=[Frame(doc.leftMargin,doc.bottomMargin,doc.width,doc.height,
  id="f",leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],onPage=furn)])
W=doc.width; s=[]

# ================= PAGE 1
s.append(P("Lightfire Partner Performance Review","title"))
s.append(P("Appointments set 6 July \u2013 15 August 2026 whose date has passed \u00b7 issued 18 August","sub"))
s.append(Spacer(1,8))

s.append(kpis([
 ("65.8%","Your sit % against<br/>our 80% goal",R),
 ("78.9%","Reece setters,<br/>same measure",N),
 ("38%","Your appointments with<br/>no confirmer of record",R),
 ("0","Sales from 244 appts with<br/>no confirmer, either team",R),
 ("12 \u2192 4","Your agents on our<br/>dialler, in one week",R),
],W))
s.append(Spacer(1,9))

s.append(callout("The whole review in one paragraph",
 "Sit % \u2014 sits divided by issued appointments net of cancellations \u2014 is the number our floor is "
 "managed to, and our standard is <b>80%</b>. Your book runs <b>65.8%</b>, ours 78.9%; neither of us is where we "
 "want to be. The cause is not qualification and not the leads you work: <b>38% of Lightfire-set appointments "
 "have no confirmer of record, against 11% of ours</b>, and once confirmation status is held constant we find no "
 "statistically distinguishable difference between the two teams. <b>A substantial share of that fix is "
 "ours</b> \u2014 our desk covers 22% of your book and 87% of our own. We are asking for a shared "
 "confirmation-ownership rule, your bench restaffed, and sit % reported weekly by agent.", NAVY))

s.append(P("Credit first, because it is earned","h2"))
s.extend(bl([
 "<b>Craig Deer sets more appointments than any setter in our company</b> \u2014 152 in six weeks, 49 in the week of 9 August alone.",
 "<b>Carla Wright doubled her output</b> (13 \u2192 26), and your three staffed agents raised combined output 31% while covering an absent bench.",
 "<b>Your confirmed appointments hold up</b> \u2014 they issue at 85.1% against our 92.9%.",
]))

s.append(P("1.  Issued Sit % by agent against the 80% goal","h1"))
s.append(P(
 "<b>Issued Sit %</b> = sits \u00f7 (gross issued \u2212 cancels). Section 3 uses <b>Matured Sit %</b> (sits "
 "\u00f7 all matured appointments), necessarily lower. The two are not comparable.","small"))
s.append(table(
 ["Agent","Gross issued","Cancels","Net issued","Sits","Issued Sit %","vs goal","Sits short"],
 [["Gordon, Grecian *","7","1","6","6",C(G,"100.0%"),C(G,"+20.0"),"\u2014"],
  ["Dennis, Jodian *","7","0","7","6",C(G,"85.7%"),C(G,"+5.7"),"\u2014"],
  ["Martin, Nickalos *","7","1","6","5",C(G,"83.3%"),C(G,"+3.3"),"\u2014"],
  ["Slowely, Diamoneke *","17","0","17","14",C(G,"82.4%"),C(G,"+2.4"),"\u2014"],
  ["Bryce, Shaday *","8","0","8","6",C(A,"75.0%"),C(A,"\u22125.0"),"0.4"],
  [Paragraph("<b>Wright, Carla</b>",S["cellb"]),"30","0","30","20",C(R,"66.7%"),C(R,"\u221213.3"),"4.0"],
  [Paragraph("<b>Walker, Shari</b>",S["cellb"]),"34","0","34","22",C(R,"64.7%"),C(R,"\u221215.3"),"5.2"],
  [Paragraph("<b>Deer, Craig</b>",S["cellb"]),"99","2","97","60",C(R,"61.9%"),C(R,"\u221218.1"),
   Paragraph("<b>17.6</b>",S["cellb"])],
  ["Evans, Tresharna *","13","0","13","8",C(R,"61.5%"),C(R,"\u221218.5"),"2.4"],
  ["Campbell, Brittany *","5","0","5","3",C(R,"60.0%"),C(R,"\u221220.0"),"1.0"],
  ["Francis, Yanique *","11","0","11","4",C(R,"36.4%"),C(R,"\u221243.6"),"4.8"],
  [Paragraph("<b>Lightfire total</b>",S["cellb"]),Paragraph("<b>238</b>",S["cellb"]),
   Paragraph("<b>4</b>",S["cellb"]),Paragraph("<b>234</b>",S["cellb"]),Paragraph("<b>154</b>",S["cellb"]),
   Paragraph("<b>65.8%</b>",S["cellb"]),C(R,"\u221214.2"),Paragraph("<b>33</b>",S["cellb"])],
  [Paragraph("<b>Reece setters, same basis</b>",S["cellb"]),"570","7","563","444",
   Paragraph("<b>78.9%</b>",S["cellb"]),C(A,"\u22121.1"),"6"]],
 [1.42*inch,0.75*inch,0.58*inch,0.66*inch,0.44*inch,0.6*inch,0.62*inch,0.63*inch],
 aligns=[(1,"CENTER"),(2,"CENTER"),(3,"CENTER"),(4,"CENTER"),(5,"CENTER"),(6,"CENTER"),(7,"CENTER")],
 hl=[6,7,8,12]))
s.append(Spacer(1,4))
s.append(P(
 "* denominator under 20 \u2014 shown for completeness, not judgement. <b>The three agents carrying real "
 "volume are the ones that matter: Deer 61.9%, Walker 64.7%, Wright 66.7%.</b> Bringing your book to 80% is "
 "<b>33 more sits over six weeks</b> \u2014 at your observed close rate and ticket, approximately <b>$206,000 "
 "in potential gross written business</b>. An estimate, not revenue we can claim would certainly have "
 "occurred.","small"))

# ================= PAGE 2
s.append(PageBreak())
s.append(P("2.  Why they do not sit","h1"))
s.append(P(
 "We audited all 79 of your appointments that matured still reading \u2018Set\u2019, record by record, looking for "
 "any sign a confirmation process touched them \u2014 a confirmer of record, a dial from our desk, a "
 "confirmations-board message or an AI touch. <b>Fifteen showed any evidence at all. Three reached a Reece "
 "confirmer.</b> That sent us back to the full cohort."))
s.append(chart("/home/claude/report/lf_ownership.png"))
s.append(Spacer(1,3))
s.append(table(
 ["","Lightfire book (446)","Reece book (678)","Verdict"],
 [[Paragraph("<b>No confirmer of record</b>",S["cellb"]),Paragraph("<b>171 \u2014 38.3%</b>",S["cellb"]),
   Paragraph("<b>73 \u2014 10.8%</b>",S["cellb"]),C(R,"p < 0.0001")],
  ["Confirmed by our desk","100 \u2014 22.4%","590 \u2014 87.0%",C(A,"our coverage gap")],
  ["Self-confirmed by your agents","168 \u2014 37.7%","6 \u2014 0.9%","structural difference"],
  [Paragraph("<b>Strand rate among those</b>",S["cellb"]),"76 of 171 \u2014 44.4%","25 of 73 \u2014 34.2%",
   C(G,"p = 0.14 \u2014 not distinguishable")]],
 [1.85*inch,1.6*inch,1.55*inch,1.5*inch],
 aligns=[(1,"CENTER"),(2,"CENTER"),(3,"CENTER")], hl=[1,4]))
s.append(Spacer(1,5))
s.append(P(
 "<b>Once confirmation status is held constant, we find no statistically distinguishable difference between the "
 "two teams in this cohort.</b> An appointment with no confirmer strands at 44.4% on your book and 34.2% on "
 "ours \u2014 a gap our data cannot separate from chance at this sample size. On the evidence here, <b>the "
 "strongest measurable driver of the difference between the two books is whether an appointment receives "
 "confirmation coverage at all.</b>"))
s.append(P(
 "And that coverage predicts almost everything downstream. Appointments carrying a confirmer of record issue at "
 "85\u201393% and sit at 55\u201373%. Appointments without one issue at 4\u201314% and, across both teams, "
 "<b>244 matured appointments with no confirmer of record produced zero sales between them.</b>"))

s.append(callout("Where Reece needs to act",
 "<b>Our desk confirms 22% of your book and 87% of our own.</b> <b>53 of the 79 stranded appointments sit on "
 "leads we supplied</b> \u2014 our leads, our system, nobody on our side called them. Eight got a desk dial that "
 "never became a confirmation. Lead Perfection has <b>no confirmation-owner field</b>, so neither side can prove "
 "an appointment was queued and skipped. And our own 10.8% never-confirmed rate is not clean either.", GREEN))
s.append(callout("Where Lightfire needs to act",
 "Your <b>Self Generated</b> leads \u2014 22 matured, 20 never confirmed, 12 stranded \u2014 never enter our "
 "confirmation process at all. Your agents who confirm their own book barely strand (Deer 7%); the agents nobody "
 "confirms strand at up to 71%. And the <b>21% cancellation rate</b> on your set appointments, against 9% on "
 "ours, is a separate qualification question this audit does not answer.", LF))
s.append(Spacer(1,3))
s.append(P(
 "We also tested the obvious alternative \u2014 that we hand you harder leads. It does not hold: the gap appears "
 "in <b>every shared lead source</b>, and standardising for your exact source mix explains none of it "
 "(z = 8.1, p &lt; 0.0001). We are happy to share that working.","small"))

# ================= PAGE 3
s.append(PageBreak())
s.append(P("3.  Where your agents rank against ours","h1"))
s.append(P(
 "Ranked by gross contract dollars from each setter\u2019s appointments, both teams on the same matured basis. "
 "Our own setters are named so you can see exactly what we are comparing you against."))
RANK=[(1,"Linan, Ashley","Reece",131,55.0,29,646119),(2,"Zeffield, Kevin","Reece",99,69.7,29,552260),
 (3,"Avril, Chantal","Reece \u2020",50,68.0,13,517644),(4,"Manieri, John","Reece (W)",83,69.9,29,512577),
 (5,"Nunes, Dylan","Reece",88,71.6,23,485960),(6,"Deer, Craig","Lightfire",152,39.5,20,465543),
 (7,"Jakob, Robert","Reece",44,70.5,15,352557),(8,"Giraldo, Miguel","Reece",43,46.5,12,338548),
 (9,"Elliott, Andre","Reece",32,78.1,11,286407),(10,"Toussaint, Marcorie","Reece",33,69.7,9,239506),
 (11,"Flanders, Jamal","Reece",27,77.8,8,208921),(12,"Demosthene, Jianna","Reece \u2020",19,68.4,6,176883),
 (13,"Walker, Shari","Lightfire",57,38.6,7,127953),(14,"Evans, Tresharna","Lightfire \u2021",23,34.8,4,117787),
 (15,"Wright, Carla","Lightfire",77,26.0,7,106712),(16,"Slowely, Diamoneke","Lightfire",56,25.0,3,86905),
 (17,"Nunes, Jonathan","Reece",10,70.0,2,36366),(18,"Gordon, Grecian","Lightfire \u2021",9,66.7,2,29613),
 (19,"Jacobson, David","Reece",3,33.3,1,23876),(20,"Julien, Lynslee","Reece",6,50.0,1,21500),
 (21,"Campbell, Brittany","Lightfire",8,37.5,1,19561),(22,"Bryce, Shaday","Lightfire",15,40.0,1,15500),
 (23,"Dennis, Jodian","Lightfire",12,50.0,1,6500),(24,"Martin, Nickalos","Lightfire",13,38.5,1,4198),
 (25,"Nievez Moreira, Jardel","Reece",10,50.0,0,0),(26,"Francis, Yanique","Lightfire",15,26.7,0,0),
 (27,"Green, Sherika","Lightfire",7,28.6,0,0)]
rows=[]
for r,nm,team,mat,sit,sold,gross in RANK:
    isLF=team.startswith("Lightfire")
    rows.append([str(r), Paragraph(f"<b>{nm}</b>",S["cellb"]) if r<=6 else nm,
                 Paragraph(f'<b><font color="{LFH}">{team}</font></b>',S["cell"]) if isLF else team,
                 str(mat), f"{sit:.0f}%", str(sold), f"${gross:,}", f"${round(gross/mat):,}"])
s.append(table(
 ["#","Setter","Team","Matured appts","Matured Sit %","Sold","Gross sold","Gross / appt"],
 rows,
 [0.28*inch,1.42*inch,0.75*inch,0.7*inch,0.72*inch,0.42*inch,0.85*inch,0.76*inch],
 aligns=[(0,"CENTER"),(3,"CENTER"),(4,"CENTER"),(5,"CENTER"),(6,"RIGHT"),(7,"RIGHT")],
 hl=[i+1 for i,r in enumerate(RANK) if r[2].startswith("Lightfire")]))
s.append(Spacer(1,4))
s.append(P(
 "<b>Matured Sit %</b> is of <i>all</i> matured appointments and is necessarily lower than the <b>Issued Sit %</b> "
 "on page 1, which excludes appointments that never issued. Craig Deer, for example, is 61.9% issued and 39.5% "
 "matured \u2014 both correct, measuring different things. \u2020 vacated their seat during this "
 "review. \u2021 did not appear on our account in the week of 9 August. Gross credits the full closed contract "
 "to the setter of record. Excluded: house and unassigned appointments, our AI setter, the GoHighLevel "
 "integration, and anyone below three matured appointments.","small"))
s.append(Spacer(1,3))
s.append(callout("The line worth sitting with",
 "<b>Craig Deer ranks sixth in dollars while setting the most appointments in the company.</b> He sets 16% more "
 "than our top setter and produces 28% fewer dollars. He is also 17.6 sits short of the 80% goal \u2014 more "
 "than any setter on either team, because he carries the most volume. <b>He is the single largest opportunity "
 "in this document.</b> Because he self-confirms most of his own book and has only a 7% strand rate, his gap "
 "appears to need a different diagnosis from the broader confirmation-coverage problem \u2014 which is exactly "
 "what we would like to work out with him directly.", LF))

# ================= PAGE 4
s.append(P("4.  Staffing and retention","h1"))
s.append(P(
 "<b>Twelve of your agents set appointments in the week of 2 August. Four appeared on our dialler in the week "
 "of 9 August</b> \u2014 Deer, Walker and Wright for full weeks, Slowely for one day. Evans and Gordon left the "
 "account entirely, having set 12 and 8 the week before. Output held only because the three staffed agents "
 "raised their own production 31%, which concentrates production in three people and creates clear continuity "
 "risk. Our Monday board shows it: your contribution fell from 40 appointments to 13."))
s.append(P(
 "Separately, several of your agents set appointments without ever logging into our dialler \u2014 consistent "
 "with working from your own system. We are not objecting, but we cannot see that activity, and it is the same "
 "population as the Self Generated leads above."))
s.append(Spacer(1,3))
s.append(table(
 ["Week of 2\u20138 August","Gross written","Cancellations","Financing denied","Net retained","Retention %"],
 [[Paragraph("<b>Lightfire</b>",S["cellb"]),"$331,042","$95,698","$34,826","$200,518",C(R,"60.6%")],
  [Paragraph("<b>Reece</b>",S["cellb"]),"$537,496","$49,093","$0","$488,403",C(N,"90.9%")]],
 [1.3*inch,1.0*inch,1.05*inch,1.1*inch,1.0*inch,0.95*inch],
 aligns=[(1,"RIGHT"),(2,"RIGHT"),(3,"RIGHT"),(4,"RIGHT"),(5,"CENTER")], hl=[1]))
s.append(Spacer(1,4))
s.append(P(
 "The cancellation figure is <b>one contract</b> \u2014 a single $95,698 cancellation on Craig Deer\u2019s "
 "largest write. Not a pattern, and we do not read it as one. The financing figure is not one contract: "
 "<b>$34,826 across three</b>, against $0 on our side that week.","small"))

s.append(P("5.  What we are asking for","h1"))
s.append(P(
 "Five immediate items tied to confirmation coverage and bench stability; two further review items that should "
 "not compete with them for attention.","small"))
s.append(P("Immediate corrective actions","h2"))
s.append(table(
 ["#","Request","Done means","By"],
 [["1","<b>A written confirmation ownership rule</b> \u2014 every appointment carries one named owning desk before its date",
   "Rule agreed and in force both sides","1 Sep"],
  ["2","<b>Reece commits coverage on Reece-supplied leads you set</b> \u2014 53 of the 79 stranded, ours to fix",
   "Coverage staffed, measured weekly","1 Sep"],
  ["3","<b>Lightfire commits coverage on Self Generated leads</b>, or they route to our desk",
   "Named owner on every one","1 Sep"],
  ["4","<b>Issued Sit % reported weekly by agent</b> \u2014 Deer, Walker and Wright first",
   "Lightfire book \u2265 75% by 1 Oct","25 Aug"],
  ["5","<b>Restore the bench</b> \u2014 named agents, expected days per week",
   "\u2265 8 agents producing in a week","1 Sep"]],
 [0.28*inch,3.5*inch,1.7*inch,0.6*inch], aligns=[(0,"CENTER"),(3,"CENTER")]))
s.append(P("Secondary review items","h2"))
s.append(table(
 ["#","Request","Done means","By"],
 [["6","<b>Agree reporting for agents dialling from your own system</b>","Method agreed and in use","15 Sep"],
  ["7","<b>Review the three financing-denied contracts together</b> \u2014 $34,826 against $0 on our side",
   "Reviewed; retention monthly","15 Sep"]],
 [0.28*inch,3.5*inch,1.7*inch,0.6*inch], aligns=[(0,"CENTER"),(3,"CENTER")]))
s.append(Spacer(1,5))
s.append(callout("Proposed next step",
 "A working session in the week of 25 August with your account lead and ours, plus Craig Deer if he is willing. "
 "<b>We will bring the record-level file for all 79 stranded appointments</b> \u2014 lead ID, setter, dates, "
 "source, branch and every confirmation touch we found \u2014 so any appointment can be examined line by line.", GREEN))

s.append(P("Method","h2"))
s.append(P(
 "<b>Cohort:</b> appointments set 6 July \u2013 15 August 2026 dated on or before 16 August, identical filter "
 "both teams, agents merged across both name forms. <b>Issued Sit %</b> = sits \u00f7 (gross issued \u2212 "
 "cancels), not also stripping NIS/NOC. <b>Matured Sit %</b> = sits \u00f7 all matured appointments. "
 "<b>Confirmed</b> = a confirmer of record in Lead Perfection; the stranded audit used a wider test including "
 "desk dials, board messages and AI touches. <b>Tests</b> two-proportion z, two-sided \u2014 a null result "
 "means the rates cannot be distinguished, not that they are equal. <b>Limits:</b> recent sales still pending; "
 "gross is written business; small denominators marked; retention is one week (Report 137). Underlying "
 "records available for any figure here.","small"))

doc.build(s)
print("built:", OUT)
