import json
from pathlib import Path
import re
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from assess_sources import assessment_messages
from answer_question import extraction_messages, validate_extraction, synthesis_messages
from ask import parser


class QualityRegressionTests(unittest.TestCase):
    def source(self, kind='table'):
        return {'source_id':'S1','chunk':{'chunk_type':kind,'section_path':['Sekcja'],
            'text':'Kolumny: c1: Kondycja | c2: Pozytywne efekty\nr1 c1: alergia (104)\nr1 c2: 59% (61)\nr2 c1: astma (26)\nr2 c2: 54% (14)'}}

    def test_row_labels_include_first_row_without_changing_text(self):
        source=self.source()
        payload=json.loads(assessment_messages('Pytanie?', [source])[1]['content'])
        presented=payload['sources'][0]
        self.assertEqual(presented['context']['table_row_labels'],
                         ['r1 c1: alergia (104)','r2 c1: astma (26)'])
        self.assertEqual(presented['text'],source['chunk']['text'])

    def test_signature_context_reaches_extraction(self):
        source={'source_id':'S1','chunk':{'chunk_type':'text',
                 'section_path':['Słowo wstępu'],'text':'mgr farm. Marcin Mól'}}
        payload=json.loads(extraction_messages('Kto podpisał?',source)[1]['content'])
        self.assertEqual(payload['section_path'],['Słowo wstępu'])
        self.assertEqual(payload['text'],'mgr farm. Marcin Mól')

    def test_source_type_reaches_synthesis_without_changing_quote(self):
        source=self.source()
        payload=json.loads(extraction_messages('Pytanie?',source)[1]['content'])
        first=payload['evidence_catalog'][0]
        items=validate_extraction({'items':[{'text':'59% (61)','evidence_id':first['evidence_id']}]},source)
        context=json.loads(synthesis_messages('Pytanie?',items)[1]['content'])
        self.assertEqual(context['items'][0]['chunk_type'],'table')
        self.assertEqual(context['items'][0]['quote'],first['quote'])

    def test_count_notation_accepts_correct_total_and_rejects_wrong_count(self):
        path=Path(__file__).resolve().parents[1]/'config/evaluation/sample_book_100_v1.json'
        suite=json.loads(path.read_text())
        case=next(c for c in suite['cases'] if c['id']=='T02P')
        pattern=case['answer_patterns'][0]
        self.assertIsNotNone(re.search(pattern,'73% (46 z 63)'))
        self.assertIsNotNone(re.search(pattern,'73% (46)'))
        self.assertIsNone(re.search(pattern,'73% (45 z 63)'))
        self.assertIsNone(re.search(pattern,'73% (46 z 99)'))


if __name__=='__main__':unittest.main()
