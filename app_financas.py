import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import time
import json

# --- Configuração da Página ---
st.set_page_config(page_title="Minhas Finanças", layout="wide", initial_sidebar_state="collapsed")

# --- Conexão com Firebase ---
# Verifica se já existe uma conexão ativa para não conectar duas vezes
if not firebase_admin._apps:
    try:
        # 1. Tenta carregar dos segredos do Streamlit (Para Nuvem)
        if "firebase_json" in st.secrets:
            cred_info = json.loads(st.secrets["firebase_json"])
            cred = credentials.Certificate(cred_info)
            firebase_admin.initialize_app(cred)
        # 2. Caso contrário, tenta arquivo local (Para Computador)
        else:
            cred = credentials.Certificate("firestore_key.json")
            firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Erro ao conectar no Firebase: {e}")
        st.stop()

db = firestore.client()

# --- Funções de Banco de Dados (CRUD) ---

def adicionar_transacao(data_iso, tipo, cat_principal, sub_cat, desc, valor, pagto):
    # data_iso deve vir no formato YYYY-MM-DD para salvar no banco
    doc_ref = db.collection('transacoes').document()
    doc_ref.set({
        'data': data_iso,
        'tipo': tipo,
        'categoria_principal': cat_principal,
        'sub_categoria': sub_cat,
        'descricao': desc,
        'valor': float(valor),
        'forma_pagamento': pagto,
        'criado_em': firestore.SERVER_TIMESTAMP
    })
    return True

def atualizar_transacao(doc_id, data_iso, tipo, cat_principal, sub_cat, desc, valor, pagto):
    doc_ref = db.collection('transacoes').document(doc_id)
    doc_ref.update({
        'data': data_iso,
        'tipo': tipo,
        'categoria_principal': cat_principal,
        'sub_categoria': sub_cat,
        'descricao': desc,
        'valor': float(valor),
        'forma_pagamento': pagto
    })
    return True

def excluir_transacao(doc_id):
    db.collection('transacoes').document(doc_id).delete()
    return True

def carregar_dados():
    # Busca todos os documentos da coleção 'transacoes'
    docs = db.collection('transacoes').stream()
    items = []
    for doc in docs:
        item = doc.to_dict()
        item['id'] = doc.id # Guarda o ID para poder editar/excluir depois
        items.append(item)
    
    if not items:
        return pd.DataFrame()
        
    df = pd.DataFrame(items)
    return df

# --- Interface Principal ---
st.title("📱 Minhas Finanças")

tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "➕ Novo Lançamento", "📝 Gerenciar / Editar", "📂 Importar Excel"])

# --- ABA 1: DASHBOARD E EXTRATO ---
with tab1:
    df = carregar_dados()
    
    if not df.empty:
        # Converte a coluna de data (string YYYY-MM-DD) para datetime
        df['data'] = pd.to_datetime(df['data'])
        
        # Filtro de Mês/Ano
        df['mes_ano'] = df['data'].dt.strftime('%Y-%m')
        meses_disponiveis = sorted(df['mes_ano'].unique(), reverse=True)
        
        mes_selecionado = st.selectbox("Selecione o Período", meses_disponiveis)
        
        df_filtrado = df[df['mes_ano'] == mes_selecionado].copy()

        # --- Lógica VR (Vale Refeição) ---
        # Receita fixa mensal de R$ 220,00 se houver entrada de "Vale Refeição"
        # OU se o usuário cadastrar manualmente. Vamos assumir o cálculo baseado nos lançamentos.
        entradas_vr = df[(df['tipo'] == 'Receita') & (df['sub_categoria'] == 'Vale Refeição')]['valor'].sum()
        saidas_vr = df[(df['tipo'] == 'Despesa') & (df['forma_pagamento'] == 'Vale Refeição')]['valor'].sum()
        saldo_vr = entradas_vr - saidas_vr

        # Métricas do Mês
        receitas = df_filtrado[df_filtrado['tipo'] == 'Receita']['valor'].sum()
        despesas = df_filtrado[df_filtrado['tipo'] == 'Despesa']['valor'].sum()
        saldo = receitas - despesas

        col1, col2 = st.columns(2)
        col1.metric("Saldo do Mês", f"R$ {saldo:,.2f}")
        col2.metric("Saldo VR (Total)", f"R$ {saldo_vr:,.2f}")
        
        st.divider()
        
        st.subheader("Extrato Detalhado")
        
        st.dataframe(
            df_filtrado[['data', 'tipo', 'sub_categoria', 'descricao', 'valor', 'forma_pagamento']].sort_values(by='data', ascending=False),
            use_container_width=True,
            hide_index=True,
            column_config={
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                "tipo": "Tipo",
                "sub_categoria": "Categoria",
                "descricao": "Descrição",
                "forma_pagamento": "Pagamento"
            }
        )
    else:
        st.info("Nenhum dado cadastrado.")

