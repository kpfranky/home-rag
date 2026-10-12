import json
from pathlib import Path
import re
import unittest


class CountFormatTests(unittest.TestCase):
    def test_correct_person_units_and_totals_without_accepting_wrong_numbers(self):
        path=Path(__file__).resolve().parents[1]/'config/evaluation/sample_book_100_v1.json'
        suite=json.loads(path.read_text())
        for case in suite['cases']:
            if case['category']!='table': continue
            total=104 if case['id'].startswith('T01') else 63
            pairs=[(59,61),(41,43),(0,0)] if total==104 else [(73,46),(19,12),(8,5)]
            for pattern,(percent,count) in zip(case['answer_patterns'],pairs):
                for text in [f'{percent}% ({count})',f'{percent}% ({count} osób)',
                             f'{percent}% ({count} osoby)',f'{percent}% ({count} z {total})',
                             f'{percent}% ({count} osób z {total} osób)']:
                    with self.subTest(case=case['id'],text=text):
                        self.assertIsNotNone(re.search(pattern,text))
                for text in [f'{percent}% ({count+1} osób)',f'{percent+1}% ({count} osób)',
                             f'{percent}% ({count} z {total+1})']:
                    with self.subTest(case=case['id'],text=text):
                        self.assertIsNone(re.search(pattern,text))


if __name__=='__main__': unittest.main()
