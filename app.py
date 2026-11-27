import hmac
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import streamlit as st
from fpdf import FPDF

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA E CONSTANTES
# =============================================================================
st.set_page_config(
    page_title="Portal Comercial CFS - Ecossistemas & Consulta FT",
    page_icon="🌐",
    layout="wide",
)

SHEET_ID = "1zTclMBgggOlYfrwRQRIRvSVAVOHUdOVPA4EB1VopcHI"
ABA_PRODUTOS = "Produtos"
ABA_GARANTIAS = "Garantias_Ativos"
LOGO_PATH = "logo_cfs.png"

COLUNAS_PRODUTOS = [
    "id_produto",
    "categoria",
    "linha",
    "produto",
    "estado_fisico",
    "limite_regulatorio",
    "composicao",
    "ft_revisao",
    "ft_data",
]

COLUNAS_GARANTIAS = [
    "id_produto",
    "produto",
    "ativo_padronizado",
    "operador",
    "valor_numerico",
    "unidade",
]

CATEGORIAS_OFICIAIS = [
    "AnOx Tradicionais",
    "Novamold",
    "Dresbond",
    "Salplus",
    "AnOx Naturais",
    "Outros",
]

ESPECIES_FABRICA = [
    "Ruminantes",
    "Aves",
    "Suínos",
    "Pet",
    "Aqua",
    "Outros",
]

PONTOS_FABRICA = [
    "Misturador",
    "Matéria-prima",
    "Produto acabado",
    "Outros",
]

PARES_DUPLA_DECLARACAO: List[Tuple[str, str]] = [
    ("Propionato de Cálcio", "Ácido Propiônico"),
    ("Formiato de Cálcio", "Ácido Fórmico"),
    ("Nitrogênio Total", "Polimetilcarbamida"),
]

SINERGISTAS = {"Ácido Cítrico", "Ácido Fosfórico", "EDTA"}

ECOSSISTEMAS_VALIDOS = {
    "portal",
    "consulta_ft",
    "fabrica_racao",
    "avicultura",
    "ffo_bovinos",
    "ffo_suinos",
}