# --- ABA 2: LANÇAMENTO MANUAL ---
with tab2:
    st.header("Registro Manual")
    with st.form("form_manual"):
        tipo_operacao = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        
        col_a, col_b = st.columns(2)
        # Input de data com formato brasileiro
        data_transacao = col_a.date_input("Data", datetime.now(), format="DD/MM/YYYY")
        valor = col_b.number_input("Valor (R$)", min_value=0.0, format="%.2f")
        
        if tipo_operacao == "Receita":
            cat_principal = "Renda"
            opcoes_sub = ["Salário", "Vale Alimentação", "Vale Refeição", "Auxílio", "Empréstimo Recebido", "Outros"]
            forma_pagamento = "Depósito/Conta"
        else:
            cat_principal = st.selectbox("Classificação", ["Pessoal", "Familiar"])
            opcoes_sub = ["Conta de Luz", "Conta de Celular", "Condomínio", "Internet", "Lazer", "Viagens", "Mercado", "Almoço/Jantar", "Outros"]
            forma_pagamento = st.selectbox("Pagamento", ["Cartão de Crédito", "PIX", "Boleto", "Dinheiro", "Vale Refeição", "Vale Alimentação"])

        sub_categoria = st.selectbox("Categoria", options=opcoes_sub)
        descricao = st.text_input("Descrição", placeholder="Ex: Padaria")
        
        submitted = st.form_submit_button("Salvar Transação")
        if submitted and valor > 0:
            # Salva a data como string YYYY-MM-DD para o Firebase
            adicionar_transacao(data_transacao.strftime('%Y-%m-%d'), tipo_operacao, cat_principal, sub_categoria, descricao, valor, forma_pagamento)
            st.success("Salvo!")
            time.sleep(1) # Pequena pausa para o Firebase processar
            st.rerun()

# --- ABA 3: GERENCIAR / EDITAR ---
with tab3:
    st.header("Editar ou Excluir Lançamentos")
    df_edit = carregar_dados()
    
    if not df_edit.empty:
        df_edit['data'] = pd.to_datetime(df_edit['data'])
        df_edit = df_edit.sort_values(by='data', ascending=False)
        
        # Cria uma lista de descrições para o selectbox
        df_edit['display'] = df_edit['data'].dt.strftime('%d/%m/%Y') + " - " + df_edit['descricao'] + " (R$ " + df_edit['valor'].astype(str) + ")"
        
        escolha = st.selectbox("Selecione o lançamento para alterar:", df_edit['display'])
        
        # Pega os dados do item selecionado
        item_selecionado = df_edit[df_edit['display'] == escolha].iloc[0]
        
        with st.expander("✏️ Editar Detalhes", expanded=True):
            with st.form("form_edicao"):
                id_doc = item_selecionado['id']
                
                # Campos preenchidos com os valores atuais
                novo_tipo = st.radio("Tipo", ["Despesa", "Receita"], index=0 if item_selecionado['tipo'] == "Despesa" else 1, horizontal=True)
                nova_data = st.date_input("Data", item_selecionado['data'], format="DD/MM/YYYY")
                novo_valor = st.number_input("Valor", value=float(item_selecionado['valor']), format="%.2f")
                nova_desc = st.text_input("Descrição", value=item_selecionado['descricao'])
                
                # Botões de ação
                col_salvar, col_excluir = st.columns(2)
                
                if col_salvar.form_submit_button("💾 Salvar Alterações"):
                    atualizar_transacao(
                        id_doc, 
                        nova_data.strftime('%Y-%m-%d'), 
                        novo_tipo, 
                        item_selecionado['categoria_principal'], # Mantém a categoria original por simplicidade ou adicione selectbox
                        item_selecionado['sub_categoria'], 
                        nova_desc, 
                        novo_valor, 
                        item_selecionado['forma_pagamento']
                    )
                    st.success("Atualizado com sucesso!")
                    time.sleep(1)
                    st.rerun()
                
                if col_excluir.form_submit_button("🗑️ Excluir Lançamento", type="primary"):
                    excluir_transacao(id_doc)
                    st.warning("Lançamento excluído.")
                    time.sleep(1)
                    st.rerun()
    else:
        st.info("Sem dados para editar.")

