# -*- coding: utf-8 -*-
import os
import time
import pandas as pd
import numpy as np
import streamlit as st
from datetime import date
from dateutil.relativedelta import relativedelta
from supabase import create_client, Client

# -------------------------------------------
# Configuração geral do app
# -------------------------------------------
st.set_page_config(page_title="Previsor de Gastos", page_icon="💸", layout="centered")

SB_URL = st.secrets["SUPABASE_URL"]
SB_KEY = st.secrets["SUPABASE_ANON_KEY"]
APP_NAME = st.secrets.get("APP_NAME", "Previsor de Gastos")
CURRENCY = st.secrets.get("CURRENCY", "R$")

@st.cache_resource
def get_client() -> Client:
    return create_client(SB_URL, SB_KEY)

supabase = get_client()

# -------------------------------------------
# Funções auxiliares
# -------------------------------------------
def ensure_session_state():
    defaults = {
        "user": None,
        "categories": None,
        "expenses": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def sign_up(email: str, password: str):
    auth = supabase.auth.sign_up({"email": email, "password": password})
    user = auth.user
    if user:
        # Cria registro do usuário e uma categoria padrão
        supabase.table("users").insert({"id": user.id, "email": email}).execute()
        supabase.table("categories").insert({"user_id": user.id, "name": "Geral"}).execute()
    return auth


def sign_in(email: str, password: str):
    return supabase.auth.sign_in_with_password({"email": email, "password": password})


def sign_out():
    supabase.auth.sign_out()
    st.session_state.user = None


def fetch_categories(user_id):
    res = supabase.table("categories").select("*").eq("user_id", user_id).execute()
    data = res.data or []
    return pd.DataFrame(data)


def fetch_expenses(user_id, start=None, end=None):
    q = (
        supabase
        .table("expenses").select("*")
        .eq("user_id", user_id)
        .order("dt", desc=False)
    )
    if start:
        q = q.gte("dt", start.isoformat())
    if end:
        q = q.lte("dt", end.isoformat())
    res = q.execute()
    data = res.data or []
    df = pd.DataFrame(data)
    if not df.empty:
        df["dt"] = pd.to_datetime(df["dt"]).dt.date
        df["amount"] = pd.to_numeric(df["amount"])
    return df


def add_expense(user_id, dt, category_id, desc, amount):
    supabase.table("expenses").insert({
        "user_id": user_id,
        "dt": dt.isoformat(),
        "category_id": int(category_id) if category_id else None,
        "description": desc,
        "amount": float(amount)
    }).execute()


def add_category(user_id, name):
    supabase.table("categories").insert({"user_id": user_id, "name": name}).execute()


# -------------------------------------------
# Forecast simples (MVP)
# -------------------------------------------

def monthly_forecast(df: pd.DataFrame, months_ahead: int = 3):
    """
    Forecast enxuto:
    - Agrega por mês (soma)
    - Estima tendência linear (OLS sobre t x y) + média móvel
    """
    if df.empty:
        return pd.DataFrame(columns=["month", "actual", "forecast"])

    s = (
        pd.to_datetime(df["dt"]).to_series(index=df.index)
        .astype("datetime64[ns]")
    )
    ts = pd.DataFrame({"dt": s, "amount": df["amount"].values}).set_index("dt")["amount"]
    ts = ts.resample("MS").sum().rename("actual").asfreq("MS", fill_value=0.0)

    t = np.arange(len(ts))
    A = np.vstack([t, np.ones(len(t))]).T
    a, b = np.linalg.lstsq(A, ts.values, rcond=None)[0]
    trend = a * t + b

    ma = ts.rolling(window=3, min_periods=1).mean().values
    fitted = 0.6 * trend + 0.4 * ma

    last_t = t[-1]
    future_idx = pd.date_range(ts.index[-1] + pd.offsets.MonthBegin(1), periods=months_ahead, freq="MS")
    future_t = np.arange(last_t + 1, last_t + 1 + months_ahead)
    future_trend = a * future_t + b
    future_ma = np.full(months_ahead, ts.tail(3).mean())
    future_forecast = 0.6 * future_trend + 0.4 * future_ma

    out = pd.concat([
        pd.DataFrame({"month": ts.index, "actual": ts.values, "forecast": fitted}),
        pd.DataFrame({"month": future_idx, "actual": np.nan, "forecast": future_forecast})
    ], ignore_index=True)
    out["month"] = pd.to_datetime(out["month"]).dt.date
    return out


# -------------------------------------------
# Interface
# -------------------------------------------
ensure_session_state()
st.title(f"{APP_NAME} 💸")

if st.session_state.user is None:
    st.subheader("Entrar ou criar conta")

    tab_login, tab_signup = st.tabs(["Entrar", "Criar conta"])
    with tab_login:
        email = st.text_input("E-mail", key="login_email")
        password = st.text_input("Senha", type="password", key="login_pw")
        if st.button("Entrar", use_container_width=True):
            try:
                auth = sign_in(email, password)
                st.session_state.user = auth.user
                st.success("Login realizado!")
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao entrar: {e}")

    with tab_signup:
        email2 = st.text_input("E-mail", key="signup_email")
        pw1 = st.text_input("Senha", type="password", key="signup_pw1")
        pw2 = st.text_input("Confirmar senha", type="password", key="signup_pw2")
        if st.button("Criar conta", use_container_width=True, type="primary"):
            if pw1 != pw2:
                st.error("As senhas não coincidem.")
            else:
                try:
                    auth = sign_up(email2, pw1)
                    st.session_state.user = auth.user
                    st.success("Conta criada! Faça login para continuar.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao criar conta: {e}")

    st.stop()

# Área logada
user = st.session_state.user
st.caption(f"Usuário: {getattr(user, 'email', 'desconhecido')}")
if st.button("Sair"):
    sign_out()
    st.rerun()

# Carregar categorias
st.session_state.categories = fetch_categories(user.id)
if st.session_state.categories.empty:
    st.info("Nenhuma categoria. Crie uma abaixo.")

with st.expander("Categorias", expanded=False):
    col1, col2 = st.columns([3,1])
    with col1:
        new_cat = st.text_input("Nova categoria", placeholder="Ex.: Alimentação")
    with col2:
        if st.button("Adicionar"):
            if new_cat.strip():
                add_category(user.id, new_cat.strip())
                st.session_state.categories = fetch_categories(user.id)
                st.success("Categoria adicionada!")
                time.sleep(0.4)
                st.rerun()

# Filtro de período
colA, colB = st.columns(2)
with colA:
    start_date = st.date_input("Início", value=(date.today() - relativedelta(months=3)))
with colB:
    end_date = st.date_input("Fim", value=date.today())

# Lançamento
st.subheader("Lançar gasto")
with st.form("form_expense", clear_on_submit=True):
    dt = st.date_input("Data", value=date.today())
    cat_options = {row["name"]: row["id"] for _, row in st.session_state.categories.iterrows()} if not st.session_state.categories.empty else {}
    cat = st.selectbox("Categoria", options=list(cat_options.keys()) if cat_options else ["(crie uma categoria)"])
    desc = st.text_input("Descrição", placeholder="Ex.: Supermercado")
    amount = st.number_input(f"Valor ({CURRENCY})", min_value=0.0, step=10.0, format="%.2f")
    submitted = st.form_submit_button("Salvar", type="primary")
    if submitted:
        if not cat_options:
            st.error("Crie uma categoria primeiro.")
        else:
            add_expense(user.id, dt, cat_options[cat], desc, amount)
            st.success("Gasto registrado!")

# Dados
st.subheader("Despesas no período")
df = fetch_expenses(user.id, start_date, end_date)
if df.empty:
    st.info("Nenhum gasto ainda.")
else:
    # Join com categorias
    cat_df = st.session_state.categories.rename(columns={"id":"category_id"})
    df = df.merge(cat_df[["category_id","name"]], on="category_id", how="left")
    df = df.rename(columns={"name":"category"})

    st.dataframe(
        df[["dt","category","description","amount"]].sort_values("dt", ascending=False),
        use_container_width=True, hide_index=True
    )

    # Totais por categoria
    by_cat = df.groupby("category", dropna=False)["amount"].sum().sort_values(ascending=False)
    st.bar_chart(by_cat, use_container_width=True)

# Forecast
st.subheader("Previsão de gastos (próximos 3 meses)")
hist = fetch_expenses(user.id)  # histórico completo
forecast_df = monthly_forecast(hist, months_ahead=3)
if forecast_df.empty:
    st.info("Cadastre alguns gastos para gerar a previsão.")
else:
    chart_df = forecast_df.set_index("month")["forecast"].astype(float)
    st.line_chart(chart_df, use_container_width=True)
    next_months = forecast_df[pd.isna(forecast_df["actual"])].set_index("month")["forecast"]
    st.markdown("**Previsão (próximos meses):**")
    for idx, val in next_months.items():
        st.write(f"- {idx.strftime('%b/%Y')}: {CURRENCY} {val:,.2f}".replace(",", "X").replace(".", ",").replace("X","."))
