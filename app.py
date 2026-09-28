import os
import re
import io
import pandas as pd
import streamlit as st
import pdfplumber  # Engine de extração local para PDFs escaneados/imagem

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
        match = re.search(padrao_data, linha.strip())
        if match:
            if "SALDO DIA" in linha or "SALDO ANTERIOR" in linha:
                continue
            mes = int(match.group(2))
            ano = int(match.group(3))
            meses_encontrados.add((mes, ano))
            
    return sorted(list(meses_encontrados), key=lambda x: (x[1], x[0]))

def processar_linha_caixa(linha, conta_banco, conta_fornecedor, conta_cliente, mes_filtro, ano_filtro, regras_mapeamento):
    """
    Processa as linhas aplicando as regras contábeis, filtros de mês e mapeamento de subcontas.
    """
    padrao_data = r'^(\d{2})/(\d{2})/(\d{4})'
    match_data = re.search(padrao_data, linha)
    if not match_data:
        return None
        
    data_final = match_data.group(1)
    mes_linha = int(match_data.group(2))
    ano_linha = int(match_data.group(3))
    
    # Filtro de período escolhido
    if mes_linha != mes_filtro or ano_linha != ano_filtro:
        return None
        
    partes = list(filter(None, linha.split()))
    if len(partes) < 4:
        return None
        
    texto_linha = " ".join(partes)
    
    if "SALDO DIA" in texto_linha or "SALDO ANTERIOR" in texto_linha:
        return None
        
    tipo = None
    valor_str = ""
    
    if partes[-1] in ['D', 'C']:
        tipo = partes[-1]
        valor_str = partes[-2]
    elif widget_index := len(partes) > 1 and partes[-2] in ['D', 'C']:
        tipo = partes[-2]
        valor_str = partes[-3]
    else:
        if partes[-1].endswith('D') and ',' in partes[-1]:
            tipo = 'D'
            valor_str = partes[-1][:-1]
        elif partes[-1].endswith('C') and ',' in partes[-1]:
            tipo = 'C'
            valor_str = partes[-1][:-1]
        else:
            return None

    try:
        valor_limpo = valor_str.replace('.', '').replace(',', '.')
        valor_float = float(valor_limpo)
    except ValueError:
        return None

    doc = "000000"
    for p in partes[1:5]:
        if p.isdigit() and len(p) == 6:
            doc = p
            break

    sub_hora = r'\b\d{2}:\d{2}(:\d{2})?\b'
    elementos_remover = [f"{data_final}/{mes_linha:02d}/{ano_linha}", doc, valor_str, tipo, 'D', 'C']
    
    palavras_desc = []
    for p in partes:
        if re.match(sub_hora, p) or p in elementos_remover:
            continue
        p_limpo = p.replace('*', '').replace(',', '').strip()
        if p_limpo:
            palavras_desc.append(p_limpo)

    texto_complementar = " ".join(palavras_desc).strip()
    texto_complementar = re.sub(r'\s+', ' ', texto_complementar)
    descricao_final = f"{texto_complementar} (Doc: {doc})"

    # --- MAPEAMENTO DE SUBCONTAS POR PALAVRA-CHAVE ---
    conta_mapeada = None
    for palavra, conta in regras_mapeamento.items():
        if palavra.upper() in descricao_final.upper():
            conta_mapeada = conta
            break

    # Se o valor for negativo (saída/D): Débito assume a contrapartida | Crédito assume o Banco
    if tipo == 'D':
        conta_debito = conta_mapeada if conta_mapeada else conta_fornecedor
        conta_credito = conta_banco
    # Se o valor for positivo (entrada/C): Débito assume o Banco | Crédito assume a contrapartida
    else:
        conta_debito = conta_banco
        conta_credito = conta_mapeada if conta_mapeada else conta_cliente

    valor_com_virgula = f"{valor_float:.2f}".replace('.', ',')
    data_formatada = f"{data_final}/{mes_linha:02d}/{ano_linha}"

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
st.write("Adicione palavras-chave encontradas na descrição do extrato para amarrar automaticamente a contas específicas (Ex: tarifas, concessionárias, impostos):")

# Inicializa o estado das regras de mapeamento na sessão do Streamlit
if 'mapeamento' not in st.session_state:
    st.session_state.mapeamento = {"IOF": "55", "JUROS": "56", "COELBA": "110", "CESTA SERVICO": "200"}

col_palavra, col_conta, col_btn = st.columns([2, 2, 1])
with col_palavra:
    nova_palavra = st.text_input("Palavra-chave no Histórico (Ex: IOF):", key="input_palavra")
with col_conta:
    nova_conta = st.text_input("Código da Conta Contábil Relacionada:", key="input_conta")
with col_btn:
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("➕ Adicionar Regra", key="add_regra", use_container_width=True):
        if nova_palavra and nova_conta:
            st.session_state.mapeamento[nova_palavra.strip()] = nova_conta.strip()
            st.rerun()

# Exibe as regras atualmente cadastradas em formato de tags administráveis
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

# Componente para carregar os PDFs (Leitura nativa e local)
arquivo_carregado = st.file_uploader(
    "Selecione um arquivo de extrato em formato PDF para analisar", 
    type=["pdf"]
)

if arquivo_carregado:
    linhas = []
    try:
        # Abre o PDF usando pdfplumber de forma 100% local
        with pdfplumber.open(arquivo_carregado) as pdf:
            for pagina in pdf.pages:
                texto_pagina = pagina.extract_text()
                if texto_pagina:
                    linhas.extend(texto_pagina.split('\n'))
    except Exception as e:
        st.error(f"Erro ao ler o arquivo PDF. Certifique-se de que não está corrompido.")
        st.stop()
    
    # Executa a pré-análise baseada no mapeamento de datas
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
        
        # Envia as regras salvas em sessão para dentro do tratador de linhas
        registros = []
        for linha in linhas:
            res = processar_linha_caixa(
                linha.strip(), cont_banco, cont_fornecedor, cont_cliente, 
                mes_filtro, ano_filtro, st.session_state.mapeamento
            )
            if res:
                registros.append(res)
                
        if registros:
            df = pd.DataFrame(registros)
            df = df.iloc[::-1].reset_index(drop=True) # Mantém ordem cronológica crescente
            
            df['data'] = df['data'].astype(str)
            df['conta debito'] = df['conta debito'].astype(str)
            df['conta crédito'] = df['conta crédito'].astype(str)
            
            colunas_ordenadas = ['data', 'conta debito', 'conta crédito', 'valor', 'descrição']
            df = df[colunas_ordenadas]
            
            st.markdown(f"### 👀 Prévia da Importação Contábil - Período: `{periodo_escolhido}`")
            st.dataframe(df, use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            dados_excel = output.getvalue()
            
            nome_saida = f"{os.path.splitext(arquivo_carregado.name)[0]}_{periodo_escolhido.replace(' ', '_')}.xlsx"
            st.download_button(
                label=f"📥 Baixar Planilha Pronta para o ERP ({periodo_escolhido})",
                data=dados_excel,
                file_name=nome_saida,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info(f"Nenhum lançamento contábil processado para o período {periodo_escolhido}.")
    else:
