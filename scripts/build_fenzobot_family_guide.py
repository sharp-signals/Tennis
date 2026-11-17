"""Build the plain-language Fenzobot family and subweight guide."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "manuals" / "Fenzobot_Guia_das_Familias_e_Subpesos.docx"
LOGO = ROOT / "docs" / "assets" / "fenzo-logo.png"

NAVY = "12304A"
TEAL = "20BFC1"
ORANGE = "FF9851"
PALE_BLUE = "EAF3F8"
BORDER = "D9D9D9"
BLACK = RGBColor(0, 0, 0)


def _shade(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def _set_cell_margins(cell, top=110, start=120, bottom=110, end=120) -> None:
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for margin, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{margin}"))
        if node is None:
            node = OxmlElement(f"w:{margin}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")


def _set_cell_borders(cell, color=BORDER, size="6") -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = f"w:{edge}"
        element = borders.find(qn(tag))
        if element is None:
            element = OxmlElement(tag)
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), size)
        element.set(qn("w:color"), color)


def _set_font(run, *, name="Aptos", size=10.5, bold=False, color=BLACK) -> None:
    run.font.name = name
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:ascii"), name)
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:hAnsi"), name)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def _format_table(table, widths, *, header_fill=NAVY) -> None:
    table.autofit = False
    table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
    for r_idx, row in enumerate(table.rows):
        for c_idx, cell in enumerate(row.cells):
            cell.width = Inches(widths[c_idx])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            _set_cell_margins(cell)
            _set_cell_borders(cell)
            if r_idx == 0:
                _shade(cell, header_fill)
            elif r_idx % 2 == 0:
                _shade(cell, PALE_BLUE)
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = 1.05
                for run in paragraph.runs:
                    _set_font(
                        run, size=9.1, bold=r_idx == 0,
                        color=RGBColor(255, 255, 255) if r_idx == 0 else BLACK,
                    )


def _table(doc, headers, rows, widths, *, header_fill=NAVY):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for cell, value in zip(table.rows[0].cells, headers, strict=True):
        cell.text = value
    for row_values in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, row_values, strict=True):
            cell.text = value
    _format_table(table, widths, header_fill=header_fill)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)
    return table


def _heading(doc, text, level=1):
    paragraph = doc.add_heading(text, level=level)
    paragraph.paragraph_format.keep_with_next = True
    paragraph.paragraph_format.left_indent = Inches(0)
    paragraph.paragraph_format.first_line_indent = Inches(0)
    return paragraph


def _body(doc, text, *, bold_lead: str | None = None):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(7)
    p.paragraph_format.line_spacing = 1.12
    if bold_lead:
        lead = p.add_run(bold_lead)
        _set_font(lead, bold=True)
    run = p.add_run(text)
    _set_font(run)
    return p


def _bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.08
    run = p.add_run(text)
    _set_font(run)
    return p


def _page_break(doc):
    doc.add_page_break()


def build() -> Path:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.72)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.78)
    section.right_margin = Inches(0.78)

    styles = doc.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"].font.size = Pt(10.5)
    for style_name, size in (("Title", 25), ("Heading 1", 18), ("Heading 2", 13.5), ("Heading 3", 11.5)):
        style = styles[style_name]
        style.font.name = "Aptos Display" if style_name != "Normal" else "Aptos"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = BLACK
        style.paragraph_format.space_before = Pt(12 if style_name != "Title" else 0)
        style.paragraph_format.space_after = Pt(6)

    if LOGO.exists():
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(str(LOGO), width=Inches(2.15))
        p.paragraph_format.space_after = Pt(18)
    title = doc.add_paragraph(style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run("Fenzobot Guia das Famílias e Subpesos")
    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run("Como o modelo transforma evidência de ténis em probabilidade e fair odd")
    _set_font(run, size=13, bold=False, color=RGBColor(70, 70, 70))
    subtitle.paragraph_format.space_after = Pt(28)
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = meta.add_run("Versão metodológica 13  |  17 de novembro de 2026  |  ATP e WTA")
    _set_font(run, size=10, color=RGBColor(90, 90, 90))
    meta.paragraph_format.space_after = Pt(34)
    _body(
        doc,
        "Este guia explica, em linguagem simples, as cinco famílias do Fenzobot, "
        "todos os subpesos atualmente usados, a hierarquia entre famílias e a forma "
        "como o resultado se transforma numa probabilidade independente do mercado. "
        "Serve como manual de leitura do relatório e como referência comum para José Guerra e Hugo.",
    )
    _body(
        doc,
        "A ideia central é simples: o modelo não conta apenas quantos fatores apontam para cada jogador. "
        "Mede a intensidade de cada sinal, a qualidade e a dimensão da amostra, combina os sinais dentro "
        "da respetiva família e só depois junta as cinco famílias.",
        bold_lead="Conclusão principal  ",
    )

    _page_break(doc)
    _heading(doc, "Como ler o sistema", 1)
    _body(
        doc,
        "Cada subpeso compara o jogador A com o jogador B. Um valor positivo favorece o jogador A; "
        "um valor negativo favorece o jogador B. Antes de entrar na equação, o valor é reduzido quando "
        "a amostra é curta e normalizado com dados históricos anteriores ao jogo.",
    )
    _table(
        doc,
        ["Etapa", "O que acontece", "O que o utilizador vê"],
        [
            ("1  Recolha", "Resultados, ranking, piso, H2H e estatísticas de pontos.", "Dados factuais do encontro."),
            ("2  Subpesos", "Cada métrica é comparada, ajustada à amostra e ao nível competitivo.", "Barras internas da família."),
            ("3  Família", "Os subpesos formam uma probabilidade própria da família.", "Direção e intensidade da família."),
            ("4  Hierarquia", "As duas famílias principais comandam; as secundárias refinam.", "Mapa das cinco famílias."),
            ("5  Fair odd", "A probabilidade final é calibrada apenas com histórico anterior.", "Probabilidade, intervalo e fair odd."),
            ("6  Mercado", "A odd observada é comparada só depois da fair odd estar fechada.", "Edge central e conservador."),
        ],
        [1.05, 3.2, 2.55],
    )
    _heading(doc, "Hierarquia das famílias", 2)
    _table(
        doc,
        ["Papel", "Família", "Coeficiente ATP", "Coeficiente WTA"],
        [
            ("Principal", "Forma recente ajustada", "0,405", "0,405"),
            ("Principal", "Força estrutural", "0,465", "0,639"),
            ("Secundária relevante", "Superfície e condições", "0,302", "0,326"),
            ("Secundária contextual", "Matchup e confronto direto", "0,125", "0,124"),
            ("Secundária contextual", "Serviço e resposta", "0,125", "0,124"),
        ],
        [1.45, 2.65, 1.35, 1.35],
        header_fill="294A5F",
    )
    _body(
        doc,
        "Os coeficientes não são percentagens. Multiplicam a força contínua produzida por cada família. "
        "Uma família secundária com um sinal muito forte pode ter impacto, mas a versão 13 impede que "
        "uma única secundária ultrapasse a principal mais forte quando todas concordam. Quando existe "
        "conflito, cada secundária fica limitada à média das principais e o bloco secundário não pode "
        "superar o bloco principal.",
    )

    _page_break(doc)
    _heading(doc, "Intensidade visual e impacto real", 1)
    _body(
        doc,
        "A barra é contínua. As palavras residual, muito ligeiro, ligeiro, moderado, forte e muito forte "
        "são apenas faixas de leitura. O cálculo usa o valor exato, não a palavra. Duas barras classificadas "
        "como ligeiras podem, por isso, ter comprimentos diferentes e produzir efeitos diferentes na fair odd.",
    )
    _table(
        doc,
        ["Designação", "Mudança ao retirar a família", "Leitura"],
        [
            ("Residual", "menos de 0,5 pontos percentuais", "Quase não altera a probabilidade final."),
            ("Muito ligeiro", "0,5 a menos de 1,5 p.p.", "Sinal pequeno, mas mensurável."),
            ("Ligeiro", "1,5 a menos de 3 p.p.", "Ajuda a orientar sem decidir sozinho."),
            ("Moderado", "3 a menos de 7 p.p.", "Parte material da leitura do jogo."),
            ("Forte", "7 a menos de 12 p.p.", "Evidência com grande influência."),
            ("Muito forte", "12 p.p. ou mais", "O resultado depende fortemente desta família."),
        ],
        [1.35, 2.45, 3.25],
    )
    _heading(doc, "Ausência de dados e fatores não aplicáveis", 2)
    _bullet(doc, "Não aplicável significa que a situação não existe naquele jogo. Exemplo: um jogador de circuito principal sem partidas Challenger recentes.")
    _bullet(doc, "Sem dados significa que o sistema não conseguiu obter uma leitura factual utilizável.")
    _bullet(doc, "Nos dois casos o voto central é exatamente zero. A ausência pode alargar a incerteza, mas nunca favorece um jogador.")
    _bullet(doc, "Sem confronto direto é uma observação válida e neutra, não uma falha de recolha.")
    _body(
        doc,
        "No exemplo Cobolli contra Tiafoe, as linhas cinzentas são neutras: não reduzem a vantagem de Tiafoe "
        "nem acrescentam força a Cobolli. O exemplo completo é explicado no final do guia.",
        bold_lead="Aplicação prática  ",
    )

    _page_break(doc)
    _heading(doc, "Família Forma recente ajustada", 1)
    _body(
        doc,
        "Esta é uma das duas famílias principais. Procura responder a uma pergunta: quem está realmente "
        "a competir melhor agora, depois de considerar a qualidade dos adversários e o nível dos torneios? "
        "Não trata uma vitória Challenger como equivalente a uma vitória num Masters 1000.",
    )
    _table(
        doc,
        ["Subpeso", "O que mede", "Exemplo simples"],
        [
            ("Base estatística da família", "Ponto de partida aprendido no histórico. Não é um facto individual do jogo.", "Pode deslocar a família alguns décimos antes dos fatores do encontro."),
            ("Resultados recentes no circuito principal", "Saldo de vitórias e derrotas recentes no ATP ou WTA principal, com redução temporal.", "6 vitórias em 10 contra 3 em 10 favorece o primeiro jogador. Na versão atual o coeficiente direto é zero; fica auditado, mas não vota sozinho."),
            ("Competitividade no circuito principal", "Margem de jogos e capacidade de manter derrotas equilibradas em partidas principais.", "Perder 7 6 7 6 é melhor sinal competitivo do que perder 6 1 6 1."),
            ("Qualidade das vitórias", "Força dos adversários derrotados, com maior valor para vitórias recentes sobre jogadores fortes.", "Duas vitórias contra top 20 valem mais do que duas contra jogadores fora do top 150."),
            ("Resultados em nível ATP ou WTA inferior", "Desempenho em eventos abaixo do nível principal de referência.", "Uma boa campanha num ATP 250 não equivale a uma meia final de Masters 1000."),
            ("Competitividade em nível ATP ou WTA inferior", "Qualidade dos parciais e margens nesse nível inferior.", "Distingue uma campanha sólida de vitórias apertadas contra oposição fraca."),
            ("Resultados Challenger", "Saldo recente em Challengers, usado sobretudo no ATP.", "Uma sequência Challenger ajuda, mas recebe menos crédito do que a mesma sequência ATP."),
            ("Competitividade Challenger", "Margens e resistência nos jogos Challenger.", "Vitórias dominantes contam mais do que sucessivos jogos decididos no limite."),
            ("Qualidade das vitórias ajustada ao nível", "Combina vitória e categoria do torneio numa escala comum.", "Uma vitória num Masters 1000 recebe muito mais crédito do que uma vitória Challenger 75."),
            ("Mudança recente de nível competitivo", "Deteta descida recente para circuitos inferiores. Subir de nível nunca cria crédito artificial.", "Um antigo jogador ATP que passou a jogar Challengers é sinalizado. Atualmente é diagnóstico e não vota diretamente."),
        ],
        [2.0, 3.0, 2.05],
        header_fill="7A3E18",
    )
    _page_break(doc)
    _heading(doc, "Família Força estrutural", 1)
    _body(
        doc,
        "Esta é a família principal com maior coeficiente, sobretudo no WTA. Define o nível estrutural do "
        "jogador sem tratar o ranking atual como verdade absoluta. Ranking, pontos, estabilidade histórica, "
        "inatividade e regressos após lesão são analisados em conjunto.",
    )
    _table(
        doc,
        ["Subpeso", "O que mede", "Exemplo simples"],
        [
            ("Distância material de ranking", "Diferença de ranking depois de retirar uma zona neutra de 25 por cento na razão entre posições.", "Número 70 contra 80 pode ficar neutro; número 10 contra 50 produz vantagem material."),
            ("Ranking representativo", "Reduz a confiança no ranking atual quando ele difere muito do nível típico e é pouco estável.", "Um jogador ocasionalmente no top 40 por uma única semana recebe menos confiança do que alguém estável no top 40."),
            ("Diferença de pontos", "Compara os pontos oficiais numa escala logarítmica para distinguir diferenças reais dentro do mesmo intervalo de ranking.", "Número 100 com quase o dobro dos pontos do número 150 recebe vantagem estrutural adicional."),
            ("Ajuste do ranking durante o regresso", "Contrai o peso do ranking atual quando o jogador regressa de um hiato longo e ainda tem poucos jogos.", "Um antigo top 10 agora número 400 após lesão não é tratado automaticamente como um verdadeiro número 400."),
            ("Ajuste dos pontos durante o regresso", "Aplica a mesma prudência aos pontos, que podem estar artificialmente baixos após inatividade.", "Os pontos perdidos durante a lesão não apagam a carreira, mas também não restauram automaticamente o antigo nível."),
            ("Contexto de regresso após hiato", "Mede a distância entre o nível atual e o nível típico anterior, ponderada pela pouca evidência desde o regresso.", "Depois de dois jogos de regresso a incerteza é alta; após vinte jogos o ranking atual ganha mais autoridade."),
            ("Trajetória do ranking", "Observa se o ranking vem a subir ou a cair ao longo das semanas.", "Uma subida sustentada tem mais valor do que uma alteração isolada."),
            ("Inatividade", "Penaliza diferenças relevantes no tempo sem competir.", "Um jogador parado durante meses recebe maior fricção do que outro ativo."),
        ],
        [2.0, 3.0, 2.05],
    )
    _heading(doc, "Campos de contexto mostrados no relatório", 2)
    _table(
        doc,
        ["Campo", "Significado"],
        [
            ("Ranking atual", "Posição oficial na data do jogo."),
            ("Pontos atuais", "Pontos oficiais usados para diferenciar jogadores próximos no ranking."),
            ("Melhor ranking observado", "Melhor posição encontrada no histórico; é contexto, não voto automático."),
            ("Nível típico antes do hiato", "Mediana aproximada do ranking antes de uma paragem longa aplicável."),
            ("Jogos desde o regresso", "Quantidade de evidência competitiva acumulada após o hiato."),
            ("Confiança no ranking atual", "Grau em que o ranking atual é representativo e fiável."),
            ("Ranking típico 365 dias", "Nível habitual do jogador durante o último ano ativo."),
            ("Representatividade", "Combinação de persistência, proximidade ao nível típico e estabilidade."),
        ],
        [2.3, 4.75],
        header_fill="294A5F",
    )

    _heading(doc, "Família Superfície e condições", 1)
    _body(
        doc,
        "O modelo separa hard outdoor, hard indoor, terra batida e relva. Não mistura indoor e outdoor. "
        "Além da percentagem de vitórias, ajusta o nível dos torneios disputados: 70 por cento num Challenger "
        "não equivale automaticamente a 70 por cento em ATP 500 ou Masters 1000.",
    )
    _table(
        doc,
        ["Subpeso", "O que mede", "Exemplo simples"],
        [
            ("Carreira neste piso", "Percentagem de vitórias de carreira no piso exato, reduzida quando a amostra é curta.", "8 vitórias em 10 é aproximado de forma mais prudente do que 80 vitórias em 100."),
            ("Época anterior neste piso", "Desempenho na época anterior para captar continuidade recente.", "Uma boa época anterior em indoor ajuda, mas não domina a carreira inteira."),
            ("Época atual neste piso", "Desempenho na época corrente, com maior atualidade e controlo de amostra.", "6 vitórias em 7 no ano atual é forte, mas é reduzido se os adversários forem fracos."),
            ("Qualidade no piso na carreira", "Ajusta o histórico de carreira à categoria dos torneios e adversários.", "Resultados recorrentes em Masters 1000 superam resultados Challenger no mesmo piso."),
            ("Qualidade no piso na época anterior", "Repete o ajuste de nível apenas para a época anterior.", "Uma meia final de ATP 500 pesa mais do que várias vitórias num evento inferior."),
            ("Qualidade no piso na época atual", "Combina atualidade, piso e nível competitivo no ano corrente.", "Uma meia final recente de Masters 1000 indoor é evidência muito superior a uma boa campanha Challenger."),
        ],
        [2.1, 3.0, 1.95],
        header_fill="2F6B68",
    )
    _body(
        doc,
        "A família é relevante, mas permanece abaixo das duas principais. Na versão 13, se todas as famílias "
        "concordarem, a superfície pode reforçar o favorito; contudo, não pode ter impacto individual superior "
        "à principal mais forte. Se houver conflito, fica sujeita ao limite estrito do bloco secundário.",
        bold_lead="Regra de governação  ",
    )

    _page_break(doc)
    _heading(doc, "Família Matchup e confronto direto", 1)
    _body(
        doc,
        "O H2H não é contado como uma simples percentagem. A margem de vitórias é combinada com o número de "
        "confrontos, para que uma única partida tenha pouco peso e um padrão repetido ganhe autoridade.",
    )
    _table(
        doc,
        ["Elemento", "Como funciona", "Exemplo"],
        [
            ("Confronto direto global", "Compara vitórias e derrotas entre os jogadores.", "1 0 é um indício fraco; 6 0 é um padrão forte."),
            ("Confiabilidade da amostra", "Aumenta gradualmente com o número de encontros e evita saltos artificiais.", "7 3 em dez jogos tem muito mais força do que 2 1 em três."),
            ("Piso dos encontros", "É mostrado em detalhe e ajuda o utilizador a perceber a relevância contextual.", "Dois dos três jogos em hard são mais úteis para um novo jogo em hard."),
            ("Recência e detalhe", "O relatório lista data, torneio, piso, resultado e vencedor.", "Um H2H antigo pode ser interpretado com mais prudência pelo utilizador."),
            ("Ausência de H2H", "É uma observação neutra válida, com voto zero.", "Jogadores que nunca se defrontaram não perdem cobertura factual."),
        ],
        [1.75, 3.25, 2.05],
        header_fill="7A3E18",
    )
    _heading(doc, "Diferença entre ATP e WTA", 2)
    _body(
        doc,
        "No ATP é usada uma curva contínua de confiabilidade que cresce com a amostra. No WTA mantém-se a "
        "percentagem global reduzida por amostra enquanto o histórico prospetivo aumenta. Em ambos os casos, "
        "um H2H forte continua a ser uma família secundária e não substitui forma recente ou força estrutural.",
    )
    _body(
        doc,
        "Num Alcaraz contra Medvedev com 7 3 em dez encontros, o H2H mantém contribuição expressiva. A versão 13 "
        "não o elimina; apenas impede que outra secundária isolada, como superfície, ultrapasse a principal mais forte.",
        bold_lead="Exemplo prático  ",
    )

    _page_break(doc)
    _heading(doc, "Família Serviço e resposta", 1)
    _body(
        doc,
        "É a família com menor prioridade metodológica. Serve para descrever o perfil do matchup e confirmar "
        "ou contrariar sinais mais importantes. Os valores são reduzidos por amostra e adaptados ao piso exato.",
    )
    _table(
        doc,
        ["Subpeso", "O que mede", "Exemplo simples"],
        [
            ("Serviço no piso", "Diferença nos pontos de serviço ganhos no piso atual, com redução por amostra.", "Um grande servidor indoor pode ganhar vantagem específica nesse contexto."),
            ("Resposta no piso", "Diferença nos pontos de resposta ganhos no mesmo piso.", "Um excelente respondedor em terra batida pode neutralizar um servidor agressivo."),
            ("Serviço recente", "Desvio recente do serviço face ao nível habitual no piso.", "Um jogador a servir acima da sua média recebe sinal positivo moderado, não uma duplicação do histórico."),
            ("Resposta recente", "Desvio recente da resposta face ao nível habitual.", "Uma quebra recente de qualidade na resposta pode reduzir a vantagem esperada."),
        ],
        [1.8, 3.3, 1.95],
    )
    _body(
        doc,
        "No modelo ATP entram os quatro subpesos. No modelo WTA atual, a calibração reteve serviço e resposta "
        "no piso; os desvios recentes não recebem voto autónomo. Isto pode mudar apenas com nova calibração "
        "cronológica, nunca por decisão manual num jogo específico.",
    )

    _page_break(doc)
    _heading(doc, "Como os subpesos formam a fair odd", 1)
    _body(doc, "O cálculo segue esta ordem e o mercado não entra em nenhuma destas etapas:")
    _table(
        doc,
        ["Passo", "Operação", "Proteção metodológica"],
        [
            ("1", "Cada valor factual é limitado a intervalos históricos e normalizado.", "Evita que um valor extremo isolado domine."),
            ("2", "A amostra curta é aproximada de um valor neutro.", "Dez jogos não têm a mesma confiança que cem."),
            ("3", "Os subpesos ativos produzem a probabilidade da família.", "Não aplicável e sem dados têm voto zero."),
            ("4", "A probabilidade da família é convertida em força contínua e multiplicada pelo coeficiente da família.", "As duas principais têm maior autoridade base."),
            ("5", "A governação v13 limita secundárias em consenso ou conflito.", "Uma secundária isolada não domina a leitura."),
            ("6", "A soma é calibrada em jogos cronologicamente posteriores.", "A probabilidade final é testada fora da amostra de treino."),
            ("7", "Fair odd central é o inverso da probabilidade calibrada.", "O intervalo reflete erro histórico e cobertura."),
            ("8", "Só depois é comparada com a odd observada.", "O mercado nunca constrói a fair odd."),
        ],
        [0.55, 3.65, 2.85],
    )
    _heading(doc, "Exemplo numérico simples", 2)
    _body(
        doc,
        "Imagine que Forma recente e Força estrutural favorecem o jogador A, enquanto Serviço e resposta "
        "favorece B. O modelo não conta dois votos contra um. Usa a intensidade exata. Se as principais "
        "produzirem contribuições de 0,30 e 0,20, nenhuma secundária em conflito pode exceder 0,25 e o total "
        "das secundárias não pode exceder 0,50. A fair odd resulta da soma calibrada, não de uma votação simples.",
    )

    _page_break(doc)
    _heading(doc, "Como interpretar o exemplo Cobolli contra Tiafoe", 1)
    _body(
        doc,
        "O screenshot fornecido mostra uma vantagem moderada de Tiafoe na Forma recente ajustada. A leitura "
        "correta não é que todas as linhas tenham o mesmo peso.",
    )
    _bullet(doc, "Base estatística favorece Cobolli de forma pequena. É calibração histórica, não informação individual do encontro.")
    _bullet(doc, "Resultados recentes no circuito principal ficam sem vantagem material e, na versão atual, não têm voto direto autónomo.")
    _bullet(doc, "Competitividade no circuito principal favorece Tiafoe com impacto moderado.")
    _bullet(doc, "Qualidade das vitórias favorece Tiafoe com impacto moderado.")
    _bullet(doc, "As quatro linhas de nível inferior e Challenger são não aplicáveis e têm impacto zero.")
    _bullet(doc, "Qualidade das vitórias ajustada ao nível é o fator dominante da família e favorece Tiafoe.")
    _bullet(doc, "Mudança recente de nível competitivo fica neutra.")
    _body(
        doc,
        "A vantagem moderada da família é, portanto, coerente: vários sinais ativos apontam para Tiafoe e o "
        "mais importante dentro da família é a qualidade das vitórias ajustada ao nível. As linhas cinzentas "
        "não diluem nem reforçam essa vantagem.",
    )

    _page_break(doc)
    _heading(doc, "Limites e disciplina de utilização", 1)
    _bullet(doc, "A fair odd é uma estimativa, não uma certeza e não uma ordem automática de aposta.")
    _bullet(doc, "Uma grande diferença para o mercado exige revisão crítica da identidade do jogo, dados, cobertura e intensidade das famílias.")
    _bullet(doc, "O mercado serve como comparação posterior e alerta de plausibilidade, nunca como ingrediente da probabilidade.")
    _bullet(doc, "O histórico Guerra Selection anterior pertence a uma metodologia antiga e deve ser separado da nova fase.")
    _bullet(doc, "As conclusões sobre ROI e taxa de acerto devem usar apenas previsões congeladas antes do jogo.")
    _bullet(doc, "Pesos com coeficiente zero continuam visíveis para auditoria, mas não devem ser interpretados como voto oculto.")
    _heading(doc, "Resumo para decisão", 2)
    _table(
        doc,
        ["Pergunta", "Resposta curta"],
        [
            ("Quais são as famílias principais", "Forma recente ajustada e Força estrutural."),
            ("Qual é a secundária mais relevante", "Superfície e condições."),
            ("Quando o H2H ganha força", "Quando a amostra cresce e existe uma vantagem clara e repetida."),
            ("Qual é a família menos prioritária", "Serviço e resposta."),
            ("Dados ausentes favorecem alguém", "Não. O impacto central é zero."),
            ("O mercado altera a fair odd", "Não. Só é comparado depois."),
            ("Uma secundária pode dominar", "Não isoladamente. A versão 13 impõe limites por jogo."),
            ("As palavras ligeiro e forte entram no cálculo", "Não. O cálculo usa o valor contínuo exato."),
        ],
        [2.75, 4.3],
        header_fill="294A5F",
    )

    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Fenzobot  |  Guia das Famílias e Subpesos  |  Versão 13")
    _set_font(run, size=8.5, color=RGBColor(105, 105, 105))

    properties = doc.core_properties
    properties.title = "Fenzobot Guia das Famílias e Subpesos"
    properties.subject = "Manual de leitura das famílias e subpesos do modelo contextual"
    properties.author = "Fenzobot"
    properties.keywords = "Fenzobot, ténis, famílias, subpesos, fair odd"
    doc.save(OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    print(build())
