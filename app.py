import os
import re
import io
import pandas as pd
import streamlit as st
import pdfplumber  # Engine de extração local para PDFs

# Configuração da página do Streamlit
st.set_page_config(
    page_title="Conversor Contábil Multi-Meses com Subcontas",
    page_icon="📊",
    layout="wide"
)

# Dicionário para conversão amigável de número do mês para nome em português
MESES_NOME = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
}

def pre_analisar_meses(linhas):
    """
    Varre as linhas de texto para identificar quais meses/anos possuem lançamentos válidos.
    """
    meses_encontrados = set()
    padrao_data = r'^(\d{2})/(\d{2})/(\d{4})'
    
    for linha in linhas:
        linha_limpa = linha.strip()
        match = re.search(padrao_data, linha_limpa)
        if match:
            if "SALDO DIA" in linha_limpa or "SALDO ANTERIOR" in linha_limpa:
                continue
            mes = int(match.group(2))
            ano = int(match.group(3))
            meses_encontrados.add((mes, ano))
            
    return sorted(list(meses_encontrados), key=lambda x: (x[1], x[0]))

def processar_linha_caixa(linha, conta_banco, conta_fornecedor, conta_cliente, mes_filtro, ano_filtro, regras_mapeamento):
    """
    Processa as linhas aplicando as regras contábeis, filtros de mês e mapeamento de subcontas.
    """
    linha_limpa = linha.strip()
    padrao_data = r'^(\d{2})/(\d{2})/(\d{4})'
    match_data = re.search(padrao_data, linha_limpa)
    if not match_data:
        return None
        
    dia_final = match_data.group(1)
    mes_linha = int(match_data.group(2))
    ano_linha = int(match_data.group(3))
    
    # Filtro de período escolhido
    if mes_linha != mes_filtro or ano_linha != ano_filtro:
        return None
        
    if "SALDO DIA" in linha_limpa or "SALDO ANTERIOR" in linha_limpa:
        return None
        
    partes = list(filter(None, linha_limpa.split()))
    if len(partes) < 2:
        return None

    tipo = None
    valor_str = ""
    
    # Identifica indicador D ou C na linha varrendo as colunas
    for i, parte in enumerate(partes):
        parte_clean = parte.strip().upper()
        if parte_clean in ['D', 'C']:
            tipo = parte_clean
            if i > 0:
                valor_str = partes[i-1]
            break
        elif parte_clean.endswith('D') and ',' in parte_clean:
            tipo = 'D'
            valor_str = parte_clean[:-1]
            break
        elif parte_clean.endswith('C') and ',' in parte_clean:
            tipo = 'C'
            valor_str = parte_clean[:-1]
            break

    if not tipo or not valor_str:
        return None

    try:
        valor_limpo = valor_str.replace('.', '').replace(',', '.')
        valor_float = float(valor_limpo)
    except ValueError:
        return None

    doc = "000000"
    for p in partes:
        p_clean = p.replace('-', '').replace('/', '').strip()
        if p_clean.isdigit() and len(p_clean) == 6:
            doc = p_clean
            break

    sub_hora = r'\b\d{2}:\d{2}(:\d{2})?\b'
    elementos_remover = [partes, doc, valor_str, tipo, 'D', 'C', '-', '–']
    
    palavras_desc = []
    for p in partes:
        if re.search(sub_hora, p) or p in elementos_remover or any(dt in p for dt in [f"{dia_final}/{mes_linha:02d}", str(ano_linha)]):
            continue
        p_limpo = p.replace('*', '').strip()
        if p_limpo and p_limpo not in ['D', 'C', '-', '–']:
            palavras_desc.append(p_limpo)

    texto_complementar = " ".join(palavras_desc).strip()
    texto_complementar = re.sub(r'\s+', ' ', texto_complementar)
    texto_complementar = re.sub(r'\b\d{1,3}(\.\d{3})*,\d{2}\b', '', texto_complementar).strip()
    descricao_final = f"{texto_complementar} (Doc: {doc})"

    # Mapeamento de subcontas
    conta_mapeada = None
    for palavra, conta in regras_mapeamento.items():
        if palavra.upper() in descricao_final.upper():
            if str(conta).strip() == str(conta_banco).strip():
                continue
            conta_mapeada = conta
            break

    if tipo == 'D':
        conta_debito = conta_mapeada if conta_mapeada else conta_fornecedor
        conta_credito = conta_banco
    else:
        conta_debito = conta_banco
        conta_credito = conta_mapeada if conta_mapeada else conta_cliente

    valor_com_virgula = f"{valor_float:.2f}".replace('.', ',')
    data_formatada = f"{dia_final}/{mes_linha:02d}/{ano_linha}"

    return {
        'data': data_formatada,
        'conta debito': conta_debito,
        'conta crédito': conta_credito,
        'valor': valor_com_virgula,
        'descrição': descricao_final
    }

