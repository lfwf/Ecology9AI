"""Allowlisted aggregate packets for AI. Raw records and free text stay local."""
COUNT_KEYS=set('requests archived open with_delivery with_order with_lead product_rows feedback2_rows feedback3_rows report_rows expanded_requests extra_report_rows clean_chains feedback_waiting_30days shipped_still_at_dispatch form_fields main_fields detail_tables flow_nodes routes operator_rules permission_entries active_layouts formulas field_attributes data_inputs sensitive_fields operatorless_node_visits operatorless_node_current_requests report_lists report_share_rules report_visible_fields report_sensitive_visible_fields browser_reference_fields browser_resolved_fields report_definitions report_definition_share_rules report_definition_visible_fields report_module_rows report_deleted_modules report_browser_entries'.split())
FINDING_KEYS=set('field_issues required_locked invisible_required missing_operator_groups unknown_operator_types unmatched_permission_fields route_issues layout_parse_failures report_fanout_cases delivery_discrepancies shared_orders feedback_backlog field_type_mismatch field_size_mismatch declared_type_unparsed custom_browser_definition_pending configured_column_not_found label_missing parent_unique_key_not_proven join_columns_not_found browser_definition_unresolved other_field_issues unresolved_browser_fields'.split())
COUNT_KEYS.update('linkages node_actions new_fields dynamic_supply_rules task_success_rows task_failure_rows'.split())
FINDING_KEYS.update('formula_reference_errors destructive_save_layouts branch_overlap_cases open_dynamic_source_empty public_view_lists invalid_enum_rows quantity_invalid_rows unmatched_feedback_rows duplicate_delivery_keys feedback_summary_discrepancies shipment_before_application'.split())
NODE_KEYS={'node_id','permissions','required_locked','missing_permissions','operator_rules'}
def count(v):
 if type(v) is not int or not 0<=v<=10000000:raise ValueError('Invalid aggregate count')
 return v
def mapping(value,allowed):
 if not isinstance(value,dict) or set(value)-allowed:raise ValueError('Unapproved aggregate field')
 for v in value.values():count(v)
def validate_packet(p):
 if not isinstance(p,dict) or set(p)!={'scope','counts','finding_counts','node_checks'}:raise ValueError('Unapproved packet shape')
 if p['scope'] not in {'sales_sample_review','cost_center_review'}:raise ValueError('Unapproved scope')
 mapping(p['counts'],COUNT_KEYS);mapping(p['finding_counts'],FINDING_KEYS)
 if not isinstance(p['node_checks'],list) or len(p['node_checks'])>100:raise ValueError('Invalid node aggregate')
 for row in p['node_checks']:
  if not isinstance(row,dict) or set(row)!=NODE_KEYS:raise ValueError('Unapproved node field')
  for v in row.values():count(v)
 return p
def business_counts(result):
 summary=result.get('summary',{})
 out={k:count(v) for k,v in summary.items() if k in COUNT_KEYS}
 return out
