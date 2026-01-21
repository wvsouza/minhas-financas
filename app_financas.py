import streamlit as st
import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import time
import json
import plotly.express as px

# --- Configuração da Página ---
st.set_page_config(page_title="Minhas Finanças", layout="wide", initial_sidebar_state="collapsed")

# --- Conexão com Firebase ---
# Verifica se já existe uma conexão ativa para não conectar duas vezes
if not firebase_admin._apps:
    try:
        # 1. Tenta carregar dos segredos do Streamlit (Para Nuvem)
        if "firebase_json" in st.secrets:
            # Verifica se é string (JSON colado) ou dicionário (TOML formatado)
            if isinstance(st.secrets["firebase_json"], str):
                cred_info = json.loads(st.secrets["firebase_json"])
            else:
                cred_info = dict(st.secrets["firebase_json"])
            
            cred = credentials.Certificate(cred_info)
            firebase_admin.initialize_app(cred)
        # 2. Caso contrário, tenta arquivo local (Para Computador)
        else:
            cred = credentials.Certificate("firestore_key.json")
            firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Erro ao conectar no Firebase: {e}")
        st.stop()

def check_password():
    """Para a execução do app se a senha não for inserida corretamente."""
    # Se o usuário já estiver logado na sessão, permite o acesso.
    if st.session_state.get("logged_in", False):
        return

    st.title("🔒 Acesso Restrito")
    
    with st.form("login_form"):
        password = st.text_input("Digite a senha para acessar:", type="password")
        submit_button = st.form_submit_button("Entrar")

    if submit_button:
        # A senha deve ser definida nos Segredos do Streamlit
        if "APP_PASSWORD" in st.secrets and password == st.secrets["APP_PASSWORD"]:
            st.session_state["logged_in"] = True
            st.rerun() # Recarrega o app para mostrar o conteúdo principal
        else:
            st.error("Senha incorreta ou não configurada.")
    
    # Para a execução do app se não estiver logado
    st.stop()

check_password()

# --- Botão de Logout ---
if st.sidebar.button("🔒 Sair"):
    st.session_state["logged_in"] = False
    st.rerun()

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

def excluir_tudo():
    docs = db.collection('transacoes').stream()
    for doc in docs:
        doc.reference.delete()
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

# Carrega os dados uma vez para usar em todas as abas (Otimização e Aprendizado)
df_geral = carregar_dados()

tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "➕ Novo Lançamento", "📝 Gerenciar / Editar", "📂 Importar Excel"])

