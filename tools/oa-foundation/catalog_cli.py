"""Commands for additional registered configuration categories."""
import hashlib,json,re,shutil,subprocess,uuid,sys
from pathlib import Path
import foundation as f
import catalog_store as store

def refresh(args):
    m=store.method(args.category);base=store.category_dir(args.data_root,args.environment,args.category)
    attempt=base/'attempts'/uuid.uuid4().hex;attempt.mkdir(parents=True)
    record=dict(category=args.category,status='failed',started_at=f.stamp(),business_rows_read=0)
    stage='dependency'
    try:
        dependency=f.selected_batch(args.data_root,args.environment,unreviewed=True)
        seed=f.read_json(dependency/'normalized.json')
        raw_path=dependency/'raw.json'
        seed_hash=hashlib.sha256(raw_path.read_bytes()).hexdigest()
        stage='connection_files';connection=Path(args.connection_directory).resolve()
        if not all((connection/name).is_file() for name in ['connection.json','credential.clixml']):raise ValueError('Missing connection')
        stage='reader';shell=shutil.which(args.powershell)
        if not shell:raise ValueError('Missing PowerShell')
        command=[shell,'-NoLogo','-NoProfile','-NonInteractive','-File',str(f.HOME/m['reader']),
            '-ConnectionDirectory',str(connection),'-DependencyPath',str(raw_path),'-OutputPath',str(attempt/'raw.json')]
        if m['reader']=='readers/Read-RegisteredConfig.ps1':command+=['-Category',args.category]
        if m['reader']=='readers/Read-B06.ps1':command+=['-PythonExecutable',sys.executable]
        dependency_raw_paths={'B01':raw_path}
        dependency_records={'B01':dict(batch_id=dependency.name,raw_sha256=seed_hash,review_state='not_assumed_accepted')}
        for other in m.get('dependencies',[]):
            if other=='B01':continue
            other_path=store.selected_batch(args.data_root,args.environment,other,unreviewed=True)
            other_manifest=f.read_json(other_path/'manifest.json')
            if other_manifest['compatibility']['source']!=f.digest(f.read_json(raw_path)['source_identity']):raise ValueError('Cross-category source mismatch')
            expected=f.digest([(w['id'],w['form_id'],w['isbill_raw']) for w in seed['workflows']])
            if other_manifest['compatibility']['dependency_scope']!=expected:raise ValueError('Cross-category workflow scope mismatch')
            dependency_raw_paths[other]=other_path/'raw.json'
            seed[other]=dict(category=other,model_input='raw_dependency_anchors') if other in m.get('raw_dependencies',[]) else f.read_json(other_path/'normalized.json')
            dependency_records[other]=dict(batch_id=other_path.name,raw_sha256=hashlib.sha256((other_path/'raw.json').read_bytes()).hexdigest(),review_state='not_assumed_accepted')
        if args.category in ['B07','B08']:command+=['-RelationDependencyPath',str(dependency_raw_paths['B06'])]
        if args.category=='B08':command+=['-ReportDependencyPath',str(dependency_raw_paths['B07'])]
        result=subprocess.run(command,capture_output=True,encoding='utf-8',errors='replace',timeout=m['limits']['process_timeout_seconds'],check=False)
        if result.returncode:
            try:
                stage_name=json.loads(result.stdout.strip()).get('stage','reader')
                if re.fullmatch(r'[a-z_]{1,40}',stage_name):stage='reader_'+stage_name
                payload=json.loads(result.stdout.strip())
                if payload.get('source') in m['sources']:record['failure_source']=payload['source']
                if payload.get('failure_code') in ['source_content_changed','schema_changed','dependency_changed','reader_error']:record['failure_code']=payload['failure_code']
            except (ValueError,AttributeError,TypeError):pass
            raise ValueError('Reader failed')
        stage='validation_and_publish';raw=f.read_json(attempt/'raw.json')
        if raw.get('category')!=args.category:raise ValueError('Reader category mismatch')
        if raw.get('dependency_sha256','').lower()!=seed_hash:raise ValueError('Dependency evidence mismatch')
        if f.digest(raw['source_identity'])!=f.digest(f.read_json(raw_path)['source_identity']):raise ValueError('Dependency source mismatch')
        stage='dependency_scope_validation'
        for dependency_category,source_names in m.get('scope_anchors',{}).items():
            dependency_raw=f.read_json(dependency_raw_paths[dependency_category])
            source_pairs=source_names.items() if isinstance(source_names,dict) else [(n,n) for n in source_names]
            for source_name,dependency_source in source_pairs:
                if f.digest(raw['tables'][source_name])!=f.digest(dependency_raw['tables'][dependency_source]):
                    record['failure_source']=source_name
                    raise ValueError('Dependent configuration scope changed; refresh dependency')
        if args.category in ['B07','B08'] and raw.get('relation_dependency_sha256','').lower()!=dependency_records['B06']['raw_sha256']:raise ValueError('Relation dependency evidence mismatch')
        if args.category=='B08':
            if raw.get('report_dependency_sha256','').lower()!=dependency_records['B07']['raw_sha256']:raise ValueError('Report dependency evidence mismatch')
            stage='source_code_capture'
            from source_evidence import capture_sources
            from interface_sources import registration_rows
            rows=registration_rows(raw['tables'])
            source_input=attempt/'source-input.json';f.write_json(source_input,dict(business_rows_read=0,tables=dict(actionsetting=rows)))
            profile=Path(getattr(args,'source_profile',None) or connection/'source-profile.json')
            captured=capture_sources(source_input,profile,attempt/'source-evidence.json')
            if captured['status']!='captured':raise ValueError('Local source evidence incomplete')
            files=captured['evidence']['files']
            raw['source_evidence']={k:v for k,v in captured.items() if k!='evidence'}
            raw['source_evidence']['graph']={k:v for k,v in captured['evidence'].items() if k!='files'}
            raw['source_evidence']['registration_rows_sha256']=f.digest(rows)
            raw['source_evidence']['database_capture_raw_sha256']=hashlib.sha256((attempt/'raw.json').read_bytes()).hexdigest()
            raw['tables']['local_source_files']=files
            raw['checks']['local_source_files']=dict(complete=True,row_count=len(files),hash_first=f.digest(files),hash_second=f.digest(files),pages=[])
            raw['database_capture']=dict(started_at=raw['started_at'],ended_at=raw['ended_at'])
            raw['ended_at']=captured['ended_at']
        if m.get('requires_runtime_references'):
            stage='local_reference_capture'
            from runtime_references import capture_references
            profile=Path(getattr(args,'reference_profile',None) or connection/'runtime-reference-profile.json')
            captured=capture_references(profile,attempt/'reference-evidence.json')
            if captured['status']!='captured':raise ValueError('Reference capture changed during read')
            files=captured['files']
            raw['reference_evidence']={k:v for k,v in captured.items() if k!='files'}
            raw['reference_evidence']['database_capture_raw_sha256']=hashlib.sha256((attempt/'raw.json').read_bytes()).hexdigest()
            raw['tables']['local_reference_files']=files
            raw['checks']['local_reference_files']=dict(complete=True,row_count=len(files),hash_first=f.digest(files),hash_second=f.digest(files),pages=[])
            raw['database_capture']=dict(started_at=raw['started_at'],ended_at=raw['ended_at'])
            raw['ended_at']=captured['ended_at']
        if args.category in ['B06','B07','B08']:seed['_source_database']=raw['source_identity']['database']
        stage='normalization_and_publish'
        batch=store.publish(args.data_root,args.environment,raw,seed,dependency_records)
        record.update(status='success',batch_id=batch.name,report=str(batch/m['report_file']) if m.get('report_file') else str(next(batch.glob('*.html'))))
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired):
        record.update(failure_stage=stage,action='Inspect registered source/schema/dependency; previous success preserved')
    record['ended_at']=f.stamp();f.write_json(attempt/'result.json',record)
    return record

def handle(args):
    m=store.method(args.category)
    if args.command=='method':return store.method(args.category)
    if args.command=='status':return store.status(args.data_root,args.environment,args.category)
    if args.command=='refresh':return refresh(args)
    if args.command=='review':
        store.review(args.data_root,args.environment,args.category,args.batch,args.reviewer,args.decision,args.note,args.semantic_state)
        return store.status(args.data_root,args.environment,args.category)
    batch=store.selected_batch(args.data_root,args.environment,args.category,args.unreviewed)
    state=store.status(args.data_root,args.environment,args.category)
    return dict(category=args.category,batch_id=batch.name,report=str(batch/m['report_file']) if m.get('report_file') else str(next(batch.glob('*.html'))),
                normalized=str(batch/'normalized.json'),selection='unreviewed_latest' if args.unreviewed else 'accepted',
                **state,has_unreviewed_update=state['latest_success']!=state['latest_reviewed'])
