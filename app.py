import io
import re
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from streamlit_plotly_events import plotly_events


st.set_page_config(page_title="Linha de Fronteira", layout="wide")

st.title("Linha de Fronteira — Clique nos Pontos")
st.markdown("Suba a planilha, escolha o nutriente e clique diretamente nos pontos.")


# ============================================================
# FUNÇÕES
# ============================================================

def converter_numero_br(serie):
    """
    Converte números vindos do Excel com vírgula decimal, ponto de milhar,
    espaço, %, texto misturado etc.
    """
    s = serie.copy()

    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")

    s = (
        s.astype(str)
        .str.strip()
        .str.replace("\u00a0", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace("%", "", regex=False)
    )

    # Se tiver ponto e vírgula, assume padrão brasileiro: 1.234,56
    mask_br = s.str.contains(r"\.", regex=True) & s.str.contains(",", regex=False)
    s.loc[mask_br] = (
        s.loc[mask_br]
        .str.replace(".", "", regex=False)
        .str.replace(",", ".", regex=False)
    )

    # Se tiver só vírgula, troca vírgula por ponto
    s.loc[~mask_br] = s.loc[~mask_br].str.replace(",", ".", regex=False)

    # Remove qualquer coisa que não seja número, sinal ou ponto
    s = s.str.replace(r"[^0-9\.\-]", "", regex=True)

    return pd.to_numeric(s, errors="coerce")


def ajustar_quadratico(df, x_col, y_col):
    if len(df) < 3:
        return None

    x = df[x_col].astype(float).values
    y = df[y_col].astype(float).values

    X = np.column_stack([x, x**2])

    modelo = LinearRegression()
    modelo.fit(X, y)

    y_pred = modelo.predict(X)

    c = modelo.intercept_
    b = modelo.coef_[0]
    a = modelo.coef_[1]
    r2 = r2_score(y, y_pred)

    if a < 0:
        nc = -b / (2 * a)
        y_max = c + b * nc + a * nc**2
    else:
        nc = np.nan
        y_max = np.nan

    return {
        "c": c,
        "b": b,
        "a": a,
        "r2": r2,
        "nc": nc,
        "y_max": y_max,
        "equacao": f"y = {c:.4f} + {b:.4f}x + {a:.6f}x²"
    }


def pegar_id_clicado(evento, dados_plot):
    if not evento:
        return None

    p = evento[0]

    if "pointIndex" in p:
        idx = int(p["pointIndex"])
    elif "pointNumber" in p:
        idx = int(p["pointNumber"])
    else:
        return None

    if idx < 0 or idx >= len(dados_plot):
        return None

    return int(dados_plot.iloc[idx]["id_ponto"])


def alternar_id(lista, id_clicado):
    lista = list(lista)

    if id_clicado in lista:
        lista.remove(id_clicado)
    else:
        lista.append(id_clicado)

    return lista


# ============================================================
# ESTADO
# ============================================================

if "outliers_por_nutriente" not in st.session_state:
    st.session_state["outliers_por_nutriente"] = {}

if "fronteira_por_nutriente" not in st.session_state:
    st.session_state["fronteira_por_nutriente"] = {}

if "pontos_salvos" not in st.session_state:
    st.session_state["pontos_salvos"] = {}

if "equacoes_salvas" not in st.session_state:
    st.session_state["equacoes_salvas"] = []


# ============================================================
# UPLOAD
# ============================================================

arquivo = st.file_uploader("Suba sua planilha Excel", type=["xlsx"])

if arquivo is None:
    st.info("Suba uma planilha Excel para começar.")
    st.stop()


df = pd.read_excel(arquivo)
df.columns = [str(c).strip() for c in df.columns]

st.success("Planilha carregada com sucesso.")

colunas = df.columns.tolist()

col1, col2, col3 = st.columns(3)

with col1:
    col_prod = st.selectbox(
        "Coluna de produtividade",
        colunas,
        index=colunas.index("PROD") if "PROD" in colunas else 0
    )

# Converter produtividade corretamente
df[col_prod] = converter_numero_br(df[col_prod])

with col2:
    modo_rel = st.radio(
        "Produtividade relativa",
        ["Máximo da base", "Valor fixo"]
    )

with col3:
    if modo_rel == "Valor fixo":
        prod_ref = st.number_input(
            "Valor de referência = 100%",
            value=float(df[col_prod].max())
        )
    else:
        prod_ref = float(df[col_prod].max())

if np.isnan(prod_ref) or prod_ref == 0:
    st.error("A coluna de produtividade não foi lida corretamente. Verifique se a coluna escolhida é a correta.")
    st.stop()

df["PROD_REL"] = (df[col_prod] / prod_ref) * 100

st.info(f"Produtividade usada como 100%: {prod_ref:.2f}")


# ============================================================
# NUTRIENTES
# ============================================================

possiveis_nutrientes = [
    c for c in colunas
    if c not in [col_prod, "PROD_REL"]
]

# ============================================================
# DETECTAR AUTOMATICAMENTE COLUNAS NUMÉRICAS
# ============================================================

colunas_numericas_detectadas = []

for c in possiveis_nutrientes:

    temp = converter_numero_br(df[c])

    n_validos = temp.notna().sum()

    # Se tiver pelo menos 3 valores numéricos válidos,
    # considera como variável quantitativa
    if n_validos >= 3:
        colunas_numericas_detectadas.append(c)

st.write("Colunas numéricas detectadas automaticamente:")
st.write(colunas_numericas_detectadas)

nutrientes = st.multiselect(
    "Selecione os nutrientes/variáveis",
    colunas_numericas_detectadas,
    default=colunas_numericas_detectadas[:5]
)

if len(nutrientes) == 0:
    st.warning("Selecione pelo menos um nutriente.")
    st.stop()

nutriente = st.selectbox("Nutriente atual", nutrientes)

df[nutriente] = converter_numero_br(df[nutriente])

dados = df[[nutriente, col_prod, "PROD_REL"]].copy()
linhas_antes = len(dados)

dados = dados.dropna(subset=[nutriente, col_prod, "PROD_REL"]).copy()
linhas_depois = len(dados)

if linhas_depois == 0:
    st.error(
        f"A base ficou vazia para o nutriente {nutriente}. "
        "Isso indica que essa coluna não foi convertida para número."
    )
    st.write("Diagnóstico:")
    st.write(df[[nutriente, col_prod, "PROD_REL"]].head(20))
    st.write(df[[nutriente, col_prod, "PROD_REL"]].dtypes)
    st.stop()

dados = dados.reset_index(drop=False)
dados = dados.rename(columns={"index": "indice_original"})
dados["id_ponto"] = dados.index.astype(int)

st.caption(f"Linhas antes do filtro: {linhas_antes} | Linhas válidas para o gráfico: {linhas_depois}")


# ============================================================
# ESTADO POR NUTRIENTE
# ============================================================

if nutriente not in st.session_state["outliers_por_nutriente"]:
    st.session_state["outliers_por_nutriente"][nutriente] = []

if nutriente not in st.session_state["fronteira_por_nutriente"]:
    st.session_state["fronteira_por_nutriente"][nutriente] = []

ids_outliers = st.session_state["outliers_por_nutriente"][nutriente]
ids_fronteira = st.session_state["fronteira_por_nutriente"][nutriente]


# ============================================================
# BOTÕES
# ============================================================

colb1, colb2, colb3 = st.columns(3)

with colb1:
    if st.button("Limpar outliers deste nutriente"):
        st.session_state["outliers_por_nutriente"][nutriente] = []
        st.rerun()

with colb2:
    if st.button("Limpar pontos da fronteira deste nutriente"):
        st.session_state["fronteira_por_nutriente"][nutriente] = []
        st.rerun()

with colb3:
    if st.button("Limpar tudo deste nutriente"):
        st.session_state["outliers_por_nutriente"][nutriente] = []
        st.session_state["fronteira_por_nutriente"][nutriente] = []
        st.rerun()


# ============================================================
# 1. OUTLIERS VISUAIS
# ============================================================

st.subheader("1. Clique nos pontos que deseja remover como outliers visuais")
st.write("Clique uma vez para remover. Clique novamente para desfazer.")

cores_out = ["red" if int(i) in ids_outliers else "gray" for i in dados["id_ponto"]]
tamanhos_out = [14 if int(i) in ids_outliers else 8 for i in dados["id_ponto"]]

fig_out = go.Figure()

fig_out.add_trace(
    go.Scatter(
        x=dados[nutriente],
        y=dados["PROD_REL"],
        mode="markers",
        marker=dict(
            size=tamanhos_out,
            color=cores_out,
            opacity=0.85,
            line=dict(width=1, color="black")
        ),
        text=[
            f"ID: {i}<br>{nutriente}: {x:.3f}<br>PROD_REL: {y:.2f}%"
            for i, x, y in zip(dados["id_ponto"], dados[nutriente], dados["PROD_REL"])
        ],
        hoverinfo="text"
    )
)

fig_out.add_hline(y=90, line_dash="dot")

fig_out.update_layout(
    height=520,
    title=f"Outliers visuais — {nutriente}",
    xaxis_title=nutriente,
    yaxis_title="Produtividade relativa (%)",
    clickmode="event+select",
    dragmode=False
)

evento_out = plotly_events(
    fig_out,
    click_event=True,
    hover_event=False,
    select_event=False,
    override_height=520,
    key=f"click_outlier_{nutriente}"
)

id_out = pegar_id_clicado(evento_out, dados)

if id_out is not None:
    st.session_state["outliers_por_nutriente"][nutriente] = alternar_id(
        st.session_state["outliers_por_nutriente"][nutriente],
        id_out
    )

    if id_out in st.session_state["fronteira_por_nutriente"][nutriente]:
        st.session_state["fronteira_por_nutriente"][nutriente].remove(id_out)

    st.rerun()

ids_outliers = st.session_state["outliers_por_nutriente"][nutriente]

dados_filtrados = dados[
    ~dados["id_ponto"].isin(ids_outliers)
].copy().reset_index(drop=True)

st.write(f"Outliers removidos: **{len(ids_outliers)}**")


# ============================================================
# 2. PONTOS DA FRONTEIRA
# ============================================================

st.subheader("2. Clique nos pontos que deseja usar na linha de fronteira")
st.write("Clique uma vez para selecionar. Clique novamente para remover.")

st.session_state["fronteira_por_nutriente"][nutriente] = [
    int(i) for i in st.session_state["fronteira_por_nutriente"][nutriente]
    if int(i) not in ids_outliers
]

ids_fronteira = st.session_state["fronteira_por_nutriente"][nutriente]

cores_front = [
    "orange" if int(i) in ids_fronteira else "lightgray"
    for i in dados_filtrados["id_ponto"]
]

tamanhos_front = [
    15 if int(i) in ids_fronteira else 8
    for i in dados_filtrados["id_ponto"]
]

fig_front = go.Figure()

fig_front.add_trace(
    go.Scatter(
        x=dados_filtrados[nutriente],
        y=dados_filtrados["PROD_REL"],
        mode="markers",
        marker=dict(
            size=tamanhos_front,
            color=cores_front,
            opacity=0.90,
            line=dict(width=1, color="black")
        ),
        text=[
            f"ID: {i}<br>{nutriente}: {x:.3f}<br>PROD_REL: {y:.2f}%"
            for i, x, y in zip(
                dados_filtrados["id_ponto"],
                dados_filtrados[nutriente],
                dados_filtrados["PROD_REL"]
            )
        ],
        hoverinfo="text"
    )
)

fig_front.add_hline(y=90, line_dash="dot")

fig_front.update_layout(
    height=620,
    title=f"Clique nos pontos da fronteira — {nutriente}",
    xaxis_title=nutriente,
    yaxis_title="Produtividade relativa (%)",
    clickmode="event+select",
    dragmode=False
)

evento_front = plotly_events(
    fig_front,
    click_event=True,
    hover_event=False,
    select_event=False,
    override_height=620,
    key=f"click_fronteira_{nutriente}"
)

id_front = pegar_id_clicado(evento_front, dados_filtrados)

if id_front is not None:
    st.session_state["fronteira_por_nutriente"][nutriente] = alternar_id(
        st.session_state["fronteira_por_nutriente"][nutriente],
        id_front
    )
    st.rerun()

ids_fronteira = st.session_state["fronteira_por_nutriente"][nutriente]

pontos_fronteira = dados_filtrados[
    dados_filtrados["id_ponto"].isin(ids_fronteira)
].copy()

st.write(f"Pontos selecionados para fronteira: **{len(pontos_fronteira)}**")


# ============================================================
# 3. AJUSTE
# ============================================================

ajuste = None

if len(pontos_fronteira) >= 3:

    ajuste = ajustar_quadratico(
        pontos_fronteira,
        x_col=nutriente,
        y_col="PROD_REL"
    )

    fig_final = go.Figure()

    fig_final.add_trace(
        go.Scatter(
            x=dados_filtrados[nutriente],
            y=dados_filtrados["PROD_REL"],
            mode="markers",
            marker=dict(size=8, color="lightgray", opacity=0.55),
            name="Dados filtrados"
        )
    )

    fig_final.add_trace(
        go.Scatter(
            x=pontos_fronteira[nutriente],
            y=pontos_fronteira["PROD_REL"],
            mode="markers",
            marker=dict(size=15, color="orange", line=dict(width=2, color="black")),
            name="Pontos da fronteira"
        )
    )

    x_seq = np.linspace(
        dados_filtrados[nutriente].min(),
        dados_filtrados[nutriente].max(),
        300
    )

    y_seq = ajuste["c"] + ajuste["b"] * x_seq + ajuste["a"] * x_seq**2

    fig_final.add_trace(
        go.Scatter(
            x=x_seq,
            y=y_seq,
            mode="lines",
            line=dict(width=4),
            name="Linha de fronteira"
        )
    )

    if not np.isnan(ajuste["nc"]):
        fig_final.add_vline(
            x=ajuste["nc"],
            line_dash="dash",
            annotation_text=f"NC = {ajuste['nc']:.2f}"
        )

    fig_final.add_hline(y=90, line_dash="dot")

    fig_final.update_layout(
        height=620,
        title=f"Linha de Fronteira Ajustada — {nutriente}",
        xaxis_title=nutriente,
        yaxis_title="Produtividade relativa (%)"
    )

    st.plotly_chart(fig_final, use_container_width=True)

    st.subheader("Resultado da equação")
    st.write(f"**Equação:** {ajuste['equacao']}")
    st.write(f"**R²:** {ajuste['r2']:.3f}")
    st.write(f"**NC estimado:** {ajuste['nc']:.3f}")
    st.write(f"**Produtividade máxima estimada:** {ajuste['y_max']:.2f}%")

else:
    st.warning("Selecione pelo menos 3 pontos para ajustar a equação.")


# ============================================================
# 4. TABELAS
# ============================================================

colt1, colt2 = st.columns(2)

with colt1:
    st.markdown("### Dados filtrados")
    st.dataframe(
        dados_filtrados[["id_ponto", "indice_original", nutriente, col_prod, "PROD_REL"]],
        use_container_width=True
    )

with colt2:
    st.markdown("### Pontos selecionados")
    st.dataframe(
        pontos_fronteira[["id_ponto", "indice_original", nutriente, col_prod, "PROD_REL"]],
        use_container_width=True
    )


# ============================================================
# 5. SALVAR NUTRIENTE
# ============================================================

if st.button(f"Salvar pontos de {nutriente}"):

    if ajuste is None:
        st.error("Selecione pelo menos 3 pontos antes de salvar.")
    else:
        pontos_salvar = pontos_fronteira.copy()
        pontos_salvar["nutriente"] = nutriente
        pontos_salvar["x_nutriente"] = pontos_salvar[nutriente]
        pontos_salvar["y_prod_rel"] = pontos_salvar["PROD_REL"]

        st.session_state["pontos_salvos"][nutriente] = pontos_salvar

        resumo = {
            "nutriente": nutriente,
            "n_pontos": len(pontos_fronteira),
            "n_outliers_removidos": len(ids_outliers),
            "equacao": ajuste["equacao"],
            "a_x2": ajuste["a"],
            "b_x": ajuste["b"],
            "c_intercepto": ajuste["c"],
            "R2": ajuste["r2"],
            "NC_estimado": ajuste["nc"],
            "Prod_max_estimada_%": ajuste["y_max"],
            "prod_ref_100%": prod_ref
        }

        st.session_state["equacoes_salvas"] = [
            r for r in st.session_state["equacoes_salvas"]
            if r["nutriente"] != nutriente
        ]

        st.session_state["equacoes_salvas"].append(resumo)

        st.success(f"Pontos de {nutriente} salvos com sucesso.")


# ============================================================
# 6. EXPORTAR EXCEL
# ============================================================

st.divider()
st.subheader("Exportar Excel final")

if len(st.session_state["pontos_salvos"]) > 0:

    pontos_todos = pd.concat(st.session_state["pontos_salvos"].values(), axis=0)
    resumo_final = pd.DataFrame(st.session_state["equacoes_salvas"])

    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:

        df.to_excel(writer, sheet_name="dados_com_prod_rel", index=False)

        pontos_todos.to_excel(
            writer,
            sheet_name="pontos_selecionados",
            index=False
        )

        resumo_final.to_excel(
            writer,
            sheet_name="equacoes",
            index=False
        )

        for nut, tab in st.session_state["pontos_salvos"].items():
            nome_aba = f"sel_{nut}"[:31]
            tab.to_excel(writer, sheet_name=nome_aba, index=False)

    buffer.seek(0)

    st.download_button(
        label="Baixar Excel com pontos selecionados e equações",
        data=buffer,
        file_name="linha_fronteira_pontos_selecionados.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.markdown("### Nutrientes já salvos")
    st.dataframe(resumo_final, use_container_width=True)

else:
    st.info("Nenhum nutriente salvo ainda.")