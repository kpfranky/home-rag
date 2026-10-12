from copy import deepcopy
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from grounded_evidence import table_answer, selected_answer, validate_selection
from answer_question import evidence_catalog, grounded_answer
import assess_evidence


def table():
    return {'source_id':'S1','chunk':{'chunk_type':'table','source_id':'book','text':
        'Kolumny: c1: Kondycja | c2: Pozytywne efekty | c3: Brak wyników | c4: Negatywne efekty\n'
        'r19 c1: Nadciśnienie tętnicze (63)\nr19 c2: 73% (46)\nr19 c3: 19% (12)\nr19 c4: 8% (5)'}}

QUERY='Odczytaj z tabeli wartości dla nadciśnienia tętniczego: pozytywne efekty, brak wyników i negatywne efekty.'


class GroundedEvidenceTests(unittest.TestCase):
    def test_table_preserves_column_names_and_values(self):
        answer=table_answer(QUERY,[table()])
        self.assertEqual(len(answer['claims']),3)
        self.assertIn('Brak wyników — 19% (12)',answer['claims'][1]['text'])
        self.assertNotIn('ma pozytywne efekty',answer['claims'][0]['text'])
        self.assertTrue(all(e['quote'] in table()['chunk']['text'] for c in answer['claims'] for e in c['evidence']))

    def test_selecting_one_column_does_not_return_others(self):
        result=table_answer('Odczytaj z tabeli pozytywne efekty dla nadciśnienia tętniczego.',[table()])
        self.assertEqual(len(result['claims']),1)

    def test_incomplete_mapping_falls_back(self):
        source=table();source['chunk']['text']=source['chunk']['text'].split('\n',1)[1]
        self.assertIsNone(table_answer(QUERY,[source]))

    def test_conflicting_rows_rejected(self):
        second=deepcopy(table());second['source_id']='S2'
        second['chunk']['text']=second['chunk']['text'].replace('73% (46)','74% (46)')
        with self.assertRaises(ValueError):table_answer(QUERY,[table(),second])

    def test_context_is_recorded_but_never_rendered_as_answer(self):
        catalog=[{'evidence_id':'S1:E1','source_id':'S1','quote':'Bezpośrednia odpowiedź.'},
                 {'evidence_id':'S2:E1','source_id':'S2','quote':'Kontekst.'}]
        answer=selected_answer({'direct_ids':['S1:E1'],'context_ids':['S2:E1']},catalog)
        self.assertEqual(len(answer['claims']),1)
        self.assertNotIn('Kontekst',answer['claims'][0]['text'])
        self.assertFalse(selected_answer({'direct_ids':[],'context_ids':['S2:E1']},catalog)['answerable'])

    def test_unknown_ids_and_overlap_rejected(self):
        catalog=[{'evidence_id':'S1:E1'}]
        for selection in [{'direct_ids':['invented'],'context_ids':[]},
                          {'direct_ids':['S1:E1'],'context_ids':['S1:E1']}]:
            with self.assertRaises(ValueError):validate_selection(selection,catalog)

    def test_classification_is_copied_from_original_not_synthesized(self):
        source={'source_id':'S1','chunk':{'chunk_type':'text','text':
           'Związki izoksazolowe zawarte w grzybie to głównie kwas ibotenowy i muscymol.'}}
        catalog=evidence_catalog(source)
        report={'assessment_mode':'evidence-selection','evidence_selection':
                {'direct_ids':[catalog[0]['evidence_id']],'context_ids':[]}}
        answer=grounded_answer('Jakie związki?', [source],[source],report)
        self.assertIn(source['chunk']['text'],answer['claims'][0]['text'])
        self.assertNotIn('muskaryna',answer['claims'][0]['text'])
        report['evidence_selection']['direct_ids']=[]
        with self.assertRaises(ValueError):grounded_answer('Jakie związki?',[source],[source],report)

    def test_forged_table_snapshot_rejected(self):
        answer=table_answer(QUERY,[table()]);answer['claims'][0]['text']='Zmieniona wartość.'
        report={'assessment_mode':'evidence-selection','structured_table':answer}
        with self.assertRaises(ValueError):grounded_answer(QUERY,[table()],[table()],report)

    def test_structured_table_assessment_does_not_call_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'assessment.json'
            argv=['assess_evidence.py','search.json','--embeddings','embeddings.jsonl',
                  '--embedding-report','embedding_report.json','--model','local','--output',str(output)]
            with patch.object(sys,'argv',argv), patch.object(assess_evidence,'load_sources',
                 return_value=(QUERY,[table()],'searchhash',{'output_sha256':'indexhash'})), \
                 patch.object(assess_evidence,'local_model',side_effect=AssertionError('Model must not run')):
                assess_evidence.main()
            result=json.loads(output.read_text())
            self.assertEqual(result['status'],'assessed')
            self.assertEqual(result['decision']['source_ids'],['S1'])
            self.assertIn('structured_table',result)


if __name__=='__main__':unittest.main()