# =============================================================================
# ESTILOS CSS (HUB DE CARDS E AJUSTES VISUAIS)
# =============================================================================
def aplicar_estilos_css() -> None:
    st.markdown(
        """
        <style>
        .portal-card {
            background: linear-gradient(145deg, #ffffff 0%, #f4f7fb 100%);
            border: 1px solid #d7e1ec;
            border-top: 4px solid #004a99;
            border-radius: 12px;
            padding: 18px 18px 14px 18px;
            min-height: 185px;
            box-shadow: 0 2px 8px rgba(15, 35, 65, 0.06);
            margin-bottom: 10px;
        }
        .portal-card-stub {
            border-top-color: #d97706;
        }
        .portal-card-ft {
            border-top-color: #0d9488;
        }
        .portal-title {
            font-size: 1.15rem;
            font-weight: 700;
            color: #0f2341;
            margin-bottom: 8px;
        }
        .portal-desc {
            font-size: 0.88rem;
            color: #4b5563;
            line-height: 1.45;
        }
        .obs-discreta {
            font-size: 0.80rem;
            font-style: italic;
            color: #6b7280;
            margin-top: -10px;
            margin-bottom: 10px;
            display: block;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# CAMADA DE ACESSO A DADOS (READ-ONLY GOOGLE SHEETS)
# =============================================================================
def obter_senha_app() -> str:
    try:
        return str(st.secrets.get("APP_PASSWORD", "cfs2026"))
    except Exception:
        return "cfs2026"


def montar_url_csv(nome_aba: str) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
        f"/gviz/tq?tqx=out:csv&sheet={quote(nome_aba)}"
    )


def _limpar_colunas_texto(df: pd.DataFrame) -> pd.DataFrame:
    df_limpo = df.copy()
    df_limpo.columns = [str(c).strip() for c in df_limpo.columns]
    for col in df_limpo.select_dtypes(include=["object"]).columns:
        df_limpo[col] = (
            df_limpo[col]
            .fillna("")
            .astype(str)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )
    return df_limpo


@st.cache_data(ttl=300, show_spinner="Sincronizando base de produtos e garantias...")
def carregar_base_normalizada() -> Tuple[pd.DataFrame, pd.DataFrame, str, Optional[str]]:
    horario_sync = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    try:
        df_prod = _limpar_colunas_texto(pd.read_csv(montar_url_csv(ABA_PRODUTOS)))
        df_gar = _limpar_colunas_texto(pd.read_csv(montar_url_csv(ABA_GARANTIAS)))

        faltantes_prod = [c for c in ["id_produto", "categoria", "produto"] if c not in df_prod.columns]
        faltantes_gar = [
            c
            for c in ["id_produto", "ativo_padronizado", "valor_numerico", "unidade"]
            if c not in df_gar.columns
        ]

        if faltantes_prod:
            return (
                pd.DataFrame(),
                pd.DataFrame(),
                horario_sync,
                f"Aba '{ABA_PRODUTOS}' sem colunas obrigatórias: {', '.join(faltantes_prod)}.",
            )
        if faltantes_gar:
            return (
                pd.DataFrame(),
                pd.DataFrame(),
                horario_sync,
                f"Aba '{ABA_GARANTIAS}' sem colunas obrigatórias: {', '.join(faltantes_gar)}.",
            )

        df_prod = df_prod[df_prod["id_produto"] != ""].copy()
        df_gar = df_gar[df_gar["id_produto"] != ""].copy()

        df_gar["valor_numerico"] = pd.to_numeric(
            df_gar["valor_numerico"].astype(str).str.replace(",", ".", regex=False),
            errors="coerce",
        )

        for col in COLUNAS_PRODUTOS:
            if col not in df_prod.columns:
                df_prod[col] = ""
        for col in COLUNAS_GARANTIAS:
            if col not in df_gar.columns:
                df_gar[col] = ""

        resumo_garantias = (
            df_gar.groupby("id_produto")
            .apply(formatar_resumo_garantias_df)
            .reset_index(name="garantias_resumo")
        )
        df_prod = df_prod.merge(resumo_garantias, on="id_produto", how="left")
        df_prod["garantias_resumo"] = df_prod["garantias_resumo"].fillna("Sem garantia declarada")

        df_prod = ordenar_portfolio(df_prod)
        return df_prod, df_gar, horario_sync, None

    except Exception as exc:
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            horario_sync,
            f"Falha ao conectar com a planilha base: {exc}. "
            "Verifique a conexão e clique em 'Atualizar Base'.",
        )


# =============================================================================
# FORMATAÇÃO BRASILEIRA & INPUTS SEM +/- (COM SALVAMENTO IMEDIATO)
# =============================================================================
def fmt_br(valor: float, casas: int = 2) -> str:
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def parse_numero_br(texto: str, padrao: float = 0.0, minimo: float = 0.0) -> float:
    if texto is None:
        return max(padrao, minimo)
    limpo = re.sub(r"[^\d,.-]", "", str(texto).strip())
    if not limpo:
        return max(padrao, minimo)
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif limpo.count(".") > 1:
        limpo = limpo.replace(".", "")
    try:
        val = float(limpo)
        return max(val, minimo)
    except ValueError:
        return max(padrao, minimo)


def input_numero_br(
    label: str,
    valor_atual: float,
    key: str,
    casas: int = 2,
    minimo: float = 0.0,
    placeholder: str = "",
    vazio_inicial: bool = False,
) -> float:
    txt_key = f"_txt_{key}"
    if txt_key not in st.session_state:
        if vazio_inicial and float(valor_atual) == 0.0:
            st.session_state[txt_key] = ""
        else:
            st.session_state[txt_key] = fmt_br(float(valor_atual), casas)
    digitado = st.text_input(label, key=txt_key, placeholder=placeholder)
    return parse_numero_br(digitado, padrao=0.0 if vazio_inicial else float(valor_atual), minimo=minimo)


def input_inteiro_br(
    label: str,
    valor_atual: int,
    key: str,
    minimo: int = 0,
    placeholder: str = "",
    vazio_inicial: bool = False,
) -> int:
    txt_key = f"_txt_{key}"
    if txt_key not in st.session_state:
        if vazio_inicial and int(valor_atual) == 0:
            st.session_state[txt_key] = ""
        else:
            st.session_state[txt_key] = fmt_br(float(valor_atual), 0)
    digitado = st.text_input(label, key=txt_key, placeholder=placeholder)
    padrao_calc = 0.0 if vazio_inicial else float(valor_atual)
    val = int(round(parse_numero_br(digitado, padrao=padrao_calc, minimo=float(minimo))))
    return max(val, minimo)


def obs_discreta(texto: str) -> None:
    st.markdown(f'<span class="obs-discreta">{texto}</span>', unsafe_allow_html=True)


def pdf_safe(texto: Any) -> str:
    s = str(texto or "").replace("—", "-").replace("–", "-").replace("•", "-")
    return s.encode("latin-1", "replace").decode("latin-1")


# =============================================================================
# CAMADA DE DOMÍNIO (GARANTIAS, PPM EM KG/TON, BALANÇO DE MASSA E PDF)
# =============================================================================
def formatar_valor_garantia(valor: float, unidade: str) -> str:
    if pd.isna(valor):
        return "-"
    if unidade.upper() == "UFC/G":
        return f"{valor:.1e} {unidade}"
    if unidade.lower() == "mg/kg":
        return f"{fmt_br(float(valor), 0)} {unidade}"
    return f"{fmt_br(float(valor), 2)}%"


def formatar_resumo_garantias_df(grupo: pd.DataFrame) -> str:
    partes: List[str] = []
    for _, row in grupo.iterrows():
        ativo = str(row.get("ativo_padronizado", "")).strip()
        operador = str(row.get("operador", "")).strip()
        val = row.get("valor_numerico")
        unidade = str(row.get("unidade", "")).strip()
        if not ativo:
            continue
        val_fmt = formatar_valor_garantia(val, unidade)
        prefixo = f"{operador} " if operador else ""
        partes.append(f"{ativo}: {prefixo}{val_fmt}")
    return " | ".join(partes)


def resumo_curto_ativo_pdf(id_produto: str, df_garantias: pd.DataFrame) -> str:
    gar = df_garantias[df_garantias["id_produto"] == id_produto]
    if gar.empty:
        return ""
    partes: List[str] = []
    for _, row in gar.iterrows():
        ativo = str(row.get("ativo_padronizado", "")).strip()
        val = row.get("valor_numerico")
        unidade = str(row.get("unidade", "")).strip()
        if not ativo or pd.isna(val):
            continue
        partes.append(f"{ativo} {formatar_valor_garantia(float(val), unidade)}")
    return ", ".join(partes[:3])


def ordenar_portfolio(df: pd.DataFrame) -> pd.DataFrame:
    def peso_ordem(row: pd.Series) -> int:
        cat = str(row.get("categoria", "")).strip()
        if cat in CATEGORIAS_OFICIAIS:
            return CATEGORIAS_OFICIAIS.index(cat) + 1
        texto = f"{row.get('linha', '')} {cat} {row.get('produto', '')}".lower()
        if "xtendra" in texto or "anox" in texto:
            return 1
        if "novamold" in texto or "propical" in texto:
            return 2
        if "dresbond" in texto:
            return 3
        if "salplus" in texto:
            return 4
        if "nasure" in texto or "natural" in texto:
            return 5
        return 6

    df_copia = df.copy()
    df_copia["_ordem"] = df_copia.apply(peso_ordem, axis=1)
    df_copia = df_copia.sort_values(by=["_ordem", "produto"]).drop(columns=["_ordem"])
    return df_copia.reset_index(drop=True)


def calcular_entrega_ativos_kg_ton(
    id_produto: str,
    dosagem_kg_ton: float,
    df_garantias: pd.DataFrame,
) -> Dict[str, Any]:
    gar_prod = df_garantias[df_garantias["id_produto"] == id_produto]
    if gar_prod.empty or dosagem_kg_ton <= 0:
        return {
            "detalhe_texto": "Sem garantia numérica aplicável" if gar_prod.empty else "Dosagem 0,000 kg/ton",
            "ppm_primarios": 0.0,
            "ppm_sinergistas": 0.0,
            "tem_ppm": False,
            "observacao_dupla": "",
        }

    ativos_presentes = set(gar_prod["ativo_padronizado"].dropna().tolist())
    ativos_excluidos_soma = set()
    notas_dupla: List[str] = []

    for excluido, mantido in PARES_DUPLA_DECLARACAO:
        if excluido in ativos_presentes and mantido in ativos_presentes:
            ativos_excluidos_soma.add(excluido)
            notas_dupla.append(f"{excluido} não somado por equivalência a {mantido}")

    detalhes: List[str] = []
    ppm_primarios = 0.0
    ppm_sinergistas = 0.0
    tem_ppm = False

    for _, row in gar_prod.iterrows():
        ativo = str(row["ativo_padronizado"]).strip()
        val = row["valor_numerico"]
        unidade = str(row["unidade"]).strip()
        if pd.isna(val):
            continue

        if unidade == "%":
            ppm_mol = dosagem_kg_ton * float(val) * 10.0
            tem_ppm = True
            detalhes.append(f"{ativo}: {fmt_br(ppm_mol, 1)} ppm")
            if ativo not in ativos_excluidos_soma:
                if ativo in SINERGISTAS:
                    ppm_sinergistas += ppm_mol
                else:
                    ppm_primarios += ppm_mol
        elif unidade.lower() == "mg/kg":
            ppm_mol = dosagem_kg_ton * (float(val) / 1000.0)
            tem_ppm = True
            detalhes.append(f"{ativo}: {fmt_br(ppm_mol, 3)} ppm")
            if ativo not in ativos_excluidos_soma:
                ppm_primarios += ppm_mol
        elif unidade.upper() == "UFC/G":
            ufc_g_substrato = (dosagem_kg_ton * float(val)) / 1000.0
            detalhes.append(f"{ativo}: {ufc_g_substrato:.2e} UFC/g")
        else:
            detalhes.append(f"{ativo}: {val} {unidade}")

    if ppm_primarios == 0.0 and ppm_sinergistas > 0.0:
        ppm_primarios = ppm_sinergistas
        ppm_sinergistas = 0.0

    return {
        "detalhe_texto": " | ".join(detalhes) if detalhes else "Não aplicável (%)",
        "ppm_primarios": ppm_primarios,
        "ppm_sinergistas": ppm_sinergistas,
        "tem_ppm": tem_ppm,
        "observacao_dupla": "; ".join(notas_dupla),
    }


def calcular_balanco_massa_aves(
    tipo_gatilho: str,
    aves_dia: float,
    dias_mes: int,
    racao_input: float,
    mp_input: float,
    consumo_ave: float,
    peso_ave: float,
    rend_mp_pv: float,
    rend_fv: float,
    rend_fps: float,
    rend_oleo: float,
) -> Tuple[float, Dict[str, float]]:
    if tipo_gatilho == "Aves Abatidas":
        aves_mes = max(aves_dia, 0.0) * max(dias_mes, 0)
        racao_calc = (aves_mes * consumo_ave) / 1000.0
        mp_calc = ((aves_mes * peso_ave) * (rend_mp_pv / 100.0)) / 1000.0
    elif tipo_gatilho == "Produção de Ração":
        racao_calc = max(racao_input, 0.0)
        aves_mes = (racao_calc * 1000.0) / consumo_ave if consumo_ave > 0 else 0.0
        mp_calc = ((aves_mes * peso_ave) * (rend_mp_pv / 100.0)) / 1000.0
    else:
        mp_calc = max(mp_input, 0.0)
        fator_mp = peso_ave * (rend_mp_pv / 100.0)
        aves_mes = (mp_calc * 1000.0) / fator_mp if fator_mp > 0 else 0.0
        racao_calc = (aves_mes * consumo_ave) / 1000.0

    volumes = {
        "Fábrica de Ração": racao_calc,
        "Matéria-Prima Bruta FFO": mp_calc,
        "Farinha de Vísceras (FV)": mp_calc * (rend_fv / 100.0),
        "Farinha de Penas (FPS)": mp_calc * (rend_fps / 100.0),
        "Óleo de Frango": mp_calc * (rend_oleo / 100.0),
    }
    return aves_mes, volumes


class PropostaCFSPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-24)
        self.set_draw_color(210, 215, 220)
        self.line(15, self.get_y(), 195, self.get_y())
        self.ln(3)
        y_base = self.get_y()

        self.set_font("Helvetica", "B", 8)
        self.set_text_color(100, 110, 120)
        self.set_xy(15, y_base + 3)
        self.cell(100, 5, "BRINGING SCIENCE TO EVERYDAY LIFE", ln=0)

        if os.path.exists(LOGO_PATH):
            try:
                self.image(LOGO_PATH, x=155, y=y_base, w=40)
                return
            except Exception:
                pass

        self.set_xy(125, y_base + 1)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(0, 74, 153)
        self.cell(70, 5, "CFS  Camlin Fine Sciences", align="R", ln=1)


def gerar_pdf_proposta(
    consultor_nome: str,
    consultor_email: str,
    consultor_telefone: str,
    cliente_nome: str,
    cliente_cnpj: str,
    cliente_contato: str,
    cliente_email: str,
    incoterm: str,
    destino: str,
    expedicao_dias: int,
    validade_str: str,
    pagamento: str,
    obs_gerais: str,
    modo_tecnico: bool,
    linhas_proposta: List[Dict[str, Any]],
) -> bytes:
    pdf = PropostaCFSPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=28)
    pdf.set_margins(15, 16, 15)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(15, 35, 65)
    pdf.cell(120, 9, pdf_safe("Proposta Comercial"), ln=0)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(90, 95, 105)
    pdf.cell(60, 9, pdf_safe(f"Emissão: {datetime.now().strftime('%d/%m/%Y')}"), align="R", ln=1)

    pdf.set_draw_color(0, 74, 153)
    pdf.set_line_width(0.6)
    pdf.line(15, pdf.get_y() + 1, 195, pdf.get_y() + 1)
    pdf.ln(7)

    y_info = pdf.get_y()

    pdf.set_xy(15, y_info)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(0, 74, 153)
    pdf.cell(85, 5, "FORNECEDOR", ln=1)
    pdf.set_x(15)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(85, 5, pdf_safe(consultor_nome or "Consultor CFS"), ln=1)
    pdf.set_x(15)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(80, 80, 80)
    contato_forn = " | ".join([x for x in [consultor_email, consultor_telefone] if x.strip()])
    pdf.multi_cell(85, 4.5, pdf_safe(contato_forn or "Camlin Fine Sciences"))
    y_fim_forn = pdf.get_y()

    pdf.set_xy(105, y_info)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(0, 74, 153)
    pdf.cell(90, 5, "CLIENTE", ln=1)
    pdf.set_x(105)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(90, 5, pdf_safe(cliente_nome or "Não especificado"), ln=1)
    pdf.set_x(105)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(80, 80, 80)
    linha_ac_partes = []
    if cliente_contato.strip():
        linha_ac_partes.append(f"A/C: {cliente_contato.strip()}")
    if cliente_email.strip():
        linha_ac_partes.append(cliente_email.strip())
    if cliente_cnpj.strip():
        linha_ac_partes.append(f"CNPJ: {cliente_cnpj.strip()}")
    pdf.multi_cell(90, 4.5, pdf_safe(" | ".join(linha_ac_partes) or "-"))
    y_fim_cli = pdf.get_y()

    pdf.set_y(max(y_fim_forn, y_fim_cli) + 8)

    col_preco = f"Preço {incoterm}"
    if modo_tecnico:
        headers = [
            "Produto / Descrição",
            "Dosagem",
            "Qtd. mensal",
            col_preco,
            "Custo/ton",
            "Observação / Aplicação",
        ]
        widths = [50, 22, 24, 24, 22, 38]
        aligns = ["L", "C", "R", "R", "R", "L"]
    else:
        headers = [
            "Produto / Descrição",
            "Quantidade mensal",
            col_preco,
            "Observação / Aplicação",
        ]
        widths = [64, 32, 32, 52]
        aligns = ["L", "R", "R", "L"]

    pdf.set_fill_color(15, 35, 65)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8.5)
    for h, w, al in zip(headers, widths, aligns):
        pdf.cell(w, 8, pdf_safe(h), border=0, align=al, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(30, 30, 30)
    pdf.set_draw_color(220, 225, 230)
    pdf.set_line_width(0.25)

    for idx_row, lp in enumerate(linhas_proposta):
        desc_prod = lp["produto_pdf"]
        qtd_str = f"{fmt_br(lp['qtd_mensal'], 0)} kg"
        preco_str = f"USD {fmt_br(lp['preco_kg'], 2)}/kg"
        obs_str = lp["obs_pdf"] or "-"

        if modo_tecnico:
            valores = [
                desc_prod,
                f"{fmt_br(lp['dosagem'], 3)} kg/t",
                qtd_str,
                preco_str,
                f"USD {fmt_br(lp['custo_ton'], 2)}",
                obs_str,
            ]
        else:
            valores = [desc_prod, qtd_str, preco_str, obs_str]

        line_h = 5.0
        max_lines = 1
        for val_txt, w in zip(valores, widths):
            linhas_calc = pdf.multi_cell(w - 2, line_h, pdf_safe(val_txt), split_only=True)
            max_lines = max(max_lines, len(linhas_calc))
        row_h = max(8.0, max_lines * line_h + 2.5)

        if pdf.get_y() + row_h > 265:
            pdf.add_page()

        x_start = 15.0
        y_start = pdf.get_y()
        if idx_row % 2 == 1:
            pdf.set_fill_color(246, 248, 251)
            pdf.rect(x_start, y_start, sum(widths), row_h, style="F")

        cur_x = x_start
        for val_txt, w, al in zip(valores, widths, aligns):
            pdf.set_xy(cur_x + 1, y_start + 1.2)
            pdf.multi_cell(w - 2, line_h, pdf_safe(val_txt), border=0, align=al)
            cur_x += w

        pdf.line(x_start, y_start + row_h, x_start + sum(widths), y_start + row_h)
        pdf.set_y(y_start + row_h)

    pdf.ln(8)

    pdf.set_font("Helvetica", "B", 9.5)
    pdf.set_text_color(15, 35, 65)
    pdf.cell(0, 6, pdf_safe("Condições Comerciais"), ln=1)
    pdf.ln(1)

    incoterm_full = f"{incoterm} - {destino}" if destino.strip() else incoterm
    condicoes = [
        ("Incoterm:", incoterm_full),
        ("Expedição:", f"{expedicao_dias} dias úteis"),
        ("Validade da proposta:", validade_str),
        ("Pagamento:", pagamento),
    ]
    for rotulo, valor in condicoes:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(50, 55, 65)
        pdf.cell(42, 5.5, pdf_safe(rotulo), ln=0)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 5.5, pdf_safe(valor), ln=1)

    if obs_gerais.strip():
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(70, 75, 85)
        pdf.cell(0, 5, pdf_safe("Observações Gerais:"), ln=1)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(60, 60, 60)
        pdf.multi_cell(0, 4.5, pdf_safe(obs_gerais.strip()))

    saida = pdf.output()
    return bytes(saida) if isinstance(saida, (bytes, bytearray)) else saida.encode("latin-1")


# =============================================================================
# GESTÃO DE ESTADO (SESSION STATE)
# =============================================================================
def inicializar_sessao(lista_produtos: List[str]) -> None:
    prod_inicial = lista_produtos[0] if lista_produtos else ""
    defaults: Dict[str, Any] = {
        "consultor_nome": "",
        "consultor_email": "",
        "consultor_telefone": "",
        "cliente_nome": "",
        "cliente_cnpj": "",
        "cliente_contato": "",
        "cliente_email": "",
        "crm_historico": [],
        "incoterm": "CIF",
        "destino": "",
        "expedicao_dias": 5,
        "validade_proposta": date.today() + timedelta(days=30),
        "pagamento": "30 dias",
        "obs_gerais_pdf": "",
        "aves_etapa": 0,
        "tipo_gatilho": "Aves Abatidas",
        "aves_dia": 50000.0,
        "dias_mes": 25,
        "racao_input": 7500.0,
        "mp_input": 3750.0,
        "consumo_ave": 5.0,
        "peso_ave": 3.0,
        "rend_mp_pv": 30.0,
        "rend_fv": 25.0,
        "rend_fps": 10.0,
        "rend_oleo": 12.67,
        "aves_next_id": 3,
        "fab_etapa": 0,
        "fab_misturadores": [
            {"id": 1, "capacidade_kg": 2000, "observacao": ""},
        ],
        "fab_next_mist_id": 2,
        "fab_especies": [
            {"id": 1, "especie": "", "volume": 0, "observacao": ""},
        ],
        "fab_next_esp_id": 2,
        "fab_cesta": [],
        "fab_next_cesta_id": 1,
        "bov_etapa": 0,
        "bov_mp_ton": 4000.0,
        "bov_rend_farinha": 26.0,
        "bov_rend_sebo": 14.0,
        "bov_rend_sangue": 4.0,
        "bov_next_id": 3,
        "sui_etapa": 0,
        "sui_mp_ton": 3000.0,
        "sui_rend_farinha": 24.0,
        "sui_rend_gordura": 15.0,
        "sui_rend_sangue": 4.5,
        "sui_next_id": 3,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if "aves_cesta" not in st.session_state:
        st.session_state.aves_cesta = [
            {
                "id": 1,
                "matriz": "Farinha de Vísceras (FV)",
                "produto": prod_inicial,
                "dosagem": 0.500,
                "observacao": "",
                "preco_kg": 15.00,
                "share": 100,
            },
            {
                "id": 2,
                "matriz": "Óleo de Frango",
                "produto": prod_inicial,
                "dosagem": 1.000,
                "observacao": "",
                "preco_kg": 18.00,
                "share": 100,
            },
        ]

    if "bov_cesta" not in st.session_state:
        st.session_state.bov_cesta = [
            {
                "id": 1,
                "matriz": "Farinha de Carne e Ossos (FCO)",
                "produto": prod_inicial,
                "dosagem": 0.500,
                "observacao": "",
                "preco_kg": 15.00,
                "share": 100,
            },
            {
                "id": 2,
                "matriz": "Sebo Bovino",
                "produto": prod_inicial,
                "dosagem": 0.800,
                "observacao": "",
                "preco_kg": 18.00,
                "share": 100,
            },
        ]

    if "sui_cesta" not in st.session_state:
        st.session_state.sui_cesta = [
            {
                "id": 1,
                "matriz": "Farinha de Carne e Ossos Suína",
                "produto": prod_inicial,
                "dosagem": 0.500,
                "observacao": "",
                "preco_kg": 15.00,
                "share": 100,
            },
            {
                "id": 2,
                "matriz": "Gordura / Óleo Suíno",
                "produto": prod_inicial,
                "dosagem": 1.000,
                "observacao": "",
                "preco_kg": 18.00,
                "share": 100,
            },
        ]


# =============================================================================
# NAVEGAÇÃO (SINCRONIZADA COM QUERY_PARAMS E SEM CONFLITO DE WIDGET KEY)
# =============================================================================
def navegar_para(ecossistema: str) -> None:
    destino = ecossistema if ecossistema in ECOSSISTEMAS_VALIDOS else "portal"
    st.session_state["ecossistema_ativo"] = destino
    try:
        st.query_params["eco"] = destino
    except Exception:
        pass
    st.rerun()


def mudar_etapa(chave_estado: str, nova_etapa: int) -> None:
    st.session_state[chave_estado] = nova_etapa
    st.rerun()


def renderizar_setas_etapa(chave_estado: str, etapa_atual: int, total_etapas: int) -> None:
    st.markdown("---")
    c_ant, _, c_prox = st.columns([1.4, 3.2, 1.4])
    with c_ant:
        if etapa_atual > 0:
            if st.button(
                "⬅️ Etapa Anterior",
                key=f"btn_ant_{chave_estado}_{etapa_atual}",
                use_container_width=True,
            ):
                mudar_etapa(chave_estado, etapa_atual - 1)
    with c_prox:
        if etapa_atual < total_etapas - 1:
            if st.button(
                "Próxima Etapa ➡️",
                key=f"btn_prox_{chave_estado}_{etapa_atual}",
                type="primary",
                use_container_width=True,
            ):
                mudar_etapa(chave_estado, etapa_atual + 1)


# =============================================================================
# COMPONENTES REUTILIZÁVEIS (CADASTRO CLIENTE, CONSULTA FT, PDF)
# =============================================================================
def renderizar_etapa_cadastro_cliente(
    ecossistema_label: str,
    resumo_volume_str: str,
    qtd_itens_cesta: int,
) -> None:
    st.header("Etapa 0: Cadastro Cliente & Consultor")

    col_forn, col_cli = st.columns(2)
    with col_forn:
        st.subheader("👔 Dados do Fornecedor (Consultor CFS)")
        st.session_state.consultor_nome = st.text_input(
            "Nome do Consultor:",
            value=st.session_state.consultor_nome,
            placeholder="Ítalo Ferreira",
            key=f"cons_nome_{ecossistema_label}",
        )
        st.session_state.consultor_email = st.text_input(
            "E-mail Corporativo:",
            value=st.session_state.consultor_email,
            placeholder="nome.sobrenome@camlinfs.com",
            key=f"cons_email_{ecossistema_label}",
        )
        st.session_state.consultor_telefone = st.text_input(
            "Telefone / WhatsApp:",
            value=st.session_state.consultor_telefone,
            placeholder="+55 (19) 99999-9999",
            key=f"cons_tel_{ecossistema_label}",
        )

    with col_cli:
        st.subheader("🏢 Dados do Cliente")
        st.session_state.cliente_nome = st.text_input(
            "Nome da Empresa / Cliente:",
            value=st.session_state.cliente_nome,
            placeholder="Ex.: Agroindustrial Brasil Ltda",
            key=f"cli_nome_{ecossistema_label}",
        )
        st.session_state.cliente_cnpj = st.text_input(
            "CNPJ:",
            value=st.session_state.cliente_cnpj,
            placeholder="00.000.000/0001-00",
            key=f"cli_cnpj_{ecossistema_label}",
        )
        st.session_state.cliente_contato = st.text_input(
            "Responsável (A/C):",
            value=st.session_state.cliente_contato,
            placeholder="Ex.: Thiago Soares",
            key=f"cli_cont_{ecossistema_label}",
        )
        st.session_state.cliente_email = st.text_input(
            "E-mail do Cliente:",
            value=st.session_state.cliente_email,
            placeholder="contato@empresa.com.br",
            key=f"cli_email_{ecossistema_label}",
        )

    st.markdown("---")
    st.subheader("🗂️ Histórico de Simulações Salvas na Sessão")
    if st.button(
        "💾 Salvar Simulação Atual no Histórico",
        type="primary",
        key=f"save_crm_{ecossistema_label}",
    ):
        if not st.session_state.cliente_nome.strip():
            st.warning("Preencha o Nome da Empresa antes de salvar.")
        else:
            st.session_state.crm_historico.append(
                {
                    "Data/Hora": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "Ecossistema": ecossistema_label,
                    "Consultor": st.session_state.consultor_nome.strip(),
                    "Cliente": st.session_state.cliente_nome.strip(),
                    "CNPJ": st.session_state.cliente_cnpj.strip(),
                    "Volumes": resumo_volume_str,
                    "Itens na Cesta": qtd_itens_cesta,
                }
            )
            st.success(f"Simulação para '{st.session_state.cliente_nome}' salva no histórico.")

    if st.session_state.crm_historico:
        df_crm = pd.DataFrame(st.session_state.crm_historico)
        st.dataframe(df_crm, use_container_width=True, hide_index=True)
        st.download_button(
            label="⬇️ Exportar Histórico (CSV)",
            data=df_crm.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"historico_cfs_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            key=f"csv_crm_{ecossistema_label}",
        )
    else:
        st.info("Nenhuma simulação salva nesta sessão ainda.")


def renderizar_catalogo_ft(
    df_produtos: pd.DataFrame,
    df_garantias: pd.DataFrame,
    prefixo_key: str,
    mostrar_limite_regulatorio: bool = True,
    expanded: bool = True,
) -> None:
    with st.expander("🔍 Consultar Catálogo de FTs e Filtrar por Princípio Ativo", expanded=expanded):
        cats_presentes = df_produtos["categoria"].dropna().unique().tolist()
        cat_disp = [c for c in CATEGORIAS_OFICIAIS if c in cats_presentes] + [
            c for c in sorted(cats_presentes) if c not in CATEGORIAS_OFICIAIS
        ]
        est_disp = sorted([e for e in df_produtos["estado_fisico"].dropna().unique().tolist() if e])
        ativos_disp = sorted([a for a in df_garantias["ativo_padronizado"].dropna().unique().tolist() if a])

        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            f_cat = st.multiselect(
                "Categoria / Linha:",
                options=cat_disp,
                default=cat_disp,
                key=f"{prefixo_key}_f_cat",
            )
        with col_f2:
            f_est = st.multiselect(
                "Estado Físico:",
                options=est_disp,
                default=est_disp,
                key=f"{prefixo_key}_f_est",
            )
        with col_f3:
            f_ativos = st.multiselect(
                "Conter Princípio(s) Ativo(s) (Match Exato):",
                options=ativos_disp,
                key=f"{prefixo_key}_f_atv",
            )

        df_ft_view = df_produtos.copy()
        if f_cat:
            df_ft_view = df_ft_view[df_ft_view["categoria"].isin(f_cat)]
        if f_est:
            df_ft_view = df_ft_view[df_ft_view["estado_fisico"].isin(f_est)]

        if f_ativos:
            ids_validos = set(df_ft_view["id_produto"].tolist())
            for atv in f_ativos:
                ids_com_ativo = set(
                    df_garantias.loc[
                        df_garantias["ativo_padronizado"] == atv, "id_produto"
                    ].tolist()
                )
                ids_validos &= ids_com_ativo
            df_ft_view = df_ft_view[df_ft_view["id_produto"].isin(ids_validos)]

        colunas_exibicao = [
            "categoria",
            "produto",
            "estado_fisico",
            "garantias_resumo",
        ]
        if mostrar_limite_regulatorio:
            colunas_exibicao.append("limite_regulatorio")
        colunas_exibicao.extend(["composicao", "ft_revisao", "ft_data"])

        if df_ft_view.empty:
            st.warning("Nenhum produto encontrado com a combinação de filtros selecionada.")
        else:
            st.dataframe(
                df_ft_view[colunas_exibicao].rename(
                    columns={
                        "categoria": "Categoria",
                        "produto": "Produto",
                        "estado_fisico": "Estado Físico",
                        "garantias_resumo": "Garantias Declaradas",
                        "limite_regulatorio": "Limite Regulatório",
                        "composicao": "Composição (Referência)",
                        "ft_revisao": "Revisão FT",
                        "ft_data": "Data FT",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )


def renderizar_bloco_pdf(
    prefixo_key: str,
    linhas_proposta_pdf: List[Dict[str, Any]],
) -> None:
    st.markdown("---")
    st.subheader("📄 Emissão de Proposta Comercial em PDF (Padrão CFS)")

    modo_proposta = st.radio(
        "Formato da Tabela no PDF:",
        [
            "Comercial Enxuta (Produto, Qtd., Preço, Observação)",
            "Técnica-Comercial (+ Dosagem kg/ton e Custo/ton USD)",
        ],
        horizontal=True,
        key=f"{prefixo_key}_modo_pdf",
    )
    eh_tecnico = modo_proposta.startswith("Técnica")

    cond1, cond2, cond3, cond4 = st.columns([1.2, 2.3, 1.5, 1.8])
    with cond1:
        st.session_state.incoterm = st.selectbox(
            "Incoterm:",
            options=["CIF", "FOB"],
            index=0 if st.session_state.incoterm == "CIF" else 1,
            key=f"{prefixo_key}_incoterm",
        )
    with cond2:
        st.session_state.destino = st.text_input(
            "Cidade / UF de Destino:",
            value=st.session_state.destino,
            placeholder="Ex.: Brasília/DF",
            key=f"{prefixo_key}_destino",
        )
    with cond3:
        st.session_state.expedicao_dias = input_inteiro_br(
            "Expedição (dias úteis):",
            int(st.session_state.expedicao_dias),
            key=f"{prefixo_key}_exp_dias",
            minimo=1,
        )
    with cond4:
        st.session_state.validade_proposta = st.date_input(
            "Validade da proposta:",
            value=st.session_state.validade_proposta,
            format="DD/MM/YYYY",
            key=f"{prefixo_key}_validade",
        )

    cond5, cond6 = st.columns([1.5, 3.5])
    with cond5:
        st.session_state.pagamento = st.text_input(
            "Condição de Pagamento:",
            value=st.session_state.pagamento,
            placeholder="Ex.: 30 dias",
            key=f"{prefixo_key}_pagto",
        )
    with cond6:
        st.session_state.obs_gerais_pdf = st.text_input(
            "Observações Gerais (opcional):",
            value=st.session_state.obs_gerais_pdf,
            placeholder="Ex.: Faturamento em BRL pela PTAX venda do dia anterior.",
            key=f"{prefixo_key}_obs_pdf",
        )

    pdf_bytes = gerar_pdf_proposta(
        consultor_nome=st.session_state.consultor_nome,
        consultor_email=st.session_state.consultor_email,
        consultor_telefone=st.session_state.consultor_telefone,
        cliente_nome=st.session_state.cliente_nome,
        cliente_cnpj=st.session_state.cliente_cnpj,
        cliente_contato=st.session_state.cliente_contato,
        cliente_email=st.session_state.cliente_email,
        incoterm=st.session_state.incoterm,
        destino=st.session_state.destino,
        expedicao_dias=int(st.session_state.expedicao_dias),
        validade_str=st.session_state.validade_proposta.strftime("%d/%m/%Y"),
        pagamento=st.session_state.pagamento,
        obs_gerais=st.session_state.obs_gerais_pdf,
        modo_tecnico=eh_tecnico,
        linhas_proposta=linhas_proposta_pdf,
    )

    nome_arq_cli = (st.session_state.cliente_nome or "cliente").strip().replace(" ", "_")
    st.download_button(
        label="⬇️ Baixar Proposta Comercial (.PDF)",
        data=pdf_bytes,
        file_name=f"Proposta_Comercial_{prefixo_key}_{nome_arq_cli}_{datetime.now().strftime('%Y%m%d')}.pdf",
        mime="application/pdf",
        type="primary",
        key=f"{prefixo_key}_dl_pdf",
    )


# =============================================================================
# TELA INICIAL: PORTAL DE ECOSSISTEMAS (HUB CENTRAL)
# =============================================================================
def renderizar_portal_hub(df_produtos: pd.DataFrame, df_garantias: pd.DataFrame) -> None:
    st.title("🌐 Portal Comercial & Técnico CFS")
    st.markdown("Selecione o ecossistema operacional ou acesse a consulta rápida de Fichas Técnicas:")
    st.markdown("")

    # Linha 1: Consulta de FTs -> Fábrica de Ração -> Avicultura
    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown(
            f"""
            <div class="portal-card portal-card-ft">
                <div class="portal-title">📄 Consulta de FTs</div>
                <div class="portal-desc">
                    Consulta rápida e independente de Fichas Técnicas por linha, estado físico
                    e match exato de princípios ativos ({len(df_produtos)} produtos | {len(df_garantias)} garantias).
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Consultar FTs ➡️", key="card_btn_ft", type="primary", use_container_width=True):
            navegar_para("consulta_ft")

    with col2:
        st.markdown(
            """
            <div class="portal-card">
                <div class="portal-title">🏭 Fábrica de Ração Comercial</div>
                <div class="portal-desc">
                    Cadastro dinâmico de misturadores, volumes por espécie (Ruminantes, Aves,
                    Suínos, Pet, Aqua, Outros), pontos críticos da planta, Share (%) e PDF.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Abrir Fábrica de Ração ➡️", key="card_btn_fab", type="primary", use_container_width=True):
            navegar_para("fabrica_racao")

    with col3:
        st.markdown(
            """
            <div class="portal-card">
                <div class="portal-title">🐔 Avicultura</div>
                <div class="portal-desc">
                    Balanço de massa completo da fábrica de ração ao abatedouro e graxaria
                    (FV, FPS e Óleo de Frango), cesta em kg/ton, ppm, Share (%) e proposta PDF.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Abrir Avicultura ➡️", key="card_btn_aves", type="primary", use_container_width=True):
            navegar_para("avicultura")

    st.markdown("")

    # Linha 2: FFO Bovinos -> FFO Suínos
    col4, col5, _ = st.columns([1, 1, 1])

    with col4:
        st.markdown(
            """
            <div class="portal-card portal-card-stub">
                <div class="portal-title">🐂 FFO Bovinos</div>
                <div class="portal-desc">
                    Dimensionamento de matéria-prima bovina e rendimentos de subprodutos
                    (Farinha de Carne e Ossos, Sebo Bovino), dosagem em kg/ton, ppm e proposta PDF.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Abrir FFO Bovinos ➡️", key="card_btn_bov", use_container_width=True):
            navegar_para("ffo_bovinos")

    with col5:
        st.markdown(
            """
            <div class="portal-card portal-card-stub">
                <div class="portal-title">🐷 FFO Suínos</div>
                <div class="portal-desc">
                    Dimensionamento de matéria-prima suína e rendimentos de farinha e gordura
                    suína, montagem de cesta em kg/ton, entrega em ppm e proposta PDF.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("Abrir FFO Suínos ➡️", key="card_btn_sui", use_container_width=True):
            navegar_para("ffo_suinos")


# =============================================================================
# ECOSSISTEMA 1: AVICULTURA
# =============================================================================
def renderizar_ecossistema_avicultura(
    df_produtos: pd.DataFrame,
    df_garantias: pd.DataFrame,
    lista_produtos: List[str],
    mapa_produtos: Dict[str, Any],
) -> None:
    st.title("🐔 Ecossistema Comercial - Avicultura")

    aves_mes, volumes = calcular_balanco_massa_aves(
        tipo_gatilho=st.session_state.tipo_gatilho,
        aves_dia=float(st.session_state.aves_dia),
        dias_mes=int(st.session_state.dias_mes),
        racao_input=float(st.session_state.racao_input),
        mp_input=float(st.session_state.mp_input),
        consumo_ave=float(st.session_state.consumo_ave),
        peso_ave=float(st.session_state.peso_ave),
        rend_mp_pv=float(st.session_state.rend_mp_pv),
        rend_fv=float(st.session_state.rend_fv),
        rend_fps=float(st.session_state.rend_fps),
        rend_oleo=float(st.session_state.rend_oleo),
    )

    etapas = [
        "0. Cadastro Cliente",
        "1. Cálculo de Produção de Ração & FFO",
        "2. Produtos & Dosagens",
        "3. Faturamento & Proposta",
    ]
    etapa_idx = int(st.session_state.aves_etapa)
    escolha = st.radio(
        "Navegação das Etapas:",
        options=etapas,
        index=etapa_idx,
        horizontal=True,
        key="radio_aves_etapa",
    )
    if etapas.index(escolha) != etapa_idx:
        st.session_state.aves_etapa = etapas.index(escolha)
        st.rerun()

    st.markdown("---")

    # ETAPA 0
    if st.session_state.aves_etapa == 0:
        resumo_vol = (
            f"Ração: {fmt_br(volumes['Fábrica de Ração'], 1)} t | "
            f"MP FFO: {fmt_br(volumes['Matéria-Prima Bruta FFO'], 1)} t"
        )
        renderizar_etapa_cadastro_cliente("Avicultura", resumo_vol, len(st.session_state.aves_cesta))
        renderizar_setas_etapa("aves_etapa", 0, 4)

    # ETAPA 1
    elif st.session_state.aves_etapa == 1:
        st.header("Etapa 1: Cálculo de Produção de Ração & FFO")
        if st.session_state.cliente_nome:
            st.info(f"👤 **Cliente Ativo:** {st.session_state.cliente_nome}")

        opcoes_gatilho = ["Aves Abatidas", "Produção de Ração", "Matéria-Prima FFO Recebida"]
        st.session_state.tipo_gatilho = st.radio(
            "Qual dado de partida você tem?",
            opcoes_gatilho,
            index=opcoes_gatilho.index(st.session_state.tipo_gatilho),
            horizontal=True,
            key="aves_gatilho_radio",
        )

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("🎯 Entrada do Gatilho Principal")
            if st.session_state.tipo_gatilho == "Aves Abatidas":
                st.session_state.aves_dia = input_numero_br(
                    "Abate Diário (aves/dia):",
                    float(st.session_state.aves_dia),
                    key="aves_dia_in",
                    casas=0,
                    minimo=1.0,
                )
                st.session_state.dias_mes = input_inteiro_br(
                    "Dias de Operação / Mês:",
                    int(st.session_state.dias_mes),
                    key="aves_dias_mes_in",
                    minimo=1,
                )
            elif st.session_state.tipo_gatilho == "Produção de Ração":
                st.session_state.racao_input = input_numero_br(
                    "Volume de Ração Produzida (ton/mês):",
                    float(st.session_state.racao_input),
                    key="aves_racao_in",
                    casas=1,
                    minimo=1.0,
                )
            else:
                st.session_state.mp_input = input_numero_br(
                    "Matéria-Prima Bruta Recebida na FFO (ton/mês):",
                    float(st.session_state.mp_input),
                    key="aves_mp_in",
                    casas=1,
                    minimo=1.0,
                )

        with col2:
            with st.expander("⚙️ Índices Zootécnicos e Industriais", expanded=False):
                p_c1, p_c2 = st.columns(2)
                with p_c1:
                    st.session_state.consumo_ave = input_numero_br(
                        "Consumo Ração/Ave (kg):",
                        float(st.session_state.consumo_ave),
                        key="aves_cons_ave",
                        casas=2,
                        minimo=0.1,
                    )
                    obs_discreta("Consumo total de ração pela ave até o abate.")

                    st.session_state.peso_ave = input_numero_br(
                        "Peso Vivo Médio (kg):",
                        float(st.session_state.peso_ave),
                        key="aves_peso_ave",
                        casas=2,
                        minimo=0.1,
                    )
                    obs_discreta("Peso vivo médio da ave no momento do abate.")

                    st.session_state.rend_mp_pv = input_numero_br(
                        "Rendimento MP s/ PV (%):",
                        float(st.session_state.rend_mp_pv),
                        key="aves_rend_mp",
                        casas=2,
                        minimo=0.1,
                    )
                    obs_discreta("Proporção do PV que é destinado na forma de matéria-prima para FFO.")

                with p_c2:
                    st.session_state.rend_fv = input_numero_br(
                        "Rendimento FV s/ MP (%):",
                        float(st.session_state.rend_fv),
                        key="aves_rend_fv",
                        casas=2,
                        minimo=0.1,
                    )
                    obs_discreta("Proporção da MP que é convertida em farinha de vísceras.")

                    st.session_state.rend_fps = input_numero_br(
                        "Rendimento FPS s/ MP (%):",
                        float(st.session_state.rend_fps),
                        key="aves_rend_fps",
                        casas=2,
                        minimo=0.1,
                    )
                    obs_discreta("Proporção da MP que é convertida em farinha de penas e sangue.")

                    st.session_state.rend_oleo = input_numero_br(
                        "Rendimento Óleo s/ MP (%):",
                        float(st.session_state.rend_oleo),
                        key="aves_rend_oleo",
                        casas=2,
                        minimo=0.1,
                    )
                    obs_discreta("Proporção da MP que é convertida em óleo de aves.")

        aves_mes, volumes = calcular_balanco_massa_aves(
            tipo_gatilho=st.session_state.tipo_gatilho,
            aves_dia=float(st.session_state.aves_dia),
            dias_mes=int(st.session_state.dias_mes),
            racao_input=float(st.session_state.racao_input),
            mp_input=float(st.session_state.mp_input),
            consumo_ave=float(st.session_state.consumo_ave),
            peso_ave=float(st.session_state.peso_ave),
            rend_mp_pv=float(st.session_state.rend_mp_pv),
            rend_fv=float(st.session_state.rend_fv),
            rend_fps=float(st.session_state.rend_fps),
            rend_oleo=float(st.session_state.rend_oleo),
        )

        st.markdown("---")
        st.success(
            f"📊 **Painel de Volumes Estimados "
            f"(Equivalente a {fmt_br(aves_mes, 0)} aves/mês):**"
        )
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Ração Produzida", f"{fmt_br(volumes['Fábrica de Ração'], 1)} ton")
        m2.metric("Matéria-Prima FFO", f"{fmt_br(volumes['Matéria-Prima Bruta FFO'], 1)} ton")
        m3.metric("Farinha Vísceras (FV)", f"{fmt_br(volumes['Farinha de Vísceras (FV)'], 1)} ton")
        m4.metric("Farinha Penas (FPS)", f"{fmt_br(volumes['Farinha de Penas (FPS)'], 1)} ton")
        m5.metric("Óleo de Frango", f"{fmt_br(volumes['Óleo de Frango'], 1)} ton")

        renderizar_setas_etapa("aves_etapa", 1, 4)

    # ETAPA 2
    elif st.session_state.aves_etapa == 2:
        st.header("Etapa 2: Produtos & Dosagens")
        if st.session_state.cliente_nome:
            st.info(f"👤 **Cliente Ativo:** {st.session_state.cliente_nome}")

        renderizar_catalogo_ft(
            df_produtos,
            df_garantias,
            prefixo_key="aves",
            mostrar_limite_regulatorio=True,
            expanded=True,
        )

        st.markdown("---")
        st.subheader("🛒 Cesta de Tratamento (Dosagem em kg/ton)")

        itens_remover: List[int] = []
        itens_duplicar: List[Dict[str, Any]] = []
        resumo_cesta: List[Dict[str, Any]] = []

        for idx, item in enumerate(st.session_state.aves_cesta):
            c1, c2, c3, c4, c5, c6 = st.columns([2.2, 2.8, 1.5, 2.5, 1.0, 0.6])
            with c1:
                lista_mat = list(volumes.keys())
                mat_idx = lista_mat.index(item["matriz"]) if item["matriz"] in lista_mat else 0
                item["matriz"] = st.selectbox(
                    f"Matriz #{idx + 1}:",
                    options=lista_mat,
                    index=mat_idx,
                    key=f"aves_mat_{item['id']}",
                )
            with c2:
                prod_idx = lista_produtos.index(item["produto"]) if item["produto"] in lista_produtos else 0
                item["produto"] = st.selectbox(
                    f"Produto #{idx + 1}:",
                    options=lista_produtos,
                    index=prod_idx,
                    key=f"aves_prod_{item['id']}",
                )
            with c3:
                item["dosagem"] = input_numero_br(
                    f"kg/ton #{idx + 1}:",
                    float(item["dosagem"]),
                    key=f"aves_dose_{item['id']}",
                    casas=3,
                    minimo=0.0,
                )
            with c4:
                item["observacao"] = st.text_input(
                    f"Observação #{idx + 1}:",
                    value=str(item.get("observacao", "")),
                    placeholder="Ex.: Ponto de dosagem, qual linha, especificidade, etc.",
                    key=f"aves_obs_{item['id']}",
                )
            with c5:
                st.write("")
                st.write("")
                if st.button("➕ Dup", key=f"aves_dup_{item['id']}", use_container_width=True):
                    itens_duplicar.append(item.copy())
            with c6:
                st.write("")
                st.write("")
                if len(st.session_state.aves_cesta) > 1:
                    if st.button("🗑️", key=f"aves_del_{item['id']}", use_container_width=True):
                        itens_remover.append(item["id"])

            vol_base = float(volumes.get(item["matriz"], 0.0))
            consumo_linha_kg = vol_base * float(item["dosagem"])

            info_p = mapa_produtos.get(item["produto"], {})
            id_prod = str(info_p.get("id_produto", ""))
            est_fisico = str(info_p.get("estado_fisico", ""))
            comp_str = str(info_p.get("composicao", ""))
            limite_reg = str(info_p.get("limite_regulatorio", ""))
            rev_ft = str(info_p.get("ft_revisao", ""))

            entrega = calcular_entrega_ativos_kg_ton(id_prod, float(item["dosagem"]), df_garantias)
            nota_dupla = f" *(Nota: {entrega['observacao_dupla']})*" if entrega["observacao_dupla"] else ""
            st.caption(
                f"📌 **{item['produto']} ({est_fisico} | {rev_ft})** | "
                f"**Entrega por Molécula:** {entrega['detalhe_texto']}{nota_dupla} | "
                f"**Limite Reg.:** {limite_reg} | **Composição:** {comp_str}"
            )
            st.markdown("---")

            resumo_cesta.append(
                {
                    "Ponto": idx + 1,
                    "Matriz Aplicada": item["matriz"],
                    "Volume Matriz (ton/mês)": fmt_br(vol_base, 1),
                    "Produto Comercial": item["produto"],
                    "Estado Físico": est_fisico,
                    "Dosagem (kg/ton)": fmt_br(float(item["dosagem"]), 3),
                    "Entrega por Molécula": entrega["detalhe_texto"],
                    "Ativos Primários (ppm)": (
                        fmt_br(entrega["ppm_primarios"], 2) if entrega["tem_ppm"] else "N/A"
                    ),
                    "Observação": item["observacao"],
                    "Consumo Mensal (kg)": fmt_br(consumo_linha_kg, 2),
                    "_consumo_num": consumo_linha_kg,
                }
            )

        if itens_duplicar:
            for it in itens_duplicar:
                novo_item = it.copy()
                novo_item["id"] = st.session_state.aves_next_id
                st.session_state.aves_cesta.append(novo_item)
                st.session_state.aves_next_id += 1
            st.rerun()

        if itens_remover:
            st.session_state.aves_cesta = [
                it for it in st.session_state.aves_cesta if it["id"] not in itens_remover
            ]
            st.rerun()

        if st.button("➕ Adicionar Nova Linha de Tratamento", key="aves_add_linha"):
            st.session_state.aves_cesta.append(
                {
                    "id": st.session_state.aves_next_id,
                    "matriz": "Fábrica de Ração",
                    "produto": lista_produtos[0] if lista_produtos else "",
                    "dosagem": 0.500,
                    "observacao": "",
                    "preco_kg": 15.00,
                    "share": 100,
                }
            )
            st.session_state.aves_next_id += 1
            st.rerun()

        df_resumo = pd.DataFrame(resumo_cesta)
        st.subheader("📋 Quadro Consolidado de Consumo e Entrega em ppm")
        st.dataframe(
            df_resumo.drop(columns=["_consumo_num"]),
            use_container_width=True,
            hide_index=True,
        )

        total_kg_geral = float(df_resumo["_consumo_num"].sum()) if not df_resumo.empty else 0.0
        st.success(f"📦 **Volume Físico Total Estimado na Conta:** {fmt_br(total_kg_geral, 2)} kg / mês")

        renderizar_setas_etapa("aves_etapa", 2, 4)

    # ETAPA 3
    elif st.session_state.aves_etapa == 3:
        st.header("Etapa 3: Faturamento & Proposta (US$)")
        if st.session_state.cliente_nome:
            st.info(
                f"👤 **Cliente Ativo:** {st.session_state.cliente_nome} "
                f"(CNPJ: {st.session_state.cliente_cnpj or 'N/A'})"
            )

        linhas_financeiro: List[Dict[str, Any]] = []
        linhas_proposta_pdf: List[Dict[str, Any]] = []
        tot_vol_fat = 0.0
        tot_fat_mensal = 0.0

        for idx, item in enumerate(st.session_state.aves_cesta):
            vol_base = float(volumes.get(item["matriz"], 0.0))
            dosagem = float(item["dosagem"])
            consumo_kg_100 = vol_base * dosagem

            info_p = mapa_produtos.get(item["produto"], {})
            id_prod = str(info_p.get("id_produto", ""))
            entrega = calcular_entrega_ativos_kg_ton(id_prod, dosagem, df_garantias)
            ativos_curto = resumo_curto_ativo_pdf(id_prod, df_garantias)

            c_fin1, c_fin2, c_fin3, c_fin4 = st.columns([3, 2, 2, 3])
            with c_fin1:
                st.markdown(f"**{idx + 1}. {item['produto']}** *(em {item['matriz']})*")
                st.caption(
                    f"Dosagem: {fmt_br(dosagem, 3)} kg/ton | {entrega['detalhe_texto']} | "
                    f"Obs: {item.get('observacao') or 'N/A'}"
                )
            with c_fin2:
                item["preco_kg"] = input_numero_br(
                    f"Preço US$/kg (#{idx + 1}):",
                    float(item.get("preco_kg", 15.0)),
                    key=f"aves_preco_{item['id']}",
                    casas=2,
                    minimo=0.0,
                )
            with c_fin3:
                item["share"] = st.slider(
                    f"Share % (#{idx + 1}):",
                    min_value=10,
                    max_value=100,
                    value=int(item.get("share", 100)),
                    step=10,
                    key=f"aves_share_{item['id']}",
                )

            preco_kg = float(item["preco_kg"])
            share = int(item["share"])
            consumo_real_kg = consumo_kg_100 * (share / 100.0)
            faturamento_item = consumo_real_kg * preco_kg
            custo_ton_tratada = dosagem * preco_kg

            tot_vol_fat += consumo_real_kg
            tot_fat_mensal += faturamento_item

            with c_fin4:
                st.metric(
                    label=f"Faturamento Item #{idx + 1}",
                    value=f"US$ {fmt_br(faturamento_item, 2)} /mês",
                    delta=f"Custo Tratamento: US$ {fmt_br(custo_ton_tratada, 2)} /ton",
                )
            st.markdown("---")

            linhas_financeiro.append(
                {
                    "Matriz": item["matriz"],
                    "Produto": item["produto"],
                    "Dosagem (kg/ton)": fmt_br(dosagem, 3),
                    "Entrega por Molécula": entrega["detalhe_texto"],
                    "Observação": item.get("observacao", ""),
                    "Custo Tratamento (US$/ton)": fmt_br(custo_ton_tratada, 2),
                    "Share (%)": f"{share}%",
                    "Volume Faturado (kg/mês)": fmt_br(consumo_real_kg, 2),
                    "Preço Unitário (US$/kg)": fmt_br(preco_kg, 2),
                    "Faturamento Mensal (US$)": fmt_br(faturamento_item, 2),
                    "Faturamento Anual (US$)": fmt_br(faturamento_item * 12.0, 2),
                }
            )

            nome_pdf = f"{item['produto']} ({ativos_curto})" if ativos_curto else item["produto"]
            linhas_proposta_pdf.append(
                {
                    "produto_pdf": nome_pdf,
                    "dosagem": dosagem,
                    "qtd_mensal": consumo_real_kg,
                    "preco_kg": preco_kg,
                    "custo_ton": custo_ton_tratada,
                    "obs_pdf": item.get("observacao", "").strip() or item["matriz"],
                }
            )

        df_fin = pd.DataFrame(linhas_financeiro)
        st.subheader("💼 Resumo Executivo da Conta (US$)")
        st.dataframe(df_fin, use_container_width=True, hide_index=True)

        r1, r2, r3 = st.columns(3)
        r1.metric("Volume Total Faturado (com Share)", f"{fmt_br(tot_vol_fat, 1)} kg/mês")
        r2.metric("Faturamento Mensal Consolidado", f"US$ {fmt_br(tot_fat_mensal, 2)}")
        r3.metric("Potencial Anualizado da Conta", f"US$ {fmt_br(tot_fat_mensal * 12.0, 2)}")

        renderizar_bloco_pdf("Avicultura", linhas_proposta_pdf)
        renderizar_setas_etapa("aves_etapa", 3, 4)


# =============================================================================
# ECOSSISTEMA 2: FÁBRICA DE RAÇÃO COMERCIAL
# =============================================================================
def sincronizar_especies_cesta_fabrica(lista_produtos: List[str]) -> None:
    """Carrega na cesta apenas espécies com nome selecionado e volume > 0."""
    especies_validas = [
        e
        for e in st.session_state.fab_especies
        if str(e.get("especie", "")).strip() and int(e.get("volume", 0)) > 0
    ]
    ids_presentes_na_cesta = {it.get("esp_id") for it in st.session_state.fab_cesta}
    mapa_esp_atual = {e["id"]: e["especie"] for e in especies_validas}

    for it in st.session_state.fab_cesta:
        eid = it.get("esp_id")
        if eid in mapa_esp_atual:
            it["especie"] = mapa_esp_atual[eid]

    prod_padrao = lista_produtos[0] if lista_produtos else ""
    for esp in especies_validas:
        if esp["id"] not in ids_presentes_na_cesta:
            st.session_state.fab_cesta.append(
                {
                    "id": st.session_state.fab_next_cesta_id,
                    "esp_id": esp["id"],
                    "especie": esp["especie"],
                    "ponto": "Misturador",
                    "produto": prod_padrao,
                    "dosagem": 0.000,
                    "observacao": "",
                    "preco_kg": 0.00,
                    "share": 100,
                }
            )
            st.session_state.fab_next_cesta_id += 1


def renderizar_ecossistema_fabrica_racao(
    df_produtos: pd.DataFrame,
    df_garantias: pd.DataFrame,
    lista_produtos: List[str],
    mapa_produtos: Dict[str, Any],
) -> None:
    st.title("🏭 Ecossistema Comercial - Fábricas de Ração")

    sincronizar_especies_cesta_fabrica(lista_produtos)

    etapas = [
        "0. Cadastro Cliente",
        "1. Produção",
        "2. Produtos & Dosagens",
        "3. Faturamento & Proposta",
    ]
    etapa_idx = int(st.session_state.fab_etapa)
    escolha = st.radio(
        "Navegação das Etapas:",
        options=etapas,
        index=etapa_idx,
        horizontal=True,
        key="radio_fab_etapa",
    )
    if etapas.index(escolha) != etapa_idx:
        st.session_state.fab_etapa = etapas.index(escolha)
        st.rerun()

    st.markdown("---")

    vol_por_especie: Dict[str, int] = {}
    for esp in st.session_state.fab_especies:
        nome_e = str(esp.get("especie", "")).strip()
        vol_e = int(esp.get("volume", 0))
        if nome_e and vol_e > 0:
            vol_por_especie[nome_e] = vol_por_especie.get(nome_e, 0) + vol_e
    vol_total_fabrica = sum(vol_por_especie.values())
    vol_por_especie["Total Fábrica de Ração"] = vol_total_fabrica

    # ETAPA 0
    if st.session_state.fab_etapa == 0:
        resumo_vol = f"Total Fábrica: {fmt_br(float(vol_total_fabrica), 0)} ton/mês"
        renderizar_etapa_cadastro_cliente("Fabrica_Racao", resumo_vol, len(st.session_state.fab_cesta))
        renderizar_setas_etapa("fab_etapa", 0, 4)

    # ETAPA 1
    elif st.session_state.fab_etapa == 1:
        st.header("Etapa 1: Produção")
        if st.session_state.cliente_nome:
            st.info(f"👤 **Cliente Ativo:** {st.session_state.cliente_nome}")

        st.subheader("⚙️ Misturadores da Fábrica")
        mist_remover: List[int] = []
        for idx, mist in enumerate(st.session_state.fab_misturadores):
            cm1, cm2, cm3 = st.columns([2.0, 4.5, 0.7])
            with cm1:
                mist["capacidade_kg"] = input_inteiro_br(
                    f"Misturador #{idx + 1} - Capacidade (kg/batelada):",
                    int(mist["capacidade_kg"]),
                    key=f"fab_mist_cap_{mist['id']}",
                    minimo=0,
                )
            with cm2:
                mist["observacao"] = st.text_input(
                    f"Observação Misturador #{idx + 1}:",
                    value=str(mist.get("observacao", "")),
                    placeholder="Ex.: Linha peletizada, tempo de mistura 4 min",
                    key=f"fab_mist_obs_{mist['id']}",
                )
            with cm3:
                st.write("")
                st.write("")
                if len(st.session_state.fab_misturadores) > 1:
                    if st.button("🗑️", key=f"fab_del_mist_{mist['id']}", use_container_width=True):
                        mist_remover.append(mist["id"])

        if mist_remover:
            st.session_state.fab_misturadores = [
                m for m in st.session_state.fab_misturadores if m["id"] not in mist_remover
            ]
            st.rerun()

        if st.button("➕ Adicionar misturador", key="fab_add_mist"):
            st.session_state.fab_misturadores.append(
                {
                    "id": st.session_state.fab_next_mist_id,
                    "capacidade_kg": 1000,
                    "observacao": "",
                }
            )
            st.session_state.fab_next_mist_id += 1
            st.rerun()

        cap_total_batelada = sum(int(m["capacidade_kg"]) for m in st.session_state.fab_misturadores)
        st.caption(
            f"Total de misturadores: **{len(st.session_state.fab_misturadores)}** | "
            f"Capacidade somada por batelada: **{fmt_br(float(cap_total_batelada), 0)} kg**"
        )

        st.markdown("---")

        st.subheader("🌾 Volumes por Espécie (ton/mês)")
        opcoes_esp_com_vazio = [""] + ESPECIES_FABRICA
        esp_remover: List[int] = []
        for idx, esp in enumerate(st.session_state.fab_especies):
            ce1, ce2, ce3, ce4 = st.columns([2.2, 1.8, 3.3, 0.7])
            with ce1:
                esp_atual = str(esp.get("especie", ""))
                esp_idx = (
                    opcoes_esp_com_vazio.index(esp_atual)
                    if esp_atual in opcoes_esp_com_vazio
                    else 0
                )
                esp["especie"] = st.selectbox(
                    f"Espécie #{idx + 1}:",
                    options=opcoes_esp_com_vazio,
                    index=esp_idx,
                    format_func=lambda x: "Selecione a espécie..." if x == "" else x,
                    key=f"fab_esp_sel_{esp['id']}",
                )
            with ce2:
                esp["volume"] = input_inteiro_br(
                    f"Volume (ton/mês) #{idx + 1}:",
                    int(esp.get("volume", 0)),
                    key=f"fab_esp_vol_{esp['id']}",
                    minimo=0,
                    placeholder="Ex.: 5000",
                    vazio_inicial=True,
                )
            with ce3:
                esp["observacao"] = st.text_input(
                    f"Observação Espécie #{idx + 1}:",
                    value=str(esp.get("observacao", "")),
                    placeholder="Ex.: Fase inicial/crescimento, formulação farelada",
                    key=f"fab_esp_obs_{esp['id']}",
                )
            with ce4:
                st.write("")
                st.write("")
                if len(st.session_state.fab_especies) > 1:
                    if st.button("🗑️", key=f"fab_del_esp_{esp['id']}", use_container_width=True):
                        esp_remover.append(esp["id"])

        if esp_remover:
            st.session_state.fab_especies = [
                e for e in st.session_state.fab_especies if e["id"] not in esp_remover
            ]
            st.rerun()

        if st.button("➕ Adicionar espécie", key="fab_add_esp"):
            st.session_state.fab_especies.append(
                {
                    "id": st.session_state.fab_next_esp_id,
                    "especie": "",
                    "volume": 0,
                    "observacao": "",
                }
            )
            st.session_state.fab_next_esp_id += 1
            st.rerun()

        vol_por_especie = {}
        for esp in st.session_state.fab_especies:
            nome_e = str(esp.get("especie", "")).strip()
            vol_e = int(esp.get("volume", 0))
            if nome_e and vol_e > 0:
                vol_por_especie[nome_e] = vol_por_especie.get(nome_e, 0) + vol_e
        vol_total_fabrica = sum(vol_por_especie.values())

        st.markdown("---")
        st.success(f"📊 **Volume Total Consolidado da Fábrica:** {fmt_br(float(vol_total_fabrica), 0)} ton/mês")
        if vol_por_especie:
            cols_m = st.columns(min(len(vol_por_especie), 6))
            for i, (nome_e, v_int) in enumerate(vol_por_especie.items()):
                cols_m[i % len(cols_m)].metric(nome_e, f"{fmt_br(float(v_int), 0)} ton")

        renderizar_setas_etapa("fab_etapa", 1, 4)

    # ETAPA 2
    elif st.session_state.fab_etapa == 2:
        st.header("Etapa 2: Produtos & Dosagens")
        if st.session_state.cliente_nome:
            st.info(f"👤 **Cliente Ativo:** {st.session_state.cliente_nome}")

        resumo_tags = " | ".join(
            [
                f"**{k}:** {fmt_br(float(v), 0)} ton/mês"
                for k, v in vol_por_especie.items()
                if k != "Total Fábrica de Ração"
            ]
        )
        if resumo_tags:
            st.caption(f"🌾 **Espécies carregadas da Etapa 1:** {resumo_tags}")

        renderizar_catalogo_ft(
            df_produtos,
            df_garantias,
            prefixo_key="fab",
            mostrar_limite_regulatorio=False,
            expanded=True,
        )

        st.markdown("---")
        st.subheader("🛒 Cesta de Aplicação por Espécie & Ponto (Dosagem em kg/ton)")

        opcoes_esp_cesta = [
            str(e["especie"]).strip()
            for e in st.session_state.fab_especies
            if str(e.get("especie", "")).strip()
        ]
        if not opcoes_esp_cesta:
            opcoes_esp_cesta = list(ESPECIES_FABRICA)
        if "Total Fábrica de Ração" not in opcoes_esp_cesta:
            opcoes_esp_cesta.append("Total Fábrica de Ração")

        if not st.session_state.fab_cesta:
            st.session_state.fab_cesta.append(
                {
                    "id": st.session_state.fab_next_cesta_id,
                    "esp_id": None,
                    "especie": opcoes_esp_cesta[0],
                    "ponto": "Misturador",
                    "produto": lista_produtos[0] if lista_produtos else "",
                    "dosagem": 0.000,
                    "observacao": "",
                    "preco_kg": 0.00,
                    "share": 100,
                }
            )
            st.session_state.fab_next_cesta_id += 1

        itens_remover: List[int] = []
        itens_duplicar: List[Dict[str, Any]] = []
        resumo_cesta: List[Dict[str, Any]] = []

        for idx, item in enumerate(st.session_state.fab_cesta):
            c1, c2, c3, c4, c5, c6, c7 = st.columns([1.8, 1.8, 2.5, 1.3, 2.1, 0.9, 0.6])
            with c1:
                esp_idx = (
                    opcoes_esp_cesta.index(item["especie"])
                    if item["especie"] in opcoes_esp_cesta
                    else 0
                )
                item["especie"] = st.selectbox(
                    f"Espécie #{idx + 1}:",
                    options=opcoes_esp_cesta,
                    index=esp_idx,
                    key=f"fab_c_esp_{item['id']}",
                )
            with c2:
                pto_idx = (
                    PONTOS_FABRICA.index(item["ponto"])
                    if item["ponto"] in PONTOS_FABRICA
                    else 0
                )
                item["ponto"] = st.selectbox(
                    f"Ponto #{idx + 1}:",
                    options=PONTOS_FABRICA,
                    index=pto_idx,
                    key=f"fab_c_pto_{item['id']}",
                )
            with c3:
                prod_idx = lista_produtos.index(item["produto"]) if item["produto"] in lista_produtos else 0
                item["produto"] = st.selectbox(
                    f"Produto #{idx + 1}:",
                    options=lista_produtos,
                    index=prod_idx,
                    key=f"fab_c_prod_{item['id']}",
                )
            with c4:
                item["dosagem"] = input_numero_br(
                    f"kg/ton #{idx + 1}:",
                    float(item["dosagem"]),
                    key=f"fab_c_dose_{item['id']}",
                    casas=3,
                    minimo=0.0,
                )
            with c5:
                item["observacao"] = st.text_input(
                    f"Observação #{idx + 1}:",
                    value=str(item.get("observacao", "")),
                    placeholder="Ex.: Ponto de dosagem, qual linha, especificidade, etc.",
                    key=f"fab_c_obs_{item['id']}",
                )
            with c6:
                st.write("")
                st.write("")
                if st.button("➕ Dup", key=f"fab_c_dup_{item['id']}", use_container_width=True):
                    itens_duplicar.append(item.copy())
            with c7:
                st.write("")
                st.write("")
                if len(st.session_state.fab_cesta) > 1:
                    if st.button("🗑️", key=f"fab_c_del_{item['id']}", use_container_width=True):
                        itens_remover.append(item["id"])

            vol_base = float(vol_por_especie.get(item["especie"], 0))
            consumo_linha_kg = vol_base * float(item["dosagem"])

            info_p = mapa_produtos.get(item["produto"], {})
            id_prod = str(info_p.get("id_produto", ""))
            est_fisico = str(info_p.get("estado_fisico", ""))
            comp_str = str(info_p.get("composicao", ""))
            rev_ft = str(info_p.get("ft_revisao", ""))

            entrega = calcular_entrega_ativos_kg_ton(id_prod, float(item["dosagem"]), df_garantias)
            nota_dupla = f" *(Nota: {entrega['observacao_dupla']})*" if entrega["observacao_dupla"] else ""
            st.caption(
                f"📌 **{item['produto']} ({est_fisico} | {rev_ft})** | "
                f"**Ponto:** {item['ponto']} | "
                f"**Entrega por Molécula:** {entrega['detalhe_texto']}{nota_dupla} | "
                f"**Composição:** {comp_str}"
            )
            st.markdown("---")

            resumo_cesta.append(
                {
                    "Item": idx + 1,
                    "Espécie": item["especie"],
                    "Ponto de Aplicação": item["ponto"],
                    "Volume Espécie (ton/mês)": fmt_br(vol_base, 0),
                    "Produto Comercial": item["produto"],
                    "Dosagem (kg/ton)": fmt_br(float(item["dosagem"]), 3),
                    "Entrega por Molécula": entrega["detalhe_texto"],
                    "Ativos Primários (ppm)": (
                        fmt_br(entrega["ppm_primarios"], 2) if entrega["tem_ppm"] else "N/A"
                    ),
                    "Observação": item["observacao"],
                    "Consumo Mensal (kg)": fmt_br(consumo_linha_kg, 2),
                    "_consumo_num": consumo_linha_kg,
                }
            )

        if itens_duplicar:
            for it in itens_duplicar:
                novo_item = it.copy()
                novo_item["id"] = st.session_state.fab_next_cesta_id
                novo_item["esp_id"] = None
                st.session_state.fab_cesta.append(novo_item)
                st.session_state.fab_next_cesta_id += 1
            st.rerun()

        if itens_remover:
            st.session_state.fab_cesta = [
                it for it in st.session_state.fab_cesta if it["id"] not in itens_remover
            ]
            st.rerun()

        if st.button("➕ Adicionar Nova Linha de Tratamento", key="fab_add_cesta"):
            st.session_state.fab_cesta.append(
                {
                    "id": st.session_state.fab_next_cesta_id,
                    "esp_id": None,
                    "especie": opcoes_esp_cesta[0],
                    "ponto": "Misturador",
                    "produto": lista_produtos[0] if lista_produtos else "",
                    "dosagem": 0.000,
                    "observacao": "",
                    "preco_kg": 0.00,
                    "share": 100,
                }
            )
            st.session_state.fab_next_cesta_id += 1
            st.rerun()

        df_resumo = pd.DataFrame(resumo_cesta)
        st.subheader("📋 Quadro Consolidado de Consumo e Entrega em ppm")
        st.dataframe(
            df_resumo.drop(columns=["_consumo_num"]),
            use_container_width=True,
            hide_index=True,
        )

        total_kg_geral = float(df_resumo["_consumo_num"].sum()) if not df_resumo.empty else 0.0
        st.success(f"📦 **Volume Físico Total Estimado na Conta:** {fmt_br(total_kg_geral, 2)} kg / mês")

        renderizar_setas_etapa("fab_etapa", 2, 4)

    # ETAPA 3
    elif st.session_state.fab_etapa == 3:
        st.header("Etapa 3: Faturamento & Proposta (US$)")
        if st.session_state.cliente_nome:
            st.info(
                f"👤 **Cliente Ativo:** {st.session_state.cliente_nome} "
                f"(CNPJ: {st.session_state.cliente_cnpj or 'N/A'})"
            )

        linhas_financeiro: List[Dict[str, Any]] = []
        linhas_proposta_pdf: List[Dict[str, Any]] = []
        tot_vol_fat = 0.0
        tot_fat_mensal = 0.0

        for idx, item in enumerate(st.session_state.fab_cesta):
            vol_base = float(vol_por_especie.get(item["especie"], 0))
            dosagem = float(item["dosagem"])
            consumo_kg_100 = vol_base * dosagem

            info_p = mapa_produtos.get(item["produto"], {})
            id_prod = str(info_p.get("id_produto", ""))
            entrega = calcular_entrega_ativos_kg_ton(id_prod, dosagem, df_garantias)
            ativos_curto = resumo_curto_ativo_pdf(id_prod, df_garantias)

            c_fin1, c_fin2, c_fin3, c_fin4 = st.columns([3, 2, 2, 3])
            with c_fin1:
                st.markdown(
                    f"**{idx + 1}. {item['produto']}** *(Espécie: {item['especie']} | Ponto: {item['ponto']})*"
                )
                st.caption(
                    f"Dosagem: {fmt_br(dosagem, 3)} kg/ton | {entrega['detalhe_texto']} | "
                    f"Obs: {item.get('observacao') or 'N/A'}"
                )
            with c_fin2:
                item["preco_kg"] = input_numero_br(
                    f"Preço US$/kg (#{idx + 1}):",
                    float(item.get("preco_kg", 0.0)),
                    key=f"fab_preco_{item['id']}",
                    casas=2,
                    minimo=0.0,
                )
            with c_fin3:
                item["share"] = st.slider(
                    f"Share % (#{idx + 1}):",
                    min_value=10,
                    max_value=100,
                    value=int(item.get("share", 100)),
                    step=10,
                    key=f"fab_share_{item['id']}",
                )

            preco_kg = float(item["preco_kg"])
            share = int(item["share"])
            consumo_real_kg = consumo_kg_100 * (share / 100.0)
            faturamento_item = consumo_real_kg * preco_kg
            custo_ton_tratada = dosagem * preco_kg

            tot_vol_fat += consumo_real_kg
            tot_fat_mensal += faturamento_item

            with c_fin4:
                st.metric(
                    label=f"Faturamento Item #{idx + 1}",
                    value=f"US$ {fmt_br(faturamento_item, 2)} /mês",
                    delta=f"Custo Tratamento: US$ {fmt_br(custo_ton_tratada, 2)} /ton",
                )
            st.markdown("---")

            linhas_financeiro.append(
                {
                    "Espécie": item["especie"],
                    "Ponto": item["ponto"],
                    "Produto": item["produto"],
                    "Dosagem (kg/ton)": fmt_br(dosagem, 3),
                    "Entrega por Molécula": entrega["detalhe_texto"],
                    "Observação": item.get("observacao", ""),
                    "Custo Tratamento (US$/ton)": fmt_br(custo_ton_tratada, 2),
                    "Share (%)": f"{share}%",
                    "Volume Faturado (kg/mês)": fmt_br(consumo_real_kg, 2),
                    "Preço Unitário (US$/kg)": fmt_br(preco_kg, 2),
                    "Faturamento Mensal (US$)": fmt_br(faturamento_item, 2),
                    "Faturamento Anual (US$)": fmt_br(faturamento_item * 12.0, 2),
                }
            )

            nome_pdf = f"{item['produto']} ({ativos_curto})" if ativos_curto else item["produto"]
            obs_pdf_item = item.get("observacao", "").strip() or f"{item['especie']} - {item['ponto']}"
            linhas_proposta_pdf.append(
                {
                    "produto_pdf": nome_pdf,
                    "dosagem": dosagem,
                    "qtd_mensal": consumo_real_kg,
                    "preco_kg": preco_kg,
                    "custo_ton": custo_ton_tratada,
                    "obs_pdf": obs_pdf_item,
                }
            )

        df_fin = pd.DataFrame(linhas_financeiro)
        st.subheader("💼 Resumo Executivo da Conta (US$)")
        st.dataframe(df_fin, use_container_width=True, hide_index=True)

        r1, r2, r3 = st.columns(3)
        r1.metric("Volume Total Faturado (com Share)", f"{fmt_br(tot_vol_fat, 1)} kg/mês")
        r2.metric("Faturamento Mensal Consolidado", f"US$ {fmt_br(tot_fat_mensal, 2)}")
        r3.metric("Potencial Anualizado da Conta", f"US$ {fmt_br(tot_fat_mensal * 12.0, 2)}")

        renderizar_bloco_pdf("Fabrica_Racao", linhas_proposta_pdf)
        renderizar_setas_etapa("fab_etapa", 3, 4)


# =============================================================================
# ECOSSISTEMAS 3 & 4: FFO BOVINOS E FFO SUÍNOS (ESTRUTURA PROVISÓRIA)
# =============================================================================
def renderizar_ecossistema_ffo_provisorio(
    tipo: str,
    df_produtos: pd.DataFrame,
    df_garantias: pd.DataFrame,
    lista_produtos: List[str],
    mapa_produtos: Dict[str, Any],
) -> None:
    eh_bov = tipo == "ffo_bovinos"
    titulo = "🐂 Ecossistema Comercial - FFO Bovinos" if eh_bov else "🐷 Ecossistema Comercial - FFO Suínos"
    prefixo = "bov" if eh_bov else "sui"
    etapa_key = f"{prefixo}_etapa"
    cesta_key = f"{prefixo}_cesta"
    next_id_key = f"{prefixo}_next_id"

    st.title(titulo)
    st.warning("⚠️ **Módulo em Base Provisória:** estrutura demonstrativa para simulação de volumes, dosagens em kg/ton, ppm e proposta em US$.")

    etapas = [
        "0. Cadastro Cliente",
        "1. Cálculo de Produção FFO",
        "2. Produtos & Dosagens",
        "3. Faturamento & Proposta",
    ]
    etapa_idx = int(st.session_state[etapa_key])
    escolha = st.radio(
        "Navegação das Etapas:",
        options=etapas,
        index=etapa_idx,
        horizontal=True,
        key=f"radio_{prefixo}_etapa",
    )
    if etapas.index(escolha) != etapa_idx:
        st.session_state[etapa_key] = etapas.index(escolha)
        st.rerun()

    st.markdown("---")

    if eh_bov:
        mp = float(st.session_state.bov_mp_ton)
        volumes = {
            "Matéria-Prima Bruta Bovina": mp,
            "Farinha de Carne e Ossos (FCO)": mp * (float(st.session_state.bov_rend_farinha) / 100.0),
            "Sebo Bovino": mp * (float(st.session_state.bov_rend_sebo) / 100.0),
            "Farinha de Sangue Bovina": mp * (float(st.session_state.bov_rend_sangue) / 100.0),
        }
    else:
        mp = float(st.session_state.sui_mp_ton)
        volumes = {
            "Matéria-Prima Bruta Suína": mp,
            "Farinha de Carne e Ossos Suína": mp * (float(st.session_state.sui_rend_farinha) / 100.0),
            "Gordura / Óleo Suíno": mp * (float(st.session_state.sui_rend_gordura) / 100.0),
            "Farinha de Sangue Suína": mp * (float(st.session_state.sui_rend_sangue) / 100.0),
        }

    # ETAPA 0
    if st.session_state[etapa_key] == 0:
        resumo_vol = f"MP FFO: {fmt_br(mp, 1)} ton/mês"
        renderizar_etapa_cadastro_cliente(
            "FFO_Bovinos" if eh_bov else "FFO_Suinos",
            resumo_vol,
            len(st.session_state[cesta_key]),
        )
        renderizar_setas_etapa(etapa_key, 0, 4)

    # ETAPA 1
    elif st.session_state[etapa_key] == 1:
        st.header("Etapa 1: Dimensionamento de Matéria-Prima e Subprodutos (Provisório)")
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("🎯 Entrada de Matéria-Prima")
            if eh_bov:
                st.session_state.bov_mp_ton = input_numero_br(
                    "Matéria-Prima Bruta Bovina Recebida (ton/mês):",
                    float(st.session_state.bov_mp_ton),
                    key="bov_mp_in",
                    casas=1,
                    minimo=1.0,
                )
            else:
                st.session_state.sui_mp_ton = input_numero_br(
                    "Matéria-Prima Bruta Suína Recebida (ton/mês):",
                    float(st.session_state.sui_mp_ton),
                    key="sui_mp_in",
                    casas=1,
                    minimo=1.0,
                )
        with col2:
            st.subheader("⚙️ Rendimentos Industriais (%)")
            if eh_bov:
                st.session_state.bov_rend_farinha = input_numero_br(
                    "Rendimento Farinha Carne/Ossos (%):",
                    float(st.session_state.bov_rend_farinha),
                    key="bov_rf",
                    casas=2,
                    minimo=0.1,
                )
                st.session_state.bov_rend_sebo = input_numero_br(
                    "Rendimento Sebo Bovino (%):",
                    float(st.session_state.bov_rend_sebo),
                    key="bov_rs",
                    casas=2,
                    minimo=0.1,
                )
                st.session_state.bov_rend_sangue = input_numero_br(
                    "Rendimento Farinha de Sangue (%):",
                    float(st.session_state.bov_rend_sangue),
                    key="bov_rsg",
                    casas=2,
                    minimo=0.1,
                )
                mp = float(st.session_state.bov_mp_ton)
                volumes = {
                    "Matéria-Prima Bruta Bovina": mp,
                    "Farinha de Carne e Ossos (FCO)": mp * (float(st.session_state.bov_rend_farinha) / 100.0),
                    "Sebo Bovino": mp * (float(st.session_state.bov_rend_sebo) / 100.0),
                    "Farinha de Sangue Bovina": mp * (float(st.session_state.bov_rend_sangue) / 100.0),
                }
            else:
                st.session_state.sui_rend_farinha = input_numero_br(
                    "Rendimento Farinha Carne/Ossos Suína (%):",
                    float(st.session_state.sui_rend_farinha),
                    key="sui_rf",
                    casas=2,
                    minimo=0.1,
                )
                st.session_state.sui_rend_gordura = input_numero_br(
                    "Rendimento Gordura / Óleo Suíno (%):",
                    float(st.session_state.sui_rend_gordura),
                    key="sui_rg",
                    casas=2,
                    minimo=0.1,
                )
                st.session_state.sui_rend_sangue = input_numero_br(
                    "Rendimento Farinha de Sangue (%):",
                    float(st.session_state.sui_rend_sangue),
                    key="sui_rsg",
                    casas=2,
                    minimo=0.1,
                )
                mp = float(st.session_state.sui_mp_ton)
                volumes = {
                    "Matéria-Prima Bruta Suína": mp,
                    "Farinha de Carne e Ossos Suína": mp * (float(st.session_state.sui_rend_farinha) / 100.0),
                    "Gordura / Óleo Suíno": mp * (float(st.session_state.sui_rend_gordura) / 100.0),
                    "Farinha de Sangue Suína": mp * (float(st.session_state.sui_rend_sangue) / 100.0),
                }

        st.markdown("---")
        cols_v = st.columns(len(volumes))
        for i, (nome_m, val_m) in enumerate(volumes.items()):
            cols_v[i].metric(nome_m, f"{fmt_br(val_m, 1)} ton")

        renderizar_setas_etapa(etapa_key, 1, 4)

    # ETAPA 2
    elif st.session_state[etapa_key] == 2:
        st.header("Etapa 2: Produtos & Dosagens")
        renderizar_catalogo_ft(
            df_produtos,
            df_garantias,
            prefixo_key=prefixo,
            mostrar_limite_regulatorio=True,
            expanded=False,
        )

        st.markdown("---")
        st.subheader("🛒 Cesta de Tratamento (Dosagem em kg/ton)")

        itens_remover: List[int] = []
        itens_duplicar: List[Dict[str, Any]] = []
        resumo_cesta: List[Dict[str, Any]] = []

        for idx, item in enumerate(st.session_state[cesta_key]):
            c1, c2, c3, c4, c5, c6 = st.columns([2.2, 2.8, 1.5, 2.5, 1.0, 0.6])
            with c1:
                lista_mat = list(volumes.keys())
                mat_idx = lista_mat.index(item["matriz"]) if item["matriz"] in lista_mat else 0
                item["matriz"] = st.selectbox(
                    f"Matriz #{idx + 1}:",
                    options=lista_mat,
                    index=mat_idx,
                    key=f"{prefixo}_mat_{item['id']}",
                )
            with c2:
                prod_idx = lista_produtos.index(item["produto"]) if item["produto"] in lista_produtos else 0
                item["produto"] = st.selectbox(
                    f"Produto #{idx + 1}:",
                    options=lista_produtos,
                    index=prod_idx,
                    key=f"{prefixo}_prod_{item['id']}",
                )
            with c3:
                item["dosagem"] = input_numero_br(
                    f"kg/ton #{idx + 1}:",
                    float(item["dosagem"]),
                    key=f"{prefixo}_dose_{item['id']}",
                    casas=3,
                    minimo=0.0,
                )
            with c4:
                item["observacao"] = st.text_input(
                    f"Observação #{idx + 1}:",
                    value=str(item.get("observacao", "")),
                    placeholder="Ex.: Ponto de dosagem, qual linha, especificidade, etc.",
                    key=f"{prefixo}_obs_{item['id']}",
                )
            with c5:
                st.write("")
                st.write("")
                if st.button("➕ Dup", key=f"{prefixo}_dup_{item['id']}", use_container_width=True):
                    itens_duplicar.append(item.copy())
            with c6:
                st.write("")
                st.write("")
                if len(st.session_state[cesta_key]) > 1:
                    if st.button("🗑️", key=f"{prefixo}_del_{item['id']}", use_container_width=True):
                        itens_remover.append(item["id"])

            vol_base = float(volumes.get(item["matriz"], 0.0))
            consumo_linha_kg = vol_base * float(item["dosagem"])

            info_p = mapa_produtos.get(item["produto"], {})
            id_prod = str(info_p.get("id_produto", ""))
            est_fisico = str(info_p.get("estado_fisico", ""))
            comp_str = str(info_p.get("composicao", ""))
            rev_ft = str(info_p.get("ft_revisao", ""))

            entrega = calcular_entrega_ativos_kg_ton(id_prod, float(item["dosagem"]), df_garantias)
            st.caption(
                f"📌 **{item['produto']} ({est_fisico} | {rev_ft})** | "
                f"**Entrega por Molécula:** {entrega['detalhe_texto']} | "
                f"**Composição:** {comp_str}"
            )
            st.markdown("---")

            resumo_cesta.append(
                {
                    "Ponto": idx + 1,
                    "Matriz Aplicada": item["matriz"],
                    "Volume Matriz (ton/mês)": fmt_br(vol_base, 1),
                    "Produto Comercial": item["produto"],
                    "Dosagem (kg/ton)": fmt_br(float(item["dosagem"]), 3),
                    "Entrega por Molécula": entrega["detalhe_texto"],
                    "Observação": item["observacao"],
                    "Consumo Mensal (kg)": fmt_br(consumo_linha_kg, 2),
                    "_consumo_num": consumo_linha_kg,
                }
            )

        if itens_duplicar:
            for it in itens_duplicar:
                novo_item = it.copy()
                novo_item["id"] = st.session_state[next_id_key]
                st.session_state[cesta_key].append(novo_item)
                st.session_state[next_id_key] += 1
            st.rerun()

        if itens_remover:
            st.session_state[cesta_key] = [
                it for it in st.session_state[cesta_key] if it["id"] not in itens_remover
            ]
            st.rerun()

        if st.button("➕ Adicionar Nova Linha de Tratamento", key=f"{prefixo}_add_linha"):
            st.session_state[cesta_key].append(
                {
                    "id": st.session_state[next_id_key],
                    "matriz": list(volumes.keys())[0],
                    "produto": lista_produtos[0] if lista_produtos else "",
                    "dosagem": 0.500,
                    "observacao": "",
                    "preco_kg": 15.00,
                    "share": 100,
                }
            )
            st.session_state[next_id_key] += 1
            st.rerun()

        df_resumo = pd.DataFrame(resumo_cesta)
        st.dataframe(df_resumo.drop(columns=["_consumo_num"]), use_container_width=True, hide_index=True)

        total_kg_geral = float(df_resumo["_consumo_num"].sum()) if not df_resumo.empty else 0.0
        st.success(f"📦 **Volume Físico Total Estimado na Conta:** {fmt_br(total_kg_geral, 2)} kg / mês")

        renderizar_setas_etapa(etapa_key, 2, 4)

    # ETAPA 3
    elif st.session_state[etapa_key] == 3:
        st.header("Etapa 3: Faturamento & Proposta (US$)")
        linhas_financeiro: List[Dict[str, Any]] = []
        linhas_proposta_pdf: List[Dict[str, Any]] = []
        tot_vol_fat = 0.0
        tot_fat_mensal = 0.0

        for idx, item in enumerate(st.session_state[cesta_key]):
            vol_base = float(volumes.get(item["matriz"], 0.0))
            dosagem = float(item["dosagem"])
            consumo_kg_100 = vol_base * dosagem

            info_p = mapa_produtos.get(item["produto"], {})
            id_prod = str(info_p.get("id_produto", ""))
            entrega = calcular_entrega_ativos_kg_ton(id_prod, dosagem, df_garantias)
            ativos_curto = resumo_curto_ativo_pdf(id_prod, df_garantias)

            c_fin1, c_fin2, c_fin3, c_fin4 = st.columns([3, 2, 2, 3])
            with c_fin1:
                st.markdown(f"**{idx + 1}. {item['produto']}** *(em {item['matriz']})*")
                st.caption(f"Dosagem: {fmt_br(dosagem, 3)} kg/ton | {entrega['detalhe_texto']}")
            with c_fin2:
                item["preco_kg"] = input_numero_br(
                    f"Preço US$/kg (#{idx + 1}):",
                    float(item.get("preco_kg", 15.0)),
                    key=f"{prefixo}_preco_{item['id']}",
                    casas=2,
                    minimo=0.0,
                )
            with c_fin3:
                item["share"] = st.slider(
                    f"Share % (#{idx + 1}):",
                    min_value=10,
                    max_value=100,
                    value=int(item.get("share", 100)),
                    step=10,
                    key=f"{prefixo}_share_{item['id']}",
                )

            preco_kg = float(item["preco_kg"])
            share = int(item["share"])
            consumo_real_kg = consumo_kg_100 * (share / 100.0)
            faturamento_item = consumo_real_kg * preco_kg
            custo_ton_tratada = dosagem * preco_kg

            tot_vol_fat += consumo_real_kg
            tot_fat_mensal += faturamento_item

            with c_fin4:
                st.metric(
                    label=f"Faturamento Item #{idx + 1}",
                    value=f"US$ {fmt_br(faturamento_item, 2)} /mês",
                    delta=f"Custo Tratamento: US$ {fmt_br(custo_ton_tratada, 2)} /ton",
                )
            st.markdown("---")

            linhas_financeiro.append(
                {
                    "Matriz": item["matriz"],
                    "Produto": item["produto"],
                    "Dosagem (kg/ton)": fmt_br(dosagem, 3),
                    "Custo Tratamento (US$/ton)": fmt_br(custo_ton_tratada, 2),
                    "Share (%)": f"{share}%",
                    "Volume Faturado (kg/mês)": fmt_br(consumo_real_kg, 2),
                    "Preço Unitário (US$/kg)": fmt_br(preco_kg, 2),
                    "Faturamento Mensal (US$)": fmt_br(faturamento_item, 2),
                    "Faturamento Anual (US$)": fmt_br(faturamento_item * 12.0, 2),
                }
            )

            nome_pdf = f"{item['produto']} ({ativos_curto})" if ativos_curto else item["produto"]
            linhas_proposta_pdf.append(
                {
                    "produto_pdf": nome_pdf,
                    "dosagem": dosagem,
                    "qtd_mensal": consumo_real_kg,
                    "preco_kg": preco_kg,
                    "custo_ton": custo_ton_tratada,
                    "obs_pdf": item.get("observacao", "").strip() or item["matriz"],
                }
            )

        df_fin = pd.DataFrame(linhas_financeiro)
        st.dataframe(df_fin, use_container_width=True, hide_index=True)

        r1, r2, r3 = st.columns(3)
        r1.metric("Volume Total Faturado (com Share)", f"{fmt_br(tot_vol_fat, 1)} kg/mês")
        r2.metric("Faturamento Mensal Consolidado", f"US$ {fmt_br(tot_fat_mensal, 2)}")
        r3.metric("Potencial Anualizado da Conta", f"US$ {fmt_br(tot_fat_mensal * 12.0, 2)}")

        renderizar_bloco_pdf("FFO_Bovinos" if eh_bov else "FFO_Suinos", linhas_proposta_pdf)
        renderizar_setas_etapa(etapa_key, 3, 4)


# =============================================================================
# MÓDULO INDEPENDENTE: CONSULTA DE FTs
# =============================================================================
def renderizar_modulo_consulta_ft(df_produtos: pd.DataFrame, df_garantias: pd.DataFrame) -> None:
    st.title("📄 Central de Consulta de Fichas Técnicas (FT)")
    renderizar_catalogo_ft(
        df_produtos,
        df_garantias,
        prefixo_key="hub_ft",
        mostrar_limite_regulatorio=True,
        expanded=True,
    )

    st.markdown("---")
    st.subheader("🧪 Simulador Rápido de Entrega em ppm (Bancada)")
    col_s1, col_s2, col_s3 = st.columns([2.5, 1.5, 3.5])
    with col_s1:
        prod_sel = st.selectbox(
            "Selecione o Produto:",
            options=df_produtos["produto"].tolist(),
            key="ft_sim_prod",
        )
    with col_s2:
        dose_sim = input_numero_br(
            "Dosagem (kg/ton):",
            0.500,
            key="ft_sim_dose",
            casas=3,
            minimo=0.0,
        )
    with col_s3:
        row_p = df_produtos[df_produtos["produto"] == prod_sel].iloc[0]
        entrega = calcular_entrega_ativos_kg_ton(str(row_p["id_produto"]), dose_sim, df_garantias)
        st.info(
            f"**{prod_sel}** ({row_p['estado_fisico']} | {row_p['ft_revisao']})  \n"
            f"**Entrega:** {entrega['detalhe_texto']}"
        )


# =============================================================================
# AUTENTICAÇÃO E ROTEADOR PRINCIPAL DO PORTAL
# =============================================================================
def autenticar_usuario() -> bool:
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if st.session_state.autenticado:
        return True

    st.title("🔒 Autenticação Restrita")
    st.markdown("Insira a senha de acesso para utilizar o Portal Comercial CFS.")
    senha_digitada = st.text_input("Senha de Acesso:", type="password")
    if st.button("Entrar", type="primary"):
        if hmac.compare_digest(senha_digitada, obter_senha_app()):
            st.session_state.autenticado = True
            st.rerun()
        else:
            st.error("Senha incorreta. Verifique e tente novamente.")
    return False


def main() -> None:
    aplicar_estilos_css()

    if not autenticar_usuario():
        return

    if "ecossistema_ativo" not in st.session_state:
        eco_url = str(st.query_params.get("eco", "portal") or "portal").strip()
        st.session_state["ecossistema_ativo"] = (
            eco_url if eco_url in ECOSSISTEMAS_VALIDOS else "portal"
        )

    df_produtos, df_garantias, horario_sync, erro_carga = carregar_base_normalizada()

    with st.sidebar:
        if erro_carga:
            st.error("Falha na sincronização")
        else:
            st.success(f"Base conectada: {len(df_produtos)} produtos | {len(df_garantias)} garantias")
            st.caption(f"Última sincronização: {horario_sync}")

        if st.button("🔄 Atualizar Base", use_container_width=True):
            carregar_base_normalizada.clear()
            st.rerun()

        st.markdown("---")
        st.header("🌐 Portal de Ecossistemas")

        opcoes_portal = {
            "portal": "🏠 Início (Todos os Ecossistemas)",
            "consulta_ft": "📄 Consulta de FTs",
            "fabrica_racao": "🏭 Fábrica de Ração Comercial",
            "avicultura": "🐔 Avicultura",
            "ffo_bovinos": "🐂 FFO Bovinos (Provisório)",
            "ffo_suinos": "🐷 FFO Suínos (Provisório)",
        }
        chaves_portal = list(opcoes_portal.keys())
        atual = st.session_state.get("ecossistema_ativo", "portal")
        idx_atual = chaves_portal.index(atual) if atual in chaves_portal else 0

        selecionado = st.radio(
            "Ir para:",
            options=chaves_portal,
            format_func=lambda k: opcoes_portal[k],
            index=idx_atual,
            key="sidebar_portal_radio",
        )
        if selecionado != atual:
            st.session_state["ecossistema_ativo"] = selecionado
            try:
                st.query_params["eco"] = selecionado
            except Exception:
                pass
            st.rerun()

    if erro_carga or df_produtos.empty:
        st.error(erro_carga or "A base de dados retornou vazia.")
        return

    lista_produtos = df_produtos["produto"].tolist()
    mapa_produtos = df_produtos.set_index("produto").to_dict(orient="index")

    inicializar_sessao(lista_produtos)

    if st.session_state.ecossistema_ativo != "portal":
        col_back, col_cli_badge = st.columns([1.4, 4.6])
        with col_back:
            if st.button("⬅️ Voltar ao Portal", key="top_back_portal", use_container_width=True):
                navegar_para("portal")
        with col_cli_badge:
            if st.session_state.cliente_nome.strip():
                st.caption(f"Cliente ativo na sessão: **{st.session_state.cliente_nome}**")

    destino = st.session_state.ecossistema_ativo
    if destino == "portal":
        renderizar_portal_hub(df_produtos, df_garantias)
    elif destino == "consulta_ft":
        renderizar_modulo_consulta_ft(df_produtos, df_garantias)
    elif destino == "fabrica_racao":
        renderizar_ecossistema_fabrica_racao(df_produtos, df_garantias, lista_produtos, mapa_produtos)
    elif destino == "avicultura":
        renderizar_ecossistema_avicultura(df_produtos, df_garantias, lista_produtos, mapa_produtos)
    elif destino in ("ffo_bovinos", "ffo_suinos"):
        renderizar_ecossistema_ffo_provisorio(destino, df_produtos, df_garantias, lista_produtos, mapa_produtos)


if __name__ == "__main__":
    main()
