from lib.normalize import ParsedPage, chunk_pages, clean_text, remove_repeated_headers_footers


def test_clean_text_collapses_whitespace_without_destroying_paragraphs():
    value = clean_text('A   line\n\n\nB\tline')
    assert value == 'A line\n\nB line'


def test_repeated_headers_and_footers_are_removed_conservatively():
    pages = [
        ParsedPage(i, None, f"Acme Confidential\nBody page {i}\nPage {i}")
        for i in range(1, 5)
    ]
    result = remove_repeated_headers_footers(pages)
    assert result[0].text == 'Body page 1'
    assert result[-1].text == 'Body page 4'


def test_unique_page_header_is_not_removed():
    pages = [ParsedPage(i, None, f"Special title {name}\nBody {i}") for i, name in enumerate(['Alpha', 'Beta', 'Gamma', 'Delta'], start=1)]
    result = remove_repeated_headers_footers(pages)
    assert result[0].text.startswith('Special title Alpha')


def test_chunking_retains_page_provenance():
    pages = [ParsedPage(7, 'Risk', 'one paragraph\n\n' + 'word ' * 900)]
    chunks = chunk_pages(pages, target_chars=800, overlap_chars=100)
    assert len(chunks) >= 2
    assert all(c.page == 7 for c in chunks)
    assert all(c.section == 'Risk' for c in chunks)