# --- ABA 1: DASHBOARD E EXTRATO ---
with tab1:
    df = df_geral
    
    if not df.empty:
        # Converte a coluna de data (string YYYY-MM-DD) para datetime
        df['data'] = pd.to_datetime(df['data'])
        
        # Filtro de Mês/Ano
        df['mes_ano'] = df['data'].dt.strftime('%Y-%m')
        meses_disponiveis = sorted(df['mes_ano'].unique(), reverse=True)
        
        mes_selecionado = st.selectbox("Selecione o Período", meses_disponiveis)
        
        df_filtrado = df[df['mes_ano'] == mes_selecionado].copy()
        
        # Filtro de Tipo
        tipos_disponiveis = sorted(df_filtrado['tipo'].unique())
        tipos_selecionados = st.multiselect("Filtrar por Tipo", tipos_disponiveis, default=tipos_disponiveis)

        if tipos_selecionados:
            df_filtrado = df_filtrado[df_filtrado['tipo'].isin(tipos_selecionados)]
        
        # Filtro de Categoria
        categorias_disponiveis = sorted(df_filtrado['sub_categoria'].unique())
        categorias_selecionadas = st.multiselect("Filtrar por Categoria", categorias_disponiveis, default=categorias_disponiveis)

        if categorias_selecionadas:
            df_filtrado = df_filtrado[df_filtrado['sub_categoria'].isin(categorias_selecionadas)]

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
        
        st.subheader("Análise de Despesas")
        df_despesas = df_filtrado[df_filtrado['tipo'] == 'Despesa']
        
        if not df_despesas.empty:
            col_g1, col_g2 = st.columns(2)
            
            with col_g1:
                st.markdown("**Por Forma de Pagamento**")
                gastos_por_pagto = df_despesas.groupby("forma_pagamento")["valor"].sum().sort_values(ascending=False)
                st.bar_chart(gastos_por_pagto)
            
            with col_g2:
                st.markdown("**Por Categoria**")
                gastos_por_cat = df_despesas.groupby("sub_categoria")["valor"].sum().reset_index()
                fig = px.pie(gastos_por_cat, values='valor', names='sub_categoria', hole=0.4)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Nenhuma despesa encontrada com os filtros atuais.")
        
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
    
    # Listas Padrão
    lista_cat_receita = ["Salário", "Vale Alimentação", "Vale Refeição", "Auxílio", "Empréstimo Recebido", "Outros"]
    lista_cat_despesa = ["Conta de Luz", "Conta de Celular", "Condomínio", "Internet", "Lazer", "Viagens", "Mercado", "Almoço/Jantar", "Outros"]
    lista_pagamento = ["Cartão de Crédito", "PIX", "Boleto", "Dinheiro", "Vale Refeição", "Vale Alimentação"]

    # Aprendizado: Adiciona categorias/pagamentos que já existem no banco às listas padrão
    if not df_geral.empty:
        if 'sub_categoria' in df_geral.columns:
            cats_receita_db = df_geral[df_geral['tipo'] == 'Receita']['sub_categoria'].unique().tolist()
            lista_cat_receita = sorted(list(set(lista_cat_receita + cats_receita_db)))
            
            cats_despesa_db = df_geral[df_geral['tipo'] == 'Despesa']['sub_categoria'].unique().tolist()
            lista_cat_despesa = sorted(list(set(lista_cat_despesa + cats_despesa_db)))
        
        if 'forma_pagamento' in df_geral.columns:
            pagtos_db = df_geral['forma_pagamento'].unique().tolist()
            lista_pagamento = sorted(list(set(lista_pagamento + pagtos_db)))

    with st.form("form_manual"):
        tipo_operacao = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True)
        
        col_a, col_b = st.columns(2)
        # Input de data com formato brasileiro
        data_transacao = col_a.date_input("Data", datetime.now(), format="DD/MM/YYYY")
        valor = col_b.number_input("Valor (R$)", min_value=0.0, format="%.2f")
        
        if tipo_operacao == "Receita":
            cat_principal = "Renda"
            opcoes_sub = lista_cat_receita
            # Permite selecionar ou manter padrão, mas agora com lista dinâmica
            forma_pagamento_selecao = st.selectbox("Forma de Recebimento", ["Depósito/Conta"] + [p for p in lista_pagamento if p != "Depósito/Conta"])
        else:
            cat_principal = st.selectbox("Classificação", ["Pessoal", "Familiar"])
            opcoes_sub = lista_cat_despesa
            forma_pagamento_selecao = st.selectbox("Pagamento", lista_pagamento)

        sub_categoria_selecao = st.selectbox("Categoria", options=opcoes_sub)
        
        st.markdown("---")
        st.markdown("**Opções de Cadastro (Preencha apenas se não encontrou acima):**")
        col_new_1, col_new_2 = st.columns(2)
        nova_categoria = col_new_1.text_input("Nova Categoria")
        novo_pagamento = col_new_2.text_input("Nova Forma de Pagamento")

        descricao = st.text_input("Descrição", placeholder="Ex: Padaria")
        
        submitted = st.form_submit_button("Salvar Transação")
        if submitted and valor > 0:
            # Lógica: Se preencheu o campo "Novo", usa ele. Senão, usa o do Selectbox.
            cat_final = nova_categoria.strip() if nova_categoria.strip() else sub_categoria_selecao
            pagto_final = novo_pagamento.strip() if novo_pagamento.strip() else forma_pagamento_selecao
            
            # Salva a data como string YYYY-MM-DD para o Firebase
            adicionar_transacao(data_transacao.strftime('%Y-%m-%d'), tipo_operacao, cat_principal, cat_final, descricao, valor, pagto_final)
            st.success("Salvo!")
            
            time.sleep(1) # Pequena pausa para o Firebase processar
            st.rerun()