# --- PAINEL VISUAL STREAMLIT ---
st.title("📊 Conversor Contábil de PDFs Direto com Subcontas")
st.markdown("Arraste os seus arquivos **PDF** de imagem ou escaneados diretamente aqui. O sistema usará o leitor local.")

# 1. Configuração Fixa do Plano de Contas Padrão na Sidebar
st.sidebar.header("⚙️ Contas Padrão")
cont_banco = st.sidebar.text_input("Conta Banco:", value="6")
cont_fornecedor = st.sidebar.text_input("Transitória Fornecedor (Padrão D):", value="848")
cont_cliente = st.sidebar.text_input("Transitória Cliente (Padrão C):", value="861")

# 2. Painel Central de Regras para Subcontas customizadas por Histórico
st.markdown("### 🔍 Mapeamento Dinâmico de Subcontas")
st.write("Adicione palavras-chave encontradas na descrição do extrato para amarrar automaticamente a contas específicas:")

if 'mapeamento' not in st.session_state:
    st.session_state.mapeamento = {}

col_palavra, col_conta, col_btn = st.columns(3)
with col_palavra:
    nova_palavra = st.text_input("Palavra-chave no Histórico (Ex: IOF):", key="input_palavra")
with col_conta:
    nova_conta = st.text_input("Código da Conta Contábil Relacionada:", key="input_conta")
with col_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("➕ Adicionar Regra", key="add_regra", use_container_width=True):
        if nova_palavra and nova_conta:
            if nova_conta.strip() == cont_banco.strip():
                st.error("A conta banco não pode ser usada em regras de subcontas.")
            else:
                st.session_state.mapeamento[nova_palavra.strip()] = nova_conta.strip()
                st.rerun()

# Exibe as regras cadastradas
if st.session_state.mapeamento:
    st.write("**Regras de Subcontas Ativas (Clique no botão para remover):**")
    cols = st.columns(4)
    for idx, (palavra, conta) in enumerate(st.session_state.mapeamento.items()):
        col_atual = cols[idx % 4]
        with col_atual:
            if st.button(f"❌ {palavra} ➡️ {conta}", key=f"del_{palavra}", use_container_width=True):
                del st.session_state.mapeamento[palavra]
                st.rerun()

st.markdown("---")

arquivo_carregado = st.file_uploader(
    "Selecione um arquivo de extrato em formato PDF para analisar", 
    type=["pdf"]
)

if arquivo_carregado:
    linhas = []
    try:
        with pdfplumber.open(arquivo_carregado) as pdf:
            for pagina in pdf.pages:
                texto_pagina = pagina.extract_text()
                if texto_pagina:
                    linhas.extend(texto_pagina.split('\n'))
    except Exception as e:
        st.error("Erro ao ler o arquivo PDF. Certifique-se de que não está corrompido.")
        st.stop()
    
    periodos_disponiveis = pre_analisar_meses(linhas)
    
    if periodos_disponiveis:
        opcoes_selecao = [f"{MESES_NOME[p[0]]} de {p[1]}" for p in periodos_disponiveis]
        
        if len(periodos_disponiveis) > 1:
            st.warning(f"⚠️ Atenção: Detectamos lançamentos de **{len(periodos_disponiveis)} meses diferentes** neste PDF!")
        
        periodo_escolhido = st.selectbox(
            "📅 Qual mês você deseja converter e exportar agora?",
            options=opcoes_selecao
        )
        
        index_escolhido = opcoes_selecao.index(periodo_escolhido)
        mes_filtro, ano_filtro = periodos_disponiveis[index_escolhido]
        
        chave_execucao = f"{arquivo_carregado.name}|{periodo_escolhido}"

        executar = st.button("▶️ Executar conversão", key="btn_executar", type="primary")

        if executar:
            registros = []
            for linha in linhas:
                res = processar_linha_caixa(
                    linha, cont_banco, cont_fornecedor, cont_cliente,
                    mes_filtro, ano_filtro, st.session_state.mapeamento
                )
                if res:
                    registros.append(res)

            if registros:
                df = pd.DataFrame(registros)
                df = df.iloc[::-1].reset_index(drop=True)  # Ordem cronológica crescente

                df['data'] = df['data'].astype(str)
                df['conta debito'] = df['conta debito'].astype(str)
                df['conta crédito'] = df['conta crédito'].astype(str)

                colunas_ordenadas = ['data', 'conta debito', 'conta crédito', 'valor', 'descrição']
                df = df[colunas_ordenadas]

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False)

                st.session_state.resultado = {
                    "chave": chave_execucao,
                    "df": df,
                    "excel": output.getvalue(),
                }
            else:
                st.session_state.resultado = {"chave": chave_execucao, "df": None, "excel": None}

        # Exibe o resultado da conversão de maneira controlada
        resultado = st.session_state.get("resultado")
        if resultado and resultado["chave"] == chave_execucao:
            if resultado["df"] is not None:
                # ALTERAÇÃO SOLICITADA: Exibe na tela apenas uma prévia das 5 primeiras linhas
