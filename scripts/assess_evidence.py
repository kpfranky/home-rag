"""Choose direct evidence separately from context; preserve assessment provenance."""
import argparse
import json
from pathlib import Path
from answer_question import (api_request,evidence_catalog,load_sources,local_model,write_output)
from grounded_evidence import (selection_schema,selection_messages,validate_selection,table_answer)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('search_path',type=Path)
    p.add_argument('--embeddings',required=True,type=Path)
    p.add_argument('--embedding-report',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--model',required=True)
    p.add_argument('--api-url',default='http://127.0.0.1:11434')
    p.add_argument('--think',choices=('false','true','auto'),default='false')
    p.add_argument('--top-k',type=int,default=8)
    p.add_argument('--timeout',type=int,default=600)
    args=p.parse_args()
    if args.top_k<1 or args.timeout<1:p.error('Positive top-k and timeout required')
    if args.output.resolve() in {x.resolve() for x in (args.search_path,args.embeddings,args.embedding_report)}:
        p.error('Output must differ from inputs')
    query,sources,search_hash,report=load_sources(args.search_path,args.embeddings,args.embedding_report,args.top_k)
    output={'schema_name':'home-rag-answerability','schema_version':1,'assessor_version':'evidence-0.1.0',
            'assessment_mode':'evidence-selection','query':query,'sources':sources,
            'search_sha256':search_hash,'index_sha256':report['output_sha256'],'status':'running',
            'thinking_mode':args.think,'validation_scope':'IDs and exact quotes; relevance is model judged'}
    write_output(args.output,output)
    try:
        table=table_answer(query,sources)
        if table:
            ids={e['source_id'] for c in table['claims'] for e in c['evidence']}
            output['structured_table']=table
            output['decision']={'sufficient':True,'source_ids':[s['source_id'] for s in sources if s['source_id'] in ids],
                                'reason':'Rozpoznano wskazany wiersz oraz żądane kolumny tabeli.'}
        else:
            catalog=[e for s in sources for e in evidence_catalog(s)]
            if not catalog:
                selection={'direct_ids':[],'context_ids':[]}
            else:
                messages=selection_messages(query,sources,catalog)
                name,digest=local_model(args.api_url,args.model,args.timeout)
                options={'temperature':0,'seed':0,'num_ctx':8192,'num_predict':768}
                output.update(messages=messages,options=options,model=name,model_digest=digest)
                write_output(args.output,output)
                request={'model':name,'messages':messages,'format':selection_schema(catalog),
                         'stream':False,'options':options,'keep_alive':'5m'}
                if args.think!='auto':request['think']=args.think=='true'
                response=api_request(args.api_url,'/api/chat',request,timeout=args.timeout)
                output['raw_response']=response;write_output(args.output,output)
                if response.get('done') is not True or response.get('done_reason')=='length':
                    raise ValueError('Incomplete selection response')
                selection=validate_selection(json.loads(response['message']['content']),catalog)
                if local_model(args.api_url,name,args.timeout)[1]!=digest:
                    raise ValueError('Model changed during selection')
            output['evidence_selection']=selection
            lookup={e['evidence_id']:e for e in catalog}
            ids={lookup[eid]['source_id'] for eid in selection['direct_ids']}
            output['decision']={'sufficient':bool(ids),'source_ids':[s['source_id'] for s in sources if s['source_id'] in ids],
                                'reason':'Wybrano bezpośrednie dowody.' if ids else 'Brak bezpośrednich dowodów; kontekst nie wystarcza.'}
        output['status']='assessed';write_output(args.output,output)
    except (ValueError,KeyError,TypeError,RuntimeError) as error:
        output.update(status='assessment_failed',error=str(error));write_output(args.output,output)
        raise SystemExit(str(error))
    print(json.dumps(output['decision'],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
