"""B09 structural metadata, logical candidates and source-specific state notes."""
import json,re
from pathlib import Path
from collections import defaultdict,Counter
from interface_sources import sanitize
from sql_refs import table_references
METHOD=json.loads((Path(__file__).resolve().parents[1]/'registry/B09.json').read_text('utf-8'))
def yes(v):return v is True or v==1
def no(v):return v is False or v==0
def normalize(tables,seed):
    issues=[];actual={};object_rows=tables.get('objects',[])
    def issue(kind,**refs):issues.append(dict(kind=kind,**refs))
    for o in object_rows:
        key=(o['schema_name'],o['object_name'])
        if key in actual:raise ValueError('Duplicate runtime object address')
        actual[key]=dict(o)
    grouped=defaultdict(list)
    for c in tables.get('columns',[]):grouped[(c['schema_name'],c['object_name'])].append(c)
    indexgroups=defaultdict(list)
    for c in tables.get('indexes',[]):indexgroups[(c['schema_name'],c['object_name'],c['index_id'])].append(c)
    indexes=[]
    for (schema,name,idx),parts in sorted(indexgroups.items()):
        keyparts=sorted([p for p in parts if p['key_ordinal']>0 and no(p['is_included_column'])],key=lambda x:x['key_ordinal'])
        columns=[p['column_name'] for p in keyparts];first=parts[0]
        proven=bool(columns) and len(columns)==len(set(columns)) and yes(first['is_unique']) and no(first['is_disabled']) and no(first['is_hypothetical']) and no(first['has_filter'])
        indexes.append(dict(schema_name=schema,object_name=name,index_id=idx,index_name=first['index_name'],key_columns=columns,
                            included_columns=[p['column_name'] for p in parts if yes(p['is_included_column'])],unfiltered_unique_proven=proven,configuration=parts))
    fkgroups=defaultdict(list)
    for row in tables.get('foreign_keys',[]):fkgroups[(row['schema_name'],row['object_name'],row['foreign_key_name'])].append(row)
    foreign=[]
    for (schema,name,key),parts in sorted(fkgroups.items()):
        parts=sorted(parts,key=lambda p:p['constraint_column_id']);first=parts[0]
        foreign.append(dict(schema_name=schema,object_name=name,name=key,source_columns=[p['column_name'] for p in parts],
                            referenced_schema=first['referenced_schema'],referenced_object=first['referenced_object'],referenced_columns=[p['referenced_column'] for p in parts],
                            enabled_and_trusted=no(first['is_disabled']) and no(first['is_not_trusted']),configuration=parts))
    definitions={(x['schema_name'],x['object_name']):x for x in tables.get('view_definitions',[])}
    refs=tables.get('local_reference_files',[])
    def localrefs(obj,col=None):
        result=[]
        for f in refs:
            if not f.get('available'):continue
            for topic in f.get('topics',[]):
                if topic.get('object_name')!=obj or col is not None and col not in topic.get('columns',[]):continue
                result.append(dict(reference_key=f['reference_key'],path=f['path'],sha256=f['sha256'],note=topic.get('note'),snippets=f.get('snippets',[]),evidence_state='local_reference_only_not_loaded'))
        return result
    objects=[];viewcandidates=[]
    for target in METHOD['targets']:
        keys=[key for key in actual if key[1].casefold()==target['name'].casefold()]
        if not keys:
            issue('object_not_visible',object_name=target['name'])
            objects.append(dict(schema_name=None,object_name=target['name'],requested_name=target['name'],purpose=target['purpose'],grain_note=target['grain_note'],
                                visibility_state='not_visible',columns=[],indexes=[],unique_keys=[],definition_state='not_applicable',definition=None,grain_verified=False,local_references=[]))
        for key in keys:
            raw=actual[key];cols=sorted(grouped[key],key=lambda x:x['column_id']);ix=[x for x in indexes if (x['schema_name'],x['object_name'])==key]
            state='not_applicable';definition=None
            if raw['type_desc']=='VIEW':
                definition=definitions.get(key,{}).get('definition')
                if definition is None:state='not_visible' if no(raw.get('can_view_definition')) else 'unavailable_with_permission'
                elif not str(definition).strip():state='empty_definition'
                else:state='available'
                if state!='available':issue('view_definition_unavailable',schema_name=key[0],object_name=key[1],definition_state=state)
                else:
                    parsed=table_references(definition)
                    viewcandidates.extend(dict(x,view_schema=key[0],view_name=key[1],executed=False) for x in parsed['candidates'])
            props=[p for p in tables.get('extended_properties',[]) if (p['schema_name'],p['object_name'])==key]
            objects.append(dict(raw,requested_name=target['name'],purpose=target['purpose'],grain_note=target['grain_note'],visibility_state='visible',columns=cols,indexes=ix,
                                unique_keys=[x for x in ix if x['unfiltered_unique_proven']],definition_state=state,definition=definition,grain_verified=False,
                                extended_properties=props,local_references=localrefs(key[1]),runtime_verified=False))
    def candidates(name):return [o for o in objects if o['visibility_state']=='visible' and o['requested_name']==name]
    def column(obj,name):
        exact=[c for c in obj['columns'] if c['column_name']==name]
        matches=exact or [c for c in obj['columns'] if c['column_name'].casefold()==name.casefold()]
        return matches[0] if len(matches)==1 else None
    relationships=[]
    for recipe in METHOD['relationships']:
        a=candidates(recipe['source_object']);z=candidates(recipe['target_object']);r=dict(recipe,state='structure_candidate',source_candidates=[dict(schema_name=o['schema_name'],object_name=o['object_name']) for o in a],
            target_candidates=[dict(schema_name=o['schema_name'],object_name=o['object_name']) for o in z],parent_unique_key_proven=False,foreign_key_enforced=False,business_cardinality_verified=False,runtime_verified=False)
        if not a or not z:r['state']='object_not_visible'
        elif len(a)!=1 or len(z)!=1:r['state']='schema_ambiguous'
        else:
            src=a[0];dst=z[0];acs=[column(src,n) for n in r['source_columns']];zcs=[column(dst,n) for n in r['target_columns']]
            if any(c is None for c in acs+zcs):r['state']='column_not_visible_or_ambiguous'
            elif any(x['data_type']!=y['data_type'] for x,y in zip(acs,zcs)):r['state']='column_type_mismatch'
            else:
                targetnames=[c['column_name'] for c in zcs];srcnames=[c['column_name'] for c in acs]
                r['parent_unique_key_proven']=any(len(k['key_columns'])==len(targetnames) and set(k['key_columns'])==set(targetnames) for k in dst['unique_keys'])
                r['foreign_key_enforced']=any(f['schema_name']==src['schema_name'] and f['object_name']==src['object_name'] and f['referenced_schema']==dst['schema_name'] and f['referenced_object']==dst['object_name'] and
                    len(f['source_columns'])==len(srcnames) and set(zip(f['source_columns'],f['referenced_columns']))==set(zip(srcnames,targetnames)) and f['enabled_and_trusted'] for f in foreign)
            if recipe.get('requires_view_definition') and src['definition_state']!='available':r['state']='view_definition_required'
        if r['state']!='structure_candidate':issue('logical_relation_pending',source_object=r['source_object'],target_object=r['target_object'],state=r['state'])
        relationships.append(r)
    statefields=[];timefields=[]
    for obj in objects:
        if obj['visibility_state']!='visible':continue
        for name in METHOD['status_fields'].get(obj['requested_name'],[]):
            c=column(obj,name)
            if c:statefields.append(dict(schema_name=obj['schema_name'],object_name=obj['object_name'],column_name=c['column_name'],data_type=c['data_type'],
                                        local_references=localrefs(obj['object_name'],c['column_name']),confirmed_code_dictionary=None,complete_enumeration=False,business_values_observed=False))
        for c in obj['columns']:
            name=c['column_name'];dtype=c['data_type'].lower()
            if dtype in ['date','time','datetime','datetime2','smalldatetime','datetimeoffset'] or re.search(r'(?i)(?:date|time|hours)$',name):
                storage='string_without_verified_format_or_timezone' if dtype in ['char','varchar','nchar','nvarchar','text','ntext'] else 'native_sql_temporal_type' if dtype in ['date','time','datetime','datetime2','smalldatetime','datetimeoffset'] else 'numeric_or_other_unit_unverified'
                timefields.append(dict(schema_name=obj['schema_name'],object_name=obj['object_name'],column_name=name,data_type=dtype,storage_class=storage,timezone_verified=False,unit_verified=False))
    unassociated=[]
    known=set(actual)
    for source,rows in tables.items():
        if source in ['objects','local_reference_files']:continue
        for i,row in enumerate(rows):
            if (row.get('schema_name'),row.get('object_name')) not in known:unassociated.append(dict(source=source,source_record_index=i,metadata=row))
    coverage={name:dict(raw_records=len(rows),represented_records=len(rows),role='local_source_reference' if name=='local_reference_files' else 'sys_metadata') for name,rows in tables.items()}
    return sanitize(dict(category='B09',normalization_version='1.0.0',semantic_state='partial_pending_confirmation',runtime_verified=False,business_rows_read=0,
        objects=objects,indexes=indexes,foreign_keys=foreign,relationships=relationships,state_fields=statefields,time_fields=timefields,
        local_reference_files=refs,view_source_candidates=viewcandidates,metadata_catalogs={k:v for k,v in tables.items() if k!='local_reference_files'},
        source_coverage=coverage,unassociated_metadata=unassociated,node_rounds_reconstructible=False,node_round_key=None,issues=issues,
        summary=dict(requested_object_count=len(METHOD['targets']),visible_object_count=len(actual),column_count=len(tables.get('columns',[])),index_count=len(indexes),index_component_count=len(tables.get('indexes',[])),
                     foreign_key_count=len(foreign),view_count=sum(o.get('type_desc')=='VIEW' for o in objects),visible_view_definition_count=sum(o['definition_state']=='available' for o in objects),
                     relationship_count=len(relationships),state_field_count=len(statefields),time_field_count=len(timefields),local_reference_count=len(refs),issue_counts=dict(Counter(x['kind'] for x in issues))),
        limitations=['只读sys元数据及指定本机源码参考；没有查询单据、待办、事件、视图或日志记录，未读日志文件。','逻辑连接、列名、identity及复合索引片段不能替代完整主键/外键证明；未验证真实重复或孤立行。',
                     '请求、办理项、事件和节点进入轮次分开，当前不能可靠恢复轮次；未把requestid+nodeid当唯一轮次。','状态条件仅在各自来源范围成立，本机页面筛选不是完整枚举，未知码未通过业务DISTINCT补样。',
                     'V_JDSX定义不可见时过滤、聚合、去重、rn稳定性及历史覆盖未知；不会执行视图反推定义。','字符串日期/时间没有自动变为UTC，时区和时长单位待校准；当前节点定义不直接解释历史。']))
