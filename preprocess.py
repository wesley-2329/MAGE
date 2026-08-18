import re
from itertools import chain
from cleantext import clean

class MosesPunctNormalizer:
    EXTRA_WHITESPACE = [
        (r"\r", r""),
        (r"\(", r" ("),
        (r"\)", r") "),
        (r" +", r" "),
        (r"\) ([.!:?;,])", r")\g<1>"),
        (r"\( ", r"("),
        (r" \)", r")"),
        (r"(\d) %", r"\g<1>%"),
        (r" :", r":"),
        (r" ;", r";"),
    ]
    NORMALIZE_UNICODE_IF_NOT_PENN = [(r"`", r"'"), (r"''", r' " ')]
    NORMALIZE_UNICODE = [
        ("„", r'"'), ("“", r'"'), ("”", r'"'), ("–", r"-"),
        ("—", r" - "), (r" +", r" "), ("´", r"'"),
        ("([a-zA-Z])‘([a-zA-Z])", r"\g<1>'\g<2>"),
        ("([a-zA-Z])’([a-zA-Z])", r"\g<1>'\g<2>"),
        ("‘", r"'"), ("‚", r"'"), ("’", r"'"),
        (r"''", r'"'), ("´´", r'"'), ("…", r"..."),
    ]
    FRENCH_QUOTES = [
        ("\u00A0«\u00A0", r'"'), ("«\u00A0", r'"'), ("«", r'"'),
        ("\u00A0»\u00A0", r'"'), ("\u00A0»", r'"'), ("»", r'"'),
    ]
    HANDLE_PSEUDO_SPACES = [
        ("\u00A0%", r"%"), ("nº\u00A0", "nº "), ("\u00A0:", r":"),
        ("\u00A0ºC", " ºC"), ("\u00A0cm", r" cm"), ("\u00A0\\?", "?"),
        ("\u00A0\\!", "!"), ("\u00A0;", r";"), (",\u00A0", r", "),
        (r" +", r" "),
    ]
    EN_QUOTATION_FOLLOWED_BY_COMMA = [(r'"([,.]+)', r'\g<1>"')]
    OTHER = [("(\\d)\u00A0(\\d)", r"\g<1>.\g<2>")]
    REPLACE_UNICODE_PUNCTUATION = [
        ("，", ","), (r"。\s*", ". "), ("、", ","), ("”", '"'), ("“", '"'),
        ("∶", ":"), ("：", ":"), ("？", "?"), ("《", '"'), ("》", '"'),
        ("）", ")"), ("！", "!"), ("（", "("), ("；", ";"), ("」", '"'),
        ("「", '"'), ("０", "0"), ("１", "1"), ("２", "2"), ("３", "3"),
        ("４", "4"), ("５", "5"), ("６", "6"), ("７", "7"), ("８", "8"),
        ("９", "9"), (r"．\s*", ". "), ("～", "~"), ("’", "'"),
        ("…", "..."), ("━", "-"), ("〈", "<"), ("〉", ">"),
        ("【", "["), ("】", "]"), ("％", "%"),
    ]

    def __init__(self):
        self.substitutions = [
            self.EXTRA_WHITESPACE,
            self.NORMALIZE_UNICODE_IF_NOT_PENN,
            self.NORMALIZE_UNICODE,
            self.FRENCH_QUOTES,
            self.HANDLE_PSEUDO_SPACES,
            self.EN_QUOTATION_FOLLOWED_BY_COMMA,
            self.OTHER
        ]
        self.substitutions = list(chain(*self.substitutions))

    def normalize(self, text):
        for regexp, substitution in self.substitutions:
            text = re.sub(regexp, substitution, str(text))
        return text.strip()

def _tokenization_norm(text):
    text = text.replace(' ,', ',').replace(' .', '.').replace(' ?', '?').replace(' !', '!').replace(' ;', ';')\
               .replace(" '", "'").replace(" ’ ", "'").replace(' :', ':').replace('<newline>', '\n')\
               .replace('`` ', '"').replace(" ''", '"').replace("''", '"').replace('.. ', '... ')\
               .replace(' )', ')').replace('( ', '(').replace(" n't", "n't").replace(' i ', ' I ')\
               .replace(" i'", " I'").replace("\\'", "'").replace('\n ', '\n').strip()
    return text

def _clean_text(text):
    # Remove PLM special tokens
    plm_special_tokens = r'(\<pad\>)|(\<s\>)|(\<\/s\>)|(\<unk\>)|(\<\|endoftext\|\>)'
    text = re.sub(plm_special_tokens, "", text)

    # Punctuation Normalization
    normalizer = MosesPunctNormalizer()
    text = normalizer.normalize(text)
    text = _tokenization_norm(text)

    # Clean details
    text = clean(text,
                 fix_unicode=True,
                 to_ascii=True,
                 lower=False,
                 no_line_breaks=True,
                 no_urls=True,
                 no_emails=True,
                 no_phone_numbers=True,
                 replace_with_url="",
                 replace_with_email="",
                 replace_with_phone_number="",
                 replace_with_number="<NUMBER>",
                 replace_with_digit="<DIGIT>",
                 replace_with_currency_symbol="<CUR>",
                 lang="en")

    # Keep common punctuation only
    punct_pattern = r'[^ A-Za-z0-9.?!,:;\-\[\]\{\}\(\)\'\"]'
    text = re.sub(punct_pattern, '', text)
    spe_pattern = r'[- \[\]\{\}\(\)\'\"]{2,}'
    text = re.sub(spe_pattern, '', text)
    text = " ".join(text.split())
    return text

def _rm_line_break(text):
    text = text.replace("\n","\\n")
    text = re.sub(r'(?:\\n)*\\n', r'\\n', text)
    text = re.sub(r'^.{0,3}\\n', '', text)
    text = text.replace("\\n"," ")
    return text

def preprocess(text):
    text = _rm_line_break(text)
    text = _clean_text(text)
    return text
