"""Small deterministic checks; source strings are inert and remain local."""
import re
def formula_assignment(expression):
    m=re.match(r'\s*\[(main|detail_\d+)\.(-?\d+)\]\s*=(?!=)',expression or '')
    return (m[1],int(m[2])) if m else None
def formula_references(expression):
    return [(m[1],int(m[2])) for m in re.finditer(r'\[(main|detail_\d+)\.(-?\d+)\]',expression or '')]
def rebuild_on_save(script):
    # A source clue, never proof of an executed deletion. Require event and call site.
    text=re.sub(r'/\*.*?\*/|//[^\n]*','',script or '',flags=re.S)
    event=re.search(r'registerCheckEvent\s*\([^;]*OPER_SAVE[^;]*function\s*\([^)]*\)\s*\{',text)
    if not event:return False
    tail=text[event.end():]
    end=tail.find('function addrow')
    body=tail if end<0 else tail[:end]
    helper=tail[end:] if end>=0 else ''
    return bool(re.search(r'delDetailRow\s*\(',body) and re.search(r'addrow\s*\(',body) and re.search(r'addDetailRow\s*\(',helper))
def candidate_exits(routes, value, option_field_id):
    """Static enumeration only: null/unknown is retained, not SQL-evaluated."""
    hits=[];unknown=[]
    for route in routes:
        rules=route.get('rules',[])
        if not rules:
            if route.get('condition_state')=='no_condition_definition_observed':hits.append(route['id'])
            else:unknown.append(route['id'])
            continue
        if len(rules)!=1 or len(rules[0].get('terms',[]))!=1:unknown.append(route['id']);continue
        term=rules[0]['terms'][0];ref=term.get('field_reference') or {};c=term['configuration']
        if ref.get('field_id')!=option_field_id or value is None or c.get('compareoption1') not in [7,8]:unknown.append(route['id']);continue
        options=str(c.get('elementvalue1','')).split(',')
        yes=str(value) in options
        if yes if c['compareoption1']==7 else not yes:hits.append(route['id'])
    return dict(candidate_routes=hits,unresolved_routes=unknown)
