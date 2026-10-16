"""Synthetic interface fixture, explicitly not a model or retrieval benchmark."""
import argparse
import json
from pathlib import Path


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('question');p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args();out=args.output_dir;out.mkdir(parents=True,exist_ok=False)
    q=args.question.casefold()
    source={'source_id':'S1','chunk_id':'demo:archive:p1',
            'chunk':{'source_id':'Archiwum domowe — dokument syntetyczny',
                     'page_numbers':[1],'printed_page_labels':[],
                     'section_path':['Przygotowanie dokumentów'],'text':
                     'Przygotowanie dokumentów obejmuje trzy kroki: skanowanie, rozpoznawanie tekstu i sprawdzenie jakości.'}}
    if 'tabel' in q and 'jakości' in q:
        source['chunk'].update(page_numbers=[2],section_path=['Kontrola jakości'],
          text='Tabela kontrolna: poprawne strony — 80% (8); strony do ponownego skanowania — 20% (2); brakujące strony — 0% (0).')
        source['chunk_id']='demo:archive:p2'
        text=source['chunk']['text']
    elif 'kroki' in q and ('dokument' in q or 'przygotowan' in q):text=source['chunk']['text']
    else:text=None
    claims=[{'text':text,'evidence':[{'source_id':'S1','quote':source['chunk']['text']}]}] if text else []
    answer={'schema_name':'home-rag-answer','schema_version':1,'status':'answered' if text else 'insufficient_evidence',
            'query':args.question,'composition':'demo-fixture','answer':{'answerable':bool(text),'claims':claims},
            'sources':[source] if text else [],'demo':True}
    write(out/'answer.json',answer)
    write(out/'run.json',{'schema_name':'home-rag-run','schema_version':1,'status':'completed','demo':True,
        'query':args.question,'stages':[{'name':name,'status':'completed'} for name in ('retrieval','assessment','answer')]})
    print('DEMO: wynik z danych syntetycznych, bez wyszukiwania i bez modelu.')


if __name__=='__main__':main()
