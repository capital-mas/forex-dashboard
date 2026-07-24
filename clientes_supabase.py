"""
clientes_supabase.py
Dos clientes separados:
- auth_client: solo para sign_up / sign_in (anon key, requerido por el flujo de Auth)
- data_client: para TODO lo demás (service_role key, bypassea RLS)
"""
import streamlit as st
from supabase import create_client

@st.cache_resource
def get_auth_client():
    return create_client(
        st.secrets["supabase"]["url"],
        st.secrets["supabase"]["anon_key"],
    )

@st.cache_resource
def get_data_client():
    return create_client(
        st.secrets["supabase"]["url"],
        st.secrets["supabase"]["service_role_key"],
    )
