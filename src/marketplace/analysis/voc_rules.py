"""Transparent Portuguese keyword classifier for complaint reasons.

Why it exists: the LLM path (Ollama qwen2.5:7b) is the first choice, but it needs ~5 GB
of free unified memory and ~1 s per review; on a loaded laptop it stalled at 75-120 s per
review. A rule set is cheap, deterministic, explainable to a VP ("we count reviews that
say 'só veio um'") and labels ALL ~40k reviews with text instead of a sample.

Rules were written from a development sample (`voc dev-export`) that is disjoint from both
silver-label sets, then frozen and scored once against set A (240) and set B (160, drawn and
labelled before the rules were written).

Order = priority: the first matching rule is the primary reason.
"""

from __future__ import annotations

import re
import unicodedata

NUM = r"(?:\d+|um|uma|dois|duas|tres|quatro|cinco|metade|parte)"

RULES: list[tuple[str, list[str]]] = [
    ("incomplete_order", [
        rf"\b(?:so|apenas|somente)\s+(?:me\s+)?(?:veio|vieram|chegou|chegaram|recebi|entregaram|foi entregue|enviaram)\s+{NUM}",
        r"\b(?:recebi|chegou|chegaram|veio|vieram|entregaram)\s+(?:apenas|somente|so)\b",
        rf"\brecebi\s+{NUM}\s+d[eo]s?\s+{NUM}",
        r"\bfaltou\b|\bfaltando\b|\bfaltaram\b|\bfalta(?:m)? (?:o|a|os|as|um|uma|\d+|peca|pecas|item|itens|produto|parte|instruc|manual)\b",
        r"\bcomprei (?:\d+|dois|duas|tres|quatro) .{0,40}\b(?:entregaram|chegou|chegaram|veio|vieram|recebi) (?:\d+|um|uma)\b",
        r"\bso (?:foi entregue|veio|chegou|chegaram|recebi) (?:o|a|os|as)\b",
        r"\b(?:apenas|so|somente) (?:\d+|um|uma) (?:chegou|veio|foi entregue)",
        r"\bveio sem\b|\bvieram sem\b|\bchegou sem\b",
        r"\bem partes\b|\bparte do (?:meu )?pedido\b|\bentregaram metade\b|\bso veio a metade\b",
        r"\bnao (?:veio|chegou|recebi) (?:o|a|os|as) (?!produto\b|pedido\b|mercadoria\b|encomenda\b)\w+",
        r"\bcomprei (?:\d+|dois|duas|tres|quatro) .{0,60}\b(?:so|apenas|somente)\b",
    ]),
    ("poor_quality_described", [
        r"diferente d[aoe]s? (?:foto|imagem|anuncio|anunciad|descri|propaganda|ilustra|site)|diferente do que (?:imaginei|esperava|pensei)",
        r"\bnao (?:e|era|foi|corresponde) (?:igual )?(?:a|ao|o) (?:anunciad|da foto|descri)",
        r"propaganda enganosa|nao corresponde|nao condiz",
        r"falsificad|\bfalso\b|\bfalsa\b|replica|generico|imitacao|paralelo|remanufaturad|nao e original|nao era original",
    ]),
    ("wrong_item", [
        r"\b(?:veio|vieram|chegou|recebi|mandaram|mandou|enviaram|enviou|entregaram|entregue)\b(?:\s+\w+){0,3}\s+(?:errad|trocad)",
        r"\b(?:veio|vieram|chegou|recebi|mandaram|mandou|enviaram|enviou|entregaram|entregue)\s+(?:o |a |um |uma )?(?:produto |modelo |item )?(?:outro|outra)\b",
        r"produto errado|pedido errado|mercadoria errada|entrega errada|item errado|modelo errado",
        r"\bcor (?:errada|diferente|recebida)\b|\bveio (?:na )?cor\b|\bna cor\b.{0,30}\b(?:veio|recebi|chegou)\b|\b(?:veio|recebi|chegou)\b.{0,30}\bna cor\b|nao veio na cor",
        r"\bao inves\b|\bno lugar\b|\bem vez de\b",
        r"\bnao (?:foi|era|e) o que (?:eu )?(?:comprei|pedi|encomendei)",
        r"\bpedi .{0,40} e (?:veio|recebi|chegou)",
    ]),
    ("not_received", [
        r"\bnao (?:recebi|recebemos|chegou|chegaram|foi entregue|foram entregues|entregaram|entregue|fizeram a entrega)",
        r"\bainda nao (?:recebi|chegou|foi entregue)|\bnao (?:o|a) recebi|\bnao entrega\b",
        r"\b(?:estou |continuo )?(?:aguardando|esperando) (?:o meu |a minha |o |a |meu |minha )?(?:produto|pedido|entrega|encomenda|mercadoria|chegar)",
        r"\bcade (?:o|a|meu|minha)\b|\bnada (?:chegou|de entregar)|\bnunca chegou|\bnao (?:houve|ocorreu) a entrega",
        r"consta (?:como )?entregue|\bnao recebi\b",
    ]),
    ("damaged_defective", [
        r"quebrad|defeito|danificad|amassad|trincad|rachad|avariad|riscad|arranhad|estragad|rasgad|descolou|vaza\b|vazando",
        r"\bnao (?:funciona|funcionou|liga|ligou|esta funcionando|veio funcionando)|parou de funcionar|sem funcionar",
    ]),
    ("refund_cancellation", [
        r"estorn|reembols|ressarc|restitui|dinheiro de volta|devolucao do (?:dinheiro|valor)",
        r"cancel|nota fiscal|\bnf\b|cobran|cobrad|boleto|fatur",
        r"\bsem (?:ter )?(?:em )?estoque|nao estar disponivel|nao (?:tinha|tinham|possuem|ha) (?:o produto )?(?:em |no )?estoque|indisponivel|nao tem estoque",
        r"\bdevolu|\bdevolver\b|\btroca\b",
    ]),
    ("poor_quality", [
        r"qualidade|material|acabamento|\bfin[oa]\b|fragil|fraco|fraca|desbotad|descasc|mal feito|nao gostei|pessimo produto|produto ruim|\bruim\b|horrivel|porcaria|vencid",
    ]),
    ("late_delivery", [
        r"atras|demor|prazo (?:de |para )?(?:a )?(?:entrega )?(?:muito |bem |excessivamente )?(?:longo|grande|alto|extenso)|prazo menor|fora do prazo|depois do prazo|passou do prazo|nao (?:chegou|foi entregue) no prazo",
    ]),
    ("seller_communication", [
        r"(?:sem|nenhuma|nenhum|nao (?:tive|obtive|recebi|tenho|da)) (?:uma )?(?:resposta|retorno|posicao|contato|satisfacao|informac)",
        r"ninguem (?:me )?(?:responde|da|entra|entrou)|nao (?:me )?responde|atendimento|rastrei",
    ]),
]
POSITIVE = re.compile(
    r"otim|excelente|recomendo|adorei|amei|perfeit|muito bom|muito boa|gostei|satisfeit|"
    r"antes do prazo|no prazo|dentro do prazo|rapid|parabens|nota 10|tudo (?:certo|ok|em ordem)|"
    r"\bbom\b|\bboa\b|maravilh|lindo|linda|confiavel|correto"
)


NEGATIVE = re.compile(
    r"nao (?:e|foi|era) (?:bom|boa)|nao recomendo|nao gostei|pessim|horrivel|ruim|deixou a desejar|"
    r"decepc|vergonha|absurdo"
)


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.lower())


COMPILED = [(label, [re.compile(p) for p in pats]) for label, pats in RULES]


def classify(title: str | None, message: str, score: int) -> str:
    t = normalise(f"{title or ''} . {message or ''}")
    for label, pats in COMPILED:
        if any(p.search(t) for p in pats):
            label = "poor_quality" if label == "poor_quality_described" else label
            # High scores with a mild mention are still praise ("veio rapido, falta so...").
            if score >= 4 and label in {"late_delivery", "seller_communication", "poor_quality"} \
                    and POSITIVE.search(t):
                return "positive"
            return label
    if score >= 4 or (POSITIVE.search(t) and not NEGATIVE.search(t)):
        return "positive"
    return "other"