# --- ABA 3: GERENCIAR / EDITAR ---
with tab3:
    st.header("Editar ou Excluir Lançamentos")
    df_edit = df_geral.copy()
    
    if not df_edit.empty:
        df_edit['data'] = pd.to_datetime(df_edit['data'])
        df_edit = df_edit.sort_values(by='data', ascending=False)
        
        # Tratamento para evitar erros se houver campos vazios
        df_edit['descricao'] = df_edit['descricao'].fillna('')
        df_edit['valor'] = df_edit['valor'].fillna(0.0)
        df_edit['sub_categoria'] = df_edit['sub_categoria'].fillna('Outros')
        df_edit['categoria_principal'] = df_edit['categoria_principal'].fillna('Pessoal')

        # Cria uma lista de descrições para o selectbox
        df_edit['display'] = df_edit['data'].dt.strftime('%d/%m/%Y') + " - " + df_edit['descricao'].astype(str) + " (R$ " + df_edit['valor'].astype(str) + ")"
        
        escolha = st.selectbox("Selecione o lançamento para alterar:", df_edit['display'])
        
        # Pega os dados do item selecionado
        item_selecionado = df_edit[df_edit['display'] == escolha].iloc[0]
        
        with st.expander("✏️ Editar Detalhes", expanded=True):
            with st.form("form_edicao"):
                id_doc = item_selecionado['id']
                
                # Campos preenchidos com os valores atuais
                novo_tipo = st.radio("Tipo", ["Despesa", "Receita"], index=0 if item_selecionado['tipo'] == "Despesa" else 1, horizontal=True)
                
                # --- Lógica de Categorias para Edição ---
                lista_cat_receita = ["Salário", "Vale Alimentação", "Vale Refeição", "Auxílio", "Empréstimo Recebido", "Outros"]
                lista_cat_despesa = ["Conta de Luz", "Conta de Celular", "Condomínio", "Internet", "Lazer", "Viagens", "Mercado", "Almoço/Jantar", "Outros"]
                
                if not df_geral.empty:
                    if 'sub_categoria' in df_geral.columns:
                        cats_receita_db = df_geral[df_geral['tipo'] == 'Receita']['sub_categoria'].unique().tolist()
                        lista_cat_receita = sorted(list(set(lista_cat_receita + cats_receita_db)))
                        cats_despesa_db = df_geral[df_geral['tipo'] == 'Despesa']['sub_categoria'].unique().tolist()
                        lista_cat_despesa = sorted(list(set(lista_cat_despesa + cats_despesa_db)))

                # Define opções com base no tipo ORIGINAL
                if item_selecionado['tipo'] == "Receita":
                    opcoes_cat = lista_cat_receita
                    opcoes_princ = ["Renda"]
                else:
                    opcoes_cat = lista_cat_despesa
                    opcoes_princ = ["Pessoal", "Familiar"]
                
                # Garante que a categoria atual esteja na lista
                if item_selecionado['sub_categoria'] not in opcoes_cat:
                    opcoes_cat.append(item_selecionado['sub_categoria'])
                
                col_cat1, col_cat2 = st.columns(2)
                
                idx_princ = 0
                if item_selecionado['categoria_principal'] in opcoes_princ:
                    idx_princ = opcoes_princ.index(item_selecionado['categoria_principal'])
                
                nova_cat_principal = col_cat1.selectbox("Classificação", options=opcoes_princ, index=idx_princ)
                
                idx_sub = 0
                if item_selecionado['sub_categoria'] in opcoes_cat:
                    idx_sub = opcoes_cat.index(item_selecionado['sub_categoria'])
                
                nova_sub_cat_select = col_cat2.selectbox("Categoria Existente", options=opcoes_cat, index=idx_sub)
                nova_sub_cat_text = st.text_input("Ou Nova Categoria (para renomear/criar):", placeholder="Digite para substituir a seleção acima")

                nova_data = st.date_input("Data", item_selecionado['data'], format="DD/MM/YYYY")
                novo_valor = st.number_input("Valor", value=float(item_selecionado['valor']), format="%.2f")
                nova_desc = st.text_input("Descrição", value=item_selecionado['descricao'])
                
                # Botões de ação
                col_salvar, col_excluir = st.columns(2)
                
                if col_salvar.form_submit_button("💾 Salvar Alterações"):
                    # Define categoria final (se digitou nova, usa a nova)
                    cat_final = nova_sub_cat_text.strip() if nova_sub_cat_text.strip() else nova_sub_cat_select
                    
                    atualizar_transacao(
                        id_doc, 
                        nova_data.strftime('%Y-%m-%d'), 
                        novo_tipo, 
                        nova_cat_principal, 
                        cat_final, 
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
        
        st.markdown("---")
        st.subheader("Zona de Perigo")
        if st.button("🗑️ Excluir TODAS as Transações (Limpar Banco)"):
            excluir_tudo()
            st.success("Todas as transações foram excluídas com sucesso!")
            time.sleep(2)
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
            st.markdown("---")
            st.subheader("1. Ajuste de Leitura")
            st.info("Se o cabeçalho da tabela não estiver na primeira linha (comum em extratos bancários), aumente o número abaixo até que a pré-visualização mostre os nomes das colunas corretamente (ex: Data, Histórico, Valor).")
            pular_linhas = st.number_input("Pular linhas do início do arquivo:", min_value=0, value=0)
            
            uploaded_file.seek(0) # Garante que lê do início do arquivo
            df_import = pd.read_excel(uploaded_file, skiprows=pular_linhas)
            
            st.write("Pré-visualização dos dados:")
            st.dataframe(df_import.head())
            
            st.subheader("2. Configuração da Importação")
            
            col_conf1, col_conf2 = st.columns(2)
            ano_extrato = col_conf1.number_input("Ano do Extrato", min_value=2000, max_value=2100, value=datetime.now().year)
            mes_extrato = col_conf2.selectbox("Mês de Referência", range(1, 13), index=datetime.now().month - 1, help="Ajuda a identificar transações de anos anteriores (ex: compra em Dezembro na fatura de Janeiro).")
            
            usar_data_vencimento = st.checkbox("📅 Forçar data de todos os lançamentos para uma data específica?", value=False, help="Útil para faturas de cartão: joga todos os gastos para o dia do vencimento, ignorando a data original da compra. Assim o valor aparece no mês que você paga.")
            if usar_data_vencimento:
                data_vencimento = st.date_input("Data para os lançamentos", datetime.now())
            
            adicionar_data_desc = st.checkbox("Adicionar data original na descrição? (Útil para conferência)", value=False)
            
            tipo_importacao = st.radio("O que você está importando?", ["Extrato Bancário (Misturado)", "Fatura Cartão de Crédito (Apenas Despesas)"])
            
            if tipo_importacao == "Fatura Cartão de Crédito (Apenas Despesas)":
                padrao_tipo = "Despesa"
                padrao_pagto = "Cartão de Crédito"
                padrao_cat_princ = st.selectbox("Classificação Padrão para esta fatura", ["Pessoal", "Familiar"])
            
            st.markdown("### 3. Mapeie as colunas do seu Excel")
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
                    
                    # Tratamento de Valor (Correção para erro de 'str')
                    try:
                        if isinstance(valor_raw, str):
                            # Remove R$, $, espaços
                            valor_limpo = valor_raw.replace('R$', '').replace('$', '').replace(' ', '')
                            # Ajusta vírgula decimal (Brasil: 1.000,00 -> 1000.00)
                            if ',' in valor_limpo and '.' in valor_limpo:
                                valor_limpo = valor_limpo.replace('.', '').replace(',', '.')
                            elif ',' in valor_limpo:
                                valor_limpo = valor_limpo.replace(',', '.')
                            valor_raw = float(valor_limpo)
                        else:
                            valor_raw = float(valor_raw)
                    except ValueError:
                        valor_raw = 0.0

                    # Tratamento de Data
                    data_final_str = None
                    
                    if usar_data_vencimento:
                        # Se o usuário escolheu forçar a data, usamos a data escolhida
                        data_obj = pd.to_datetime(data_vencimento)
                        data_final_str = data_obj.strftime('%Y-%m-%d')
                    else:
                        try:
                            # Lógica para datas curtas (ex: 01/01) do Bradesco
                            if isinstance(data_raw, str):
                                data_limpa = data_raw.strip()
                                if '/' in data_limpa and len(data_limpa) <= 5 and data_limpa.count('/') == 1:
                                    # Separa dia e mês para análise inteligente
                                    dia_str, mes_str = data_limpa.split('/')
                                    dia = int(dia_str)
                                    mes = int(mes_str)
                                    
                                    # Lógica de Virada de Ano:
                                    # Se a transação é do mês 12 e o extrato é do mês 1 -> Ano Anterior
                                    ano_considerado = ano_extrato
                                    if mes > mes_extrato + 6: # Ex: Mes 12 vs Mes 1 (Diferença grande)
                                        ano_considerado = ano_extrato - 1
                                    
                                    data_raw = f"{dia:02d}/{mes:02d}/{ano_considerado}"

                            data_obj = pd.to_datetime(data_raw, dayfirst=True, errors='coerce')
                            if pd.isnull(data_obj):
                                data_obj = datetime.now()
                        except:
                            data_obj = datetime.now()
                        
                        data_final_str = data_obj.strftime('%Y-%m-%d')
                    
                    if adicionar_data_desc:
                        desc_raw = f"{desc_raw} (Ref: {row[col_data]})"

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