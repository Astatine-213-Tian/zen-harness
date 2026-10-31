"""Marker on the controlled tab's title, so the user can see which tab the agent holds.

Pages that set their own title (single-page apps like Notion do on every route) would drop a
prefix set once, so a MutationObserver on <head> puts it back.
"""
import json


def mark_js(marker):
    m = json.dumps(marker + " ")
    return ("{window.__zhMarker=%s;"
            "const fix=()=>{const m=window.__zhMarker;if(m&&!document.title.startsWith(m))document.title=m+document.title;};"
            "fix();"
            "if(!window.__zhMarkObs){window.__zhMarkObs=new MutationObserver(fix);"
            "window.__zhMarkObs.observe(document.head||document.documentElement,"
            "{subtree:true,childList:true,characterData:true});}}" % m)


def unmark_js(marker):
    m = json.dumps(marker + " ")
    return ("{window.__zhMarker=null;if(window.__zhMarkObs){window.__zhMarkObs.disconnect();window.__zhMarkObs=null;}"
            "if(document.title.startsWith(%s))document.title=document.title.slice(%s.length);}" % (m, m))
