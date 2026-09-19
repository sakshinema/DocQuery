from lib.extract import grounded_answer, heuristic_extract


def test_heuristic_extraction_finds_high_signal_fields():
    result = heuristic_extract('invoice.txt', 'Acme Invoice\nTotal: INR 12,500\nEmail: finance@example.com\nDue: 30/09/2026')
    assert result['document_type'] == 'invoice'
    assert 'finance@example.com' in [e['value'] for e in result['entities']]
    assert any(e['type'] == 'currency' for e in result['entities'])


def test_question_with_no_evidence_does_not_call_or_prompt_a_model(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'not-used')
    result = grounded_answer('What is the renewal date?', [])
    assert result['mode'] == 'no-evidence'
    assert 'couldn\'t find indexed evidence' in result['answer']
