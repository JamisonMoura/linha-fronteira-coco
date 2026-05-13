import io
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score


st.set_page_config(
    page_title="Linha de Fronteira",
    layout="wide"
)

st.title("Linha de Fronteira — Seleção Manual de Pontos")
st.markdown("Suba sua planilha, selecione os pontos da fronteira e elimine visualmente pontos que considerar outliers.")


# ============================================================
# FUNÇÃO DE REGRESSÃO QUADRÁTICA
# ============================================================

def ajustar_quadratico(df, x_col, y_col):
    if len(df) < 3:
        return None

    x = df[x_col].values
    y = df[y_col].values

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


# ============================================================
# ESTADO DO APP
# ============================================================

if "pontos_salvos" not in st.session_state:
    st.session_state["pontos_salvos"] = {}

if "equacoes_salvas" not in st.session_state:
    st.session_state["equacoes_salvas"] = []


# ============================================================
# UPLOAD
# ============================================================

arquivo = st.file_uploader(
    "Suba sua planilha Excel",
    type=["xlsx"]
)

if arquivo is not None:

    df = pd.read_excel(arquivo)
    df.columns = [str(c).strip() for c in df.columns]

    st.success("Planilha carregada com sucesso.")

    with st.expander("Visualizar dados originais"):
        st.dataframe(df)

    colunas = df.columns.tolist()

    col1, col2, col3 = st.columns(3)

    with col1:
        col_prod = st.selectbox(
            "Coluna de produtividade",
            colunas,
            index=colunas.index("PROD") if "PROD" in colunas else 0
        )

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

    df[col_prod] = pd.to_numeric(df[col_prod], errors="coerce")
    df["PROD_REL"] = (df[col_prod] / prod_ref) * 100

    st.info(f"Produtividade usada como 100%: {prod_ref:.2f}")

    possiveis_nutrientes = [
        c for c in colunas
        if c not in [col_prod, "PROD_REL"]
    ]

    nutrientes = st.multiselect(
        "Selecione os nutrientes que deseja analisar",
        possiveis_nutrientes,
        default=[c for c in ["N", "P", "K", "Ca", "Mg", "S", "B", "Cu", "Mn", "Fe", "Zn"] if c in possiveis_nutrientes]
    )

    if len(nutrientes) == 0:
        st.warning("Selecione pelo menos um nutriente.")
        st.stop()

    nutriente = st.selectbox(
        "Nutriente atual",
        nutrientes
    )

    df[nutriente] = pd.to_numeric(df[nutriente], errors="coerce")

    dados = df[[nutriente, col_prod, "PROD_REL"]].dropna().copy()
    dados = dados.reset_index(drop=False)
    dados = dados.rename(columns={"index": "indice_original"})
    dados["id_ponto"] = dados.index

    st.subheader(f"Gráfico — {nutriente} x Produtividade Relativa")

    # ============================================================
    # SELEÇÃO DE OUTLIERS VISUAIS
    # ============================================================

    st.markdown("### 1. Eliminar pontos visualmente fora do padrão")

    st.write(
        "Observe o gráfico e informe os IDs dos pontos que deseja remover como outliers visuais."
    )

    ids_outliers = st.multiselect(
        "IDs dos pontos para excluir visualmente",
        dados["id_ponto"].tolist(),
        key=f"outliers_{nutriente}"
    )

    dados_filtrados = dados[~dados["id_ponto"].isin(ids_outliers)].copy()

    # ============================================================
    # SELEÇÃO DOS PONTOS DE FRONTEIRA
    # ============================================================

    st.markdown("### 2. Selecionar pontos da fronteira superior")

    ids_fronteira = st.multiselect(
        "IDs dos pontos que deseja usar na linha de fronteira",
        dados_filtrados["id_ponto"].tolist(),
        key=f"fronteira_{nutriente}"
    )

    pontos_fronteira = dados_filtrados[
        dados_filtrados["id_ponto"].isin(ids_fronteira)
    ].copy()

    # ============================================================
    # GRÁFICO
    # ============================================================

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=dados[nutriente],
            y=dados["PROD_REL"],
            mode="markers",
            marker=dict(size=8, opacity=0.35),
            text=[
                f"ID: {i}<br>{nutriente}: {x:.3f}<br>PROD_REL: {y:.2f}%"
                for i, x, y in zip(dados["id_ponto"], dados[nutriente], dados["PROD_REL"])
            ],
            hoverinfo="text",
            name="Todos os dados"
        )
    )

    if len(ids_outliers) > 0:
        dados_out = dados[dados["id_ponto"].isin(ids_outliers)]

        fig.add_trace(
            go.Scatter(
                x=dados_out[nutriente],
                y=dados_out["PROD_REL"],
                mode="markers",
                marker=dict(size=12, symbol="x"),
                text=[
                    f"OUTLIER VISUAL<br>ID: {i}<br>{nutriente}: {x:.3f}<br>PROD_REL: {y:.2f}%"
                    for i, x, y in zip(dados_out["id_ponto"], dados_out[nutriente], dados_out["PROD_REL"])
                ],
                hoverinfo="text",
                name="Outliers visuais removidos"
            )
        )

    if len(pontos_fronteira) > 0:
        fig.add_trace(
            go.Scatter(
                x=pontos_fronteira[nutriente],
                y=pontos_fronteira["PROD_REL"],
                mode="markers",
                marker=dict(size=13, line=dict(width=2)),
                text=[
                    f"FRONTEIRA<br>ID: {i}<br>{nutriente}: {x:.3f}<br>PROD_REL: {y:.2f}%"
                    for i, x, y in zip(
                        pontos_fronteira["id_ponto"],
                        pontos_fronteira[nutriente],
                        pontos_fronteira["PROD_REL"]
                    )
                ],
                hoverinfo="text",
                name="Pontos selecionados"
            )
        )

    ajuste = None

    if len(pontos_fronteira) >= 3:
        ajuste = ajustar_quadratico(
            pontos_fronteira,
            x_col=nutriente,
            y_col="PROD_REL"
        )

        if ajuste is not None:
            x_seq = np.linspace(
                dados_filtrados[nutriente].min(),
                dados_filtrados[nutriente].max(),
                300
            )

            y_seq = (
                ajuste["c"]
                + ajuste["b"] * x_seq
                + ajuste["a"] * x_seq**2
            )

            fig.add_trace(
                go.Scatter(
                    x=x_seq,
                    y=y_seq,
                    mode="lines",
                    line=dict(width=4),
                    name="Linha de fronteira"
                )
            )

            if not np.isnan(ajuste["nc"]):
                fig.add_vline(
                    x=ajuste["nc"],
                    line_dash="dash",
                    annotation_text=f"NC = {ajuste['nc']:.2f}",
                    annotation_position="top"
                )

    fig.add_hline(
        y=90,
        line_dash="dot",
        annotation_text="90% produtividade relativa",
        annotation_position="bottom right"
    )

    fig.update_layout(
        height=700,
        title=f"Linha de Fronteira — {nutriente}",
        xaxis_title=nutriente,
        yaxis_title="Produtividade relativa (%)",
        legend_title="Legenda"
    )

    st.plotly_chart(fig, use_container_width=True)

    # ============================================================
    # TABELAS AUXILIARES
    # ============================================================

    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("### Tabela para escolher os pontos")
        st.dataframe(
            dados[[ "id_ponto", "indice_original", nutriente, col_prod, "PROD_REL" ]],
            use_container_width=True
        )

    with col_b:
        st.markdown("### Pontos selecionados para fronteira")
        st.dataframe(
            pontos_fronteira[[ "id_ponto", "indice_original", nutriente, col_prod, "PROD_REL" ]],
            use_container_width=True
        )

    # ============================================================
    # RESULTADOS DO MODELO
    # ============================================================

    if ajuste is not None:
        st.subheader("Resultado da equação")

        st.write(f"**Equação:** {ajuste['equacao']}")
        st.write(f"**R2:** {ajuste['r2']:.3f}")
        st.write(f"**NC estimado:** {ajuste['nc']:.3f}")
        st.write(f"**Produtividade máxima estimada:** {ajuste['y_max']:.2f}%")

    else:
        st.warning("Selecione pelo menos 3 pontos para ajustar a equação.")

    # ============================================================
    # SALVAR NUTRIENTE
    # ============================================================

    if st.button(f"Salvar pontos de {nutriente}"):

        if len(pontos_fronteira) < 3:
            st.error("Selecione pelo menos 3 pontos antes de salvar.")
        else:
            pontos_salvar = pontos_fronteira.copy()
            pontos_salvar["nutriente"] = nutriente
            pontos_salvar["x_nutriente"] = pontos_salvar[nutriente]
            pontos_salvar["y_prod_rel"] = pontos_salvar["PROD_REL"]

            st.session_state["pontos_salvos"][nutriente] = pontos_salvar

            if ajuste is not None:
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
    # EXPORTAÇÃO FINAL
    # ============================================================

    st.divider()
    st.subheader("Exportar Excel final")

    if len(st.session_state["pontos_salvos"]) > 0:

        pontos_todos = pd.concat(
            st.session_state["pontos_salvos"].values(),
            axis=0
        )

        resumo_final = pd.DataFrame(
            st.session_state["equacoes_salvas"]
        )

        buffer = io.BytesIO()

        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:

            df.to_excel(
                writer,
                sheet_name="dados_com_prod_rel",
                index=False
            )

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
                tab.to_excel(
                    writer,
                    sheet_name=nome_aba,
                    index=False
                )

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
else:
    st.info("Suba uma planilha Excel para começar.")