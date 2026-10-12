from copy import deepcopy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from table_scope import requested_rows
from answer_question import focused_catalog, extraction_messages, validate_extraction, extraction_sources
from search_chunks import rank_chunks
from embed_chunks import DIMENSION
import json

TEXT = ('Kolumny: c1: Kondycja | c2: Pozytywne efekty | c3: Brak wyników | c4: Negatywne efekty\n'
        'r1 c1: alergia (104)\nr1 c2: 59% (61)\nr1 c3: 41% (43)\nr1 c4: 0% (0)\n'
        'r2 c1: Leki przeciwdepresyjne (47)\nr2 c2: 89% (42)\nr2 c3: 11% (5)\nr2 c4: 0% (0)')
QUERY = 'Odczytaj z tabeli odsetki i liczby osób dla alergii: pozytywne efekty, brak wyników, negatywne efekty.'


class TableScopeTests(unittest.TestCase):
    def source(self):
        return {'source_id':'S1','chunk':{'chunk_type':'table','text':TEXT}}

    def test_inflection_and_explicit_table_requirement(self):
        self.assertEqual([r[0] for r in requested_rows(TEXT,QUERY)],['1'])
        self.assertEqual(requested_rows(TEXT,'Opisz alergię.'),[])
        text='r19 c1: Nadciśnienie tętnicze (63)\nr19 c2: 73% (46)'
        self.assertEqual([r[0] for r in requested_rows(text,'Odczytaj z tabeli dane dla nadciśnienia tętniczego.')],['19'])

    def test_no_unrequested_row_reaches_model_or_validation(self):
        source=self.source(); original=deepcopy(source)
        payload=json.loads(extraction_messages(QUERY,source)[1]['content'])
        self.assertNotIn('przeciwdepresyjne',payload['text'])
        catalog=focused_catalog(source,QUERY)
        for entry in catalog:
            span=entry['text_span']
            self.assertEqual(entry['quote'],TEXT[span['start']:span['end']])
            self.assertNotIn('r2',entry['quote'])
        with self.assertRaises(ValueError):
            validate_extraction({'items':[{'text':'89% (42)','evidence_id':'S1:R2:E1'}]},source,QUERY)
        self.assertEqual(source,original)

    def test_second_row_quote_has_original_offsets_and_header_context(self):
        query='Jakie wartości podaje tabela dla leków przeciwdepresyjnych?'
        source=self.source()
        catalog=focused_catalog(source,query)
        self.assertTrue(catalog)
        self.assertEqual(catalog[0]['quote'],TEXT[catalog[0]['text_span']['start']:catalog[0]['text_span']['end']])
        payload=json.loads(extraction_messages(query,source)[1]['content'])
        self.assertTrue(payload['text'].startswith('Kolumny:'))
        self.assertNotIn('r1 c1',payload['text'])

    def test_multiple_rows_and_unknown_subject_are_not_silently_removed(self):
        self.assertEqual(len(requested_rows(TEXT,'Podaj tabelę dla alergii i leków przeciwdepresyjnych.')),2)
        self.assertEqual(requested_rows(TEXT,'Podaj tabelę dla migreny.'),[])

    def test_matching_table_precedes_higher_cosine_prose_and_keeps_scores(self):
        records=[{'chunk_id':'prose','chunk':{'chunk_type':'text','text':'alergia'}},
                 {'chunk_id':'table','chunk':{'chunk_type':'table','text':TEXT}}]
        before=deepcopy(records)
        v1=[1.0]+[0.0]*(DIMENSION-1)
        v2=[0.0,1.0]+[0.0]*(DIMENSION-2)
        plain=rank_chunks(records,[v1,v2],v1,2)
        scoped=rank_chunks(records,[v1,v2],v1,2,table_query=QUERY)
        self.assertEqual(plain[0]['chunk_id'],'prose')
        self.assertEqual(scoped[0]['chunk_id'],'table')
        self.assertEqual(scoped[0]['score'],0.0)
        self.assertEqual(records,before)

    def test_only_matching_tables_supply_evidence_when_target_row_exists(self):
        matched=self.source()
        irrelevant={'source_id':'S2','chunk':{'chunk_type':'table','text':'r1 c1: astma (26)\nr1 c2: 54% (14)'}}
        prose={'source_id':'S3','chunk':{'chunk_type':'text','text':'Opis alergii.'}}
        self.assertEqual(extraction_sources(QUERY,[irrelevant,prose,matched]),[matched])
        self.assertEqual(extraction_sources('Opisz alergię.',[prose,matched]),[prose,matched])

    def test_long_target_row_never_contains_next_row(self):
        source=self.source()
        source['chunk']['text']='r1 c1: alergia (104)\nr1 c2: '+('dane '*100)+'\nr2 c1: astma (26)\nr2 c2: 54% (14)'
        catalog=focused_catalog(source,QUERY)
        self.assertGreater(len(catalog),1)
        self.assertTrue(all(len(e['quote'])<=320 and 'r2' not in e['quote'] for e in catalog))


if __name__=='__main__':unittest.main()
