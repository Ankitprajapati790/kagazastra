# In-Memory KrutiDev 010 to Unicode Trans-lexer for Indian Govt PDFs
KRUTIDEV_UNICODE_MAP = {
    "k": "ा", "l": "ि", "h": "ी", "s": "े", "S": "ै", "q": "ु", "Q": "ू",
    "d": "क", "D": "क्", "x": "ग", "X": "ग्", "c": "म", "C": "म्", "v": "न", "V": "न्",
    "b": "य", "B": "य्", "n": "द", "N": "द्", "m": "उ", "M": "ऊ", "a": "ं",
    "r": "ज", "R": "ज्", "t": "त", "T": "त्", "y": "ल", "Y": "ल्", "u": "ह",
    "i": "प", "I": "प्", "o": "व", "O": "व्", "p": "च", "P": "च्", "g": "ह",
    "f": "ा", "j": "र", "J": "र्", "e": "s", "w": "भ", "W": "ब्", "z": "श", "Z": "ष्"
}

def convert_krutidev_to_unicode(krutidev_text: str) -> str:
    """Converts legacy KrutiDev 010 encoded text to standard Unicode Hindi"""
    result = []
    i = 0
    while i < len(krutidev_text):
        ch = krutidev_text[i]
        # Matra 'i' prefix swap handling in KrutiDev
        if ch == 'f' and i + 1 < len(krutidev_text):
            next_ch = KRUTIDEV_UNICODE_MAP.get(krutidev_text[i+1], krutidev_text[i+1])
            result.append(next_ch)
            result.append("ि")
            i += 2
            continue
        result.append(KRUTIDEV_UNICODE_MAP.get(ch, ch))
        i += 1
    return "".join(result)

def bilingual_search(text_corpus: str, query: str) -> tuple:
    """Checks match across raw text, converted text, and lowercase.
    Returns (match_found, matching_positions)
    """
    norm_query = query.strip().lower()

    matching_positions = []

    # Search in raw text (lowercase)
    if norm_query in text_corpus.lower():
        start = 0
        while True:
            pos = text_corpus.lower().find(norm_query, start)
            if pos == -1:
                break
            matching_positions.append(pos)
            start = pos + 1

    # Search in converted KrutiDev to Unicode
    converted_corpus = convert_krutidev_to_unicode(text_corpus).lower()
    if norm_query in converted_corpus:
        start = 0
        while True:
            pos = converted_corpus.find(norm_query, start)
            if pos == -1:
                break
            if pos not in matching_positions:
                matching_positions.append(pos)
            start = pos + 1

    matching_positions.sort()
    return len(matching_positions) > 0, matching_positions


def highlight_matches(text: str, query: str) -> str:
    """Highlights all matches of query in text with green background"""
    if not query.strip():
        return text

    import re
    norm_query = query.strip().lower()
    result = text

    # Highlight matches in raw text (case-insensitive)
    def replace_match(match):
        return f"<mark style='background-color: green;'>{match.group(0)}</mark>"

    # Search and highlight in raw text
    pattern = re.compile(re.escape(norm_query), re.IGNORECASE)
    result = pattern.sub(replace_match, result)

    return result