# --- ABA 4: IMPORTAÇÃO DE EXCEL ---
with tab4:
    st.header("Importar Extrato ou Fatura")
    st.markdown("Faça upload do arquivo Excel (.xlsx) do seu banco ou cartão.")
    
    uploaded_file = st.file_uploader("Escolha o arquivo Excel", type=['xlsx', 'xls'])
    
    if uploaded_file is not None:
        try:
            df_import = pd.read_excel(uploaded_file)
            st.write("Pré-visualização dos dados:")
            st.dataframe(df_import.head())
            
            st.subheader("Configuração da Importação")
            
            tipo_importacao = st.radio("O que você está importando?", ["Extrato Bancário (Misturado)", "Fatura Cartão de Crédito (Apenas Despesas)"])
            
            if tipo_importacao == "Fatura Cartão de Crédito (Apenas Despesas)":
                padrao_tipo = "Despesa"
                padrao_pagto = "Cartão de Crédito"
                padrao_cat_princ = st.selectbox("Classificação Padrão para esta fatura", ["Pessoal", "Familiar"])
            
            st.markdown("### Mapeie as colunas do seu Excel")
            colunas_excel = df_import.columns.tolist()
            
            col_data = st.selectbox("Qual coluna é a DATA?", colunas_excel)
            col_desc = st.selectbox("Qual coluna é a DESCRIÇÃO?", colunas_excel)
            col_valor = st.selectbox("Qual coluna é o VALOR?", colunas_excel)
            
            if st.button("Processar e Salvar Importação"):
                count = 0
                bar = st.progress(0)
                
                for index, row in df_import.iterrows():
                    data_raw = row[col_data]
                    desc_raw = row[col_desc]
                    valor_raw = row[col_valor]
                    
                    # Tratamento de data para garantir formato YYYY-MM-DD
                    if isinstance(data_raw, str):
                        # Tenta converter string para data (ajuste conforme seu excel se necessário)
                        try:
                            data_obj = datetime.strptime(data_raw, '%d/%m/%Y')
                        except:
                            data_obj = datetime.now() # Fallback
                    else:
                        data_obj = data_raw
                    
                    data_final_str = data_obj.strftime('%Y-%m-%d')

                    if tipo_importacao == "Extrato Bancário (Misturado)":
                        if valor_raw < 0:
                            tipo_final = "Despesa"
                            valor_final = abs(valor_raw)
                            pagto_final = "Débito/PIX"
                        else:
                            tipo_final = "Receita"
                            valor_final = valor_raw
                            pagto_final = "Depósito"
                        cat_princ_final = "Pessoal"
                        sub_cat_final = "Outros"
                    else:
                        tipo_final = padrao_tipo
                        valor_final = abs(valor_raw)
                        pagto_final = padrao_pagto
                        cat_princ_final = padrao_cat_princ
                        sub_cat_final = "Fatura Cartão"
                    
                    adicionar_transacao(data_final_str, tipo_final, cat_princ_final, sub_cat_final, desc_raw, valor_final, pagto_final)
                    count += 1
                    bar.progress((index + 1) / len(df_import))
                
                st.success(f"{count} transações importadas com sucesso!")
                time.sleep(2)
                st.rerun()
                
        except Exception as e:
            st.error(f"Erro ao ler o arquivo: {e}")