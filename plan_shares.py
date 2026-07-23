#!/usr/bin/env python3
"""
plan_shares.py — parse SapientAI economic-plan inline scripts, resolve every
subplan's ai_weight for a given scenario, and print each resource's normalized
share of the plan's build-priority pool.

Model & caveats:
  * One-pool normalization: share = resource_weight / sum(all_weights).
    The exact in-engine normalization is a black box; ratios are the robust part.
  * A subplan contributes only if its `potential` holds in the scenario.
  * Scaling subplans are treated as ON unless the scenario says `mature=True`
    (which trips the *_over_cap stop-gates).
  * Unknown leaf triggers default to True (and are listed under --debug), so a
    subplan is never silently dropped for a trigger we didn't model.

Usage:  python3 plan_shares.py [PLAN_DIR]
Edit SCENARIOS at the bottom to taste.
"""
import re, sys, glob, os

PLAN_DIR = sys.argv[1] if len(sys.argv) > 1 else \
    "common/inline_scripts/sapient/plan"

RESOURCES = ["minerals","energy","food","alloys","consumer_goods","unity",
             "physics_research","society_research","engineering_research",
             "trade","volatile_motes","rare_crystals","exotic_gases",
             "naval_cap","pops"]

# ---------- tiny Paradox-script block parser -------------------------------
def strip_comments(s):
    return "\n".join(line.split("#",1)[0] for line in s.splitlines())

def parse_block(s, i=0):
    """Parse { ... } into a list of (key, value) where value is str or list."""
    out=[]
    while i < len(s):
        m=re.match(r'\s*}', s[i:])
        if m: return out, i+m.end()
        m=re.match(r'\s*([A-Za-z_@][\w@]*)\s*(=|<=|>=|<|>)\s*', s[i:])
        if not m:
            m2=re.match(r'\s+', s[i:])
            if m2: i+=m2.end(); continue
            if i>=len(s): break
            i+=1; continue
        key=m.group(1); op=m.group(2); i+=m.end()
        if s[i]=='{':
            child,i=parse_block(s,i+1)
            out.append((key,op,child))
        else:
            vm=re.match(r'([^\s{}]+)', s[i:])
            val=vm.group(1); i+=vm.end()
            out.append((key,op,val))
    return out,i

def top_subplans(s):
    """Yield parsed subplan blocks."""
    subs=[]
    i=0
    while True:
        m=re.search(r'subplan\s*=\s*{', s[i:])
        if not m: break
        start=i+m.end()
        block,end=parse_block(s,start)
        subs.append(block)
        i=end
    return subs

# ---------- scenario -> fact evaluation ------------------------------------
THREAT_RANK={"peace":0,"wary":1,"alarmed":2,"mobilizing":3,"war":4}

def leaf_true(key,op,val,sc,unknown):
    t=sc["threat"]; tr=THREAT_RANK[t]
    if key=="sapient_threat_wary":       return tr>=1
    if key=="sapient_threat_alarmed":    return tr>=2
    if key=="sapient_threat_mobilizing": return tr>=3
    if key=="is_at_war":                 return (tr>=4)==(val=="yes")
    if key=="sapient_is_crisis":         return (sc["empire"]=="crisis")==(val=="yes")
    if key=="sapient_is_bioship_empire": return (sc["empire"]=="bioship")==(val=="yes")
    if key=="country_uses_bio_ships":    return (sc["empire"]=="bioship")==(val=="yes")
    if key=="sapient_research_arc":      return (sc["arc"]=="research")==(val=="yes")
    if key=="sapient_unity_arc":         return (sc["arc"]=="unity")==(val=="yes")
    if key=="sapient_research_split":    return sc["split"]==(val=="yes")
    if key=="country_uses_food":         return (sc["empire"]!="machine")==(val=="yes")
    if key=="sapient_scales_alloys_normal":  return sc["empire"] not in ("bioship","crisis")
    if key=="sapient_scales_alloys_bioship": return sc["empire"]=="bioship"
    if key.endswith("_over_cap") or key.endswith("_over_cap_bioship"):
        return sc["mature"]            # true only when mature -> stops scaling
    if key=="num_ascension_perks":       return sc["perks_below_cap"]
    if key=="is_homicidal":              return sc["homicidal"]==(val=="yes") if val else sc["homicidal"]
    if key=="used_naval_capacity_percent":
        f=sc["fleet_fill"]; thr=float(val)
        return f>thr if op==">" else f>=thr if op==">=" else f<thr if op=="<" else f<=thr
    if key in ("is_gestalt","is_megacorp"): return False
    if key=="has_technology":            return True
    if key=="uses_fauna_ship_sizes":     return sc["empire"]=="crisis"
    if key=="has_ascension_perk":        return sc["empire"]=="crisis"
    if key=="has_monthly_income":        return None  # handled by caller (deficit)
    if key=="has_resource":              return True
    if key=="is_nomadic":                return val=="no"   # scenarios are non-nomadic
    if key=="can_build_unity_megastructures": return True
    unknown.add(key)
    return True

