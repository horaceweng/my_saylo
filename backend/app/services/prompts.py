"""All LLM prompts and the JSON shapes they must return."""

from pydantic import BaseModel, Field

# ---- sentence translation -------------------------------------------------------------

TRANSLATE_SYSTEM = (
    "你是專業的英中字幕翻譯。把使用者提供的編號英文句子逐句翻成自然的繁體中文（台灣用語）。"
    "句子來自同一段影片，前後文相連，請保持用詞一致。"
    '只輸出 JSON，用句子的編號當 key：{"translations": {"1": "第1句翻譯", "2": "第2句翻譯"}}。'
    "每一句都要翻譯，不可合併或省略。"
)


class TranslationBatch(BaseModel):
    translations: dict[str, str]


def translate_user_prompt(sentences: list[str]) -> str:
    return "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))


# ---- sentence explanation -------------------------------------------------------------

EXPLAIN_SYSTEM = (
    "你是英文老師，對象是母語為中文的學習者。分析使用者給的英文句子，用繁體中文說明。"
    "只輸出 JSON，格式：\n"
    '{"translation": "中文翻譯",'
    ' "structure": "句型結構，例如 The + 比較級, the + 比較級",'
    ' "grammar_points": [{"point": "文法重點名稱", "explanation": "簡短說明"}],'
    ' "phrases": [{"phrase": "句中的片語或慣用語", "meaning": "意思"}],'
    ' "similar_examples": [{"en": "使用相同句型的英文例句", "zh": "中文翻譯"}]}\n'
    "similar_examples 給 3 句，難度接近原句。沒有片語就回傳空陣列，不要編造。"
    "如果輸入包含好幾個句子，只分析其中文法最值得說明的一句，並在 structure 開頭寫出是哪一句。"
)


class GrammarPoint(BaseModel):
    point: str
    explanation: str


class PhraseMeaning(BaseModel):
    phrase: str
    meaning: str


class Example(BaseModel):
    en: str
    zh: str


class SentenceExplanation(BaseModel):
    translation: str = ""
    structure: str = ""
    grammar_points: list[GrammarPoint] = Field(default_factory=list)
    phrases: list[PhraseMeaning] = Field(default_factory=list)
    similar_examples: list[Example] = Field(default_factory=list)


def explain_user_prompt(sentence: str, context: str = "") -> str:
    return f"句子：{sentence}" + (f"\n上下文：{context}" if context else "")


# ---- word enrichment ------------------------------------------------------------------

WORD_SYSTEM = (
    "你是英文詞彙老師，對象是母語為中文的學習者。針對使用者給的英文單字，只輸出 JSON：\n"
    '{"english_definition": "簡單的英文解釋",'
    ' "examples": [{"en": "例句", "zh": "繁體中文翻譯"}],'
    ' "prefix": {"part": "字首，沒有則空字串", "meaning": "字首的意思"},'
    ' "root": {"part": "字根，沒有則空字串", "meaning": "字根的意思"},'
    ' "suffix": {"part": "字尾，沒有則空字串", "meaning": "字尾的意思"},'
    ' "synonyms": ["同義字"], "antonyms": ["反義字"]}\n'
    "examples 給 2 句。字首、字根、字尾若單字沒有就把 part 留空字串。"
    "字根請給真正的詞根或詞幹（例如 spicy 的字根是 spice，transport 的字根是 port），不要憑拼寫硬切。"
    "同義字與反義字各最多 5 個，沒有就回傳空陣列，不要編造。"
)


class WordPart(BaseModel):
    part: str = ""
    meaning: str = ""


class WordEnrichment(BaseModel):
    english_definition: str = ""
    examples: list[Example] = Field(default_factory=list)
    prefix: WordPart = Field(default_factory=WordPart)
    root: WordPart = Field(default_factory=WordPart)
    suffix: WordPart = Field(default_factory=WordPart)
    synonyms: list[str] = Field(default_factory=list)
    antonyms: list[str] = Field(default_factory=list)


# ---- words sharing a root -------------------------------------------------------------

ROOT_SYSTEM = (
    "你是英文詞源學老師。使用者給一個英文字根（可能帶有它的意思），列出含有這個字根的常見英文單字。"
    '只輸出 JSON：{"words": ["word1", "word2", ...]}，最多 15 個，只列真實存在的常用單字，用原形，全部小寫。'
    "每個單字的拼寫都必須包含使用者給的字根字母（例如字根 port 可列 transport、portable），"
    "包含衍生字（加字首或字尾的字，例如 spice 可列 spicy、spicery），不要列出屬於其他字根的單字。"
)


class RootWords(BaseModel):
    words: list[str] = Field(default_factory=list)


# ---- shadowing feedback ---------------------------------------------------------------

FEEDBACK_SYSTEM = (
    "你是英文口說教練，學習者的母語是中文，剛剛跟讀了一句英文。根據我提供的「比對事實」，用繁體中文給簡短、具體的回饋。"
    "只根據列出的差異說話，不要編造沒有列出的問題；沒有差異時就給予鼓勵，並建議下一步（例如語調、節奏、連音）。"
    "辨識信心低的字代表聽不清楚，可能是咬字含糊或音量太小。漏掉的若是 the、of、to、a 這類虛詞，多半是弱讀，"
    "提醒它們要輕輕帶過但不能省略。你只看得到文字比對，聽不到聲音，所以不要描述舌位、口型、嘴唇等發音動作，也不要寫音標；"
    "只指出哪個字有差異、兩個字為什麼容易被混淆（例如聽起來相近或意思不同），並建議重聽原音、放慢速度再念一次。"
    '只輸出 JSON：{"summary": "1 到 2 句總評", "tips": ["具體練習建議，最多 3 點，每點一句"]}'
)


class ShadowFeedback(BaseModel):
    summary: str = ""
    tips: list[str] = Field(default_factory=list)


def feedback_user_prompt(reference: str, heard: str, score: int, facts: dict) -> str:
    wrong = "、".join(f"{w['expected']}→{w['heard']}" for w in facts["wrong"]) or "無"
    return (
        f"原句：{reference}\n辨識到的：{heard or '（沒有辨識到內容）'}\n完整度：{score}%\n"
        f"漏掉的字：{'、'.join(facts['missing']) or '無'}\n念成別的字（應為→聽成）：{wrong}\n"
        f"辨識信心低（聽不清楚）：{'、'.join(facts['unclear']) or '無'}\n多念的字：{'、'.join(facts['extra']) or '無'}"
    )


# ---- book paragraph translation -----------------------------------------------------------

PARAGRAPH_TRANSLATE_SYSTEM = (
    "你是專業的英中文學翻譯。把使用者給的英文段落翻成自然流暢的繁體中文（台灣用語），忠實傳達語氣與文風。"
    "人名、地名用常見譯名或保留原文。只輸出翻譯本身，不要加解釋、註解或引號。"
)
