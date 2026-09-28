import os
import re
import io
import pandas as pd
import streamlit as st
from google import genai  # SDK oficial do Google

# Configuração da página do Streamlit
st.set_page_config(
    page_title="Conversor Contábil Inteligente com Gemini IA",
    page_icon="🤖",
    layout="wide"
)

# Inicialização do Cliente Gemini buscando o Token das Secrets do Streamlit
try:
    api_key = st.secrets["GEMINI_API_KEY"]
    client = genai.Client(api_key=api_key)
except Exception:
    st.error("🔑 Erro: Chave 'GEMINI_API_KEY' não configurada nos Secrets do Streamlit Cloud.")
    st.stop()

# Dicionário para conversão amigável de número do mês para nome em português
MESES_NOME = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
    5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
    9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
}

def pre_analisar_meses(linhas):
    """Identifica quais meses/anos possuem lançamentos válidos."""
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
    """Processa as linhas aplicando as regras contábeis, filtros de mês e mapeamento de subcontas."""
    padrao_data = r'^(\d{2})/(\d{2})/(\d{4})'
    match_data = re.search(padrao_data, linha)
    if not match_data:
        return None
        
    data_final = match_data.group(1)
    mes_linha = int(match_data.group(2))
    ano_linha = int(match_data.group(3))
    
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
    elif partes[-2] in ['D', 'C']:
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

    # --- MAPEAMENTO INTELIGENTE DE SUBCONTAS POR PALAVRA-CHAVE ---
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
st.title("🤖 Conversor Contábil Autônomo com Mapeamento de Histórico")
st.markdown("Arraste extratos em **PDF (Imagem ou Digital)**. A IA do Gemini fará a leitura e o sistema associará as contas.")

# 1. Configuração Fixa do Plano de Contas Padrão na Sidebar
st.sidebar.header("⚙️ Contas Padrão")
cont_banco = st.sidebar.text_input("Conta Banco:", value="6")
cont_fornecedor = st.sidebar.text_input("Transitória Fornecedor (Padrão D):", value="848")
cont_cliente = st.sidebar.text_input("Transitória Cliente (Padrão C):", value="861")

# 2. Painel Central de Regras para Subcontas customizadas por Histórico
st.markdown("### 🔍 Mapeamento Dinâmico de Subcontas")
st.write("Adicione palavras-chave encontradas na descrição do extrato para amarrar automaticamente a contas específicas (Ex: tarifas, concessionárias, impostos):")

# Inicializa o estado das regras de mapeamento para não sumir a cada clique
if 'mapeamento' not in st.session_state:
    st.session_state.mapeamento = {"IOF": "55", "JUROS": "56", "COELBA": "110", "CESTA SERVICO": "200"}

col_palavra, col_conta, col_btn = st.columns([3, 2, 1])
with col_palavra:
    nova_palavra = st.text_input("Palavra-chave no Histórico (Ex: IOF):", key="input_palavra")
with col_conta:
    nova_conta = st.text_input("Código da Conta Contábil Relacionada:", key="input_conta")
with col_btn:
    st.write("<style>.btn-align { margin-top: 28px; }</style>", unsafe_allow_html=True)
    if st.button("➕ Adicionar Regra", key="add_regra"):
        if nova_palavra and nova_conta:
            st.session_state.mapeamento[nova_palavra.strip()] = nova_conta.strip()
            st.rerun()

# Exibe as regras atualmente cadastradas em formato de tags administráveis
if st.session_state.mapeamento:
    st.write("**Regras de Subcontas Ativas:**")
    cols = st.columns(min(len(st.session_state.mapeamento), 4))
    for idx, (palavra, conta) in enumerate(st.session_state.mapeamento.items()):
        col_atual = cols[idx % 4]
        with col_atual:
            if st.button(f"❌ {palavra} ➡️ Conta {conta}", key=f"del_{palavra}"):
                del st.session_state.mapeamento[palavra]
                st.rerun()

st.markdown("---")

# Componente para carregar os PDFs
arquivo_carregado = st.file_uploader(
    "Selecione um extrato em formato PDF para processamento", 
    type=["pdf"]
)

if arquivo_carregado:
    linhas = []
    
    with st.spinner("🤖 O Gemini está analisando visualmente as páginas do PDF... Aguarde."):
        try:
            dados_pdf = arquivo_carregado.read()
            
            prompt_ocr = """
            Você é um leitor especialista em extratos bancários em formato de imagem/digitalizado.
            Extraia o texto de TODAS as transações financeiras contidas neste PDF.
            Para cada transação encontrada, retorne estritamente em uma única linha usando o seguinte formato textual:
            DD/MM/AAAA [Numero do documento se houver] [Histórico e nomes completos dos favorecidos] [Valor] [D ou C]
            
            Regras estritas:
            1. Preserve exatamente as letras "D" para débito/saídas e "C" para crédito/entradas conforme aparecem no papel.
            2. Não pule nenhuma linha de transação.
            3. Não adicione cabeçalhos, comentários, explicações ou formatações Markdown (como ``` ou tabelas). Retorne apenas as linhas cruas de texto.
            """
            
            resposta = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[
                    prompt_ocr,
                    {"mime_type": "application/pdf", "data": dados_pdf}
                ]
            )
            
            texto_extraido = resposta.text
            if texto_extraido:
                linhas = texto_extraido.split('\n')
                
        except Exception as e:
            st.error(f"Ocorreu um erro ao se comunicar com a API do Gemini: {e}")
            st.stop()
            
    # Executa a análise inteligente baseada no mapeamento de datas
    periodos_disponiveis = pre_analisar_meses(linhas)
    
    if periodos_disponiveis:
        opcoes_selecao = [f"{MESES_NOME[p[0]]} de {p[1]}" for p in periodos_disponiveis]
        
        if len(periodos_disponiveis) > 1:
            st.warning(f"⚠️ Atenção: A IA detectou lançamentos de **{len(periodos_disponiveis)} meses diferentes** neste documento!")
        
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