def eval_conds(conds,sc,unknown):
    """conds: list of (key,op,val). Implicit AND. Handles OR/NOT/has_monthly_income."""
    for key,op,val in conds:
        if key=="OR":
            if not any(eval_conds([c],sc,unknown) for c in val): return False
        elif key=="NOT":
            if eval_conds(val,sc,unknown): return False
        elif key=="AND":
            if not eval_conds(val,sc,unknown): return False
        elif key=="has_monthly_income":
            res=next((v for k,o,v in val if k=="resource"),None)
            vop =next((o for k,o,v in val if k=="value"),None)
            vnum=next((v for k,o,v in val if k=="value"),None)
            if vop=="<" and vnum=="0":                 # deficit test
                if res not in sc["deficits"]: return False
            else:                                      # value >= target : "is it met?"
                if (res in sc["deficits"]) or (res in sc["short"]): return False
        elif key=="any_situation" or key=="any_owned_planet" or key=="any_country" \
             or key=="any_neighbor_country" or key=="check_modifier_value":
            continue  # not modeled; treat as pass-through
        elif isinstance(val,list):
            if not eval_conds(val,sc,unknown): return False
        else:
            r=leaf_true(key,op,val,sc,unknown)
            if r is False: return False
    return True

def resolve_weight(aiw,sc,unknown):
    base=0.0; add=0.0; fac=1.0
    for key,op,val in aiw:
        if key=="weight": base=float(val)
        elif key=="modifier":
            addv=next((v for k,o,v in val if k=="add"),None)
            facv=next((v for k,o,v in val if k=="factor"),None)
            conds=[(k,o,v) for k,o,v in val if k not in ("add","factor","mult")]
            if eval_conds(conds,sc,unknown):
                if addv is not None: add+=float(addv)
                if facv is not None: fac*=float(facv)
    return (base+add)*fac

RES_DISC={"physics_research","society_research","engineering_research"}
def subplan_category(block):
    """One subplan = one lane. Research disciplines collapse to a single 'research'
    category (one lab serves all three), so a subplan is never double-counted."""
    keys=[]
    for key,op,val in block:
        if key=="income" and isinstance(val,list):
            keys+=[k for k,o,v in val]
        elif key in ("naval_cap","pops"):
            keys.append(key)
    if any(k in RES_DISC for k in keys): return "research"
    return keys[0] if keys else None

def get(block,name):
    for k,o,v in block:
        if k==name: return v
    return None

# ---------- run ------------------------------------------------------------
def compute(sc):
    files=glob.glob(os.path.join(PLAN_DIR,"*.txt"))
    weights={}; unknown=set(); noweight=set()
    for f in files:
        s=strip_comments(open(f,encoding="utf-8").read())
        for block in top_subplans(s):
            pot=get(block,"potential")
            if isinstance(pot,list) and not eval_conds(pot,sc,unknown): continue
            cat=subplan_category(block)
            aiw=get(block,"ai_weight")
            if not isinstance(aiw,list):
                if cat: noweight.add(cat)          # e.g. pops: no ai_weight defined
                continue
            w=resolve_weight(aiw,sc,unknown)
            if cat: weights[cat]=weights.get(cat,0.0)+w
    return weights,unknown,noweight

def show(name,sc,include_naval=True):
    w,unknown,noweight=compute(sc)
    if not include_naval:
        w.pop("naval_cap",None); w.pop("pops",None)
    tot=sum(w.values()) or 1
    print(f"\n### {name}")
    for r in sorted(w,key=lambda k:-w[k]):
        print(f"    {r:16} {w[r]:7.0f}   {100*w[r]/tot:5.1f}%")
    if noweight: print(f"    [NO ai_weight on: {sorted(noweight)}  -> weightless, pool role undefined]")

def sc(empire="normal",threat="peace",arc="unity",split=False,mature=False,
       perks_below_cap=True,deficits=(),short=(),homicidal=False,fleet_fill=0.5):
    return dict(empire=empire,threat=threat,arc=arc,split=split,mature=mature,
                perks_below_cap=perks_below_cap,deficits=set(deficits),short=set(short),
                homicidal=homicidal,fleet_fill=fleet_fill)

if __name__=="__main__":
    show("normal | peace | fleet 50% | pre-AP4",           sc(fleet_fill=0.5))
    show("normal | AT WAR | fleet 90% | pre-AP4",          sc(threat="war",fleet_fill=0.9))
    show("HOMICIDAL | mobilizing | fleet 90% | pre-AP4",   sc(threat="mobilizing",homicidal=True,fleet_fill=0.9))
    show("normal | AT WAR | fleet 90% | post-AP4",         sc(threat="war",arc="research",fleet_fill=0.9))
    show("bioship | AT WAR | fleet 90% | pre-AP4",         sc(empire="bioship",threat="war",fleet_fill=0.9))
    show("normal | peace | ENERGY DEFICIT",                sc(deficits=["energy"]))