"""Conservative matching of explicit Polish table questions to row labels."""
import re

STOP = {'i', 'a', 'w', 'z', 'ze', 'na', 'po', 'do', 'dla', 'oraz', 'przy'}


def terms(text):
    # Limited Polish inflection matching, not a general stemmer or synonym resolver.
    result = set()
    for word in re.findall(r'[^\W\d_]+', text.casefold()):
        if len(word) <= 2 or word in STOP:
            continue
        if len(word) <= 5:
            shortened = re.sub(r'(ów|om|ami|ach|a|i|y|ę|ą|e)$', '', word)
            word = shortened if len(shortened) >= 3 else word
        result.add(word[:5])
    return result


def row_spans(text):
    matches = list(re.finditer(r'^r([0-9]+) c1:\s*([^\n]+)', text, re.MULTILINE))
    return [(m[1], m[2], m.start(), matches[i+1].start() if i+1 < len(matches) else len(text))
            for i, m in enumerate(matches)]


def requested_rows(text, query):
    if not isinstance(query, str) or not re.search(r'\btabel\w*', query.casefold()):
        return []
    query_terms = terms(query)
    result = []
    for row, label, start, end in row_spans(text):
        # Counts and notes in parentheses do not identify the condition.
        label_terms = terms(re.sub(r'\([^)]*\)', '', label))
        if label_terms and label_terms <= query_terms:
            result.append((row, label, start, end))
    return result
