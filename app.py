import os
import re
import io
import pandas as pd
import streamlit as st
from pypdf import PdfReader  # Nova biblioteca para ler o PDF diretamente

# Configuração da página do Streamlit
st.set_page_config(
    page_title="Conversor Contábil Inteligente",
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

def processar_linha_caixa(linha, conta_banco, conta_fornecedor, conta_cliente, mes_filtro, ano_filtro):
    """
    Processa as linhas filtrando rigorosamente pelo mês e ano selecionados pelo usuário.
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

    # Regra contábil informada
    if tipo == 'D':
        conta_debito = conta_fornecedor
        conta_credito = conta_banco
    else:
        conta_debito = conta_banco
        conta_credito = conta_cliente

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
st.title("📊 Conversor Contábil de PDFs Direto")
st.markdown("Agora você pode arrastar os seus arquivos **PDF** diretamente aqui sem precisar converter para texto antes.")

# Configuração fixa do plano de contas na sidebar
st.sidebar.header("⚙️ Plano de Contas")
cont_banco = st.sidebar.text_input("Conta Banco:", value="6")
cont_fornecedor = st.sidebar.text_input("Transitória Fornecedor:", value="848")
cont_cliente = st.sidebar.text_input("Transitória Cliente:", value="861")

# Alterado para aceitar arquivos PDF nativamente
arquivo_carregado = st.file_uploader(
    "Selecione um arquivo de extrato em formato PDF para analisar", 
    type=["pdf"]
)

if arquivo_carregado:
    linhas = []
    try:
        # Lê o PDF diretamente da memória do Streamlit
        leitor_pdf = PdfReader(arquivo_carregado)
        for pagina in leitor_pdf.pages:
            texto_pagina = pagina.extract_text()
            if texto_pagina:
                linhas.extend(texto_pagina.split('\n'))
    except Exception as e:
        st.error(f"Erro ao ler o arquivo PDF. Certifique-se de que não está corrompido.")
        st.stop()
    
    # Executa a pré-análise para mapear os meses reais contidos no arquivo
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
        
        registros = []
        for linha in linhas:
            res = processar_linha_caixa(linha.strip(), cont_banco, cont_fornecedor, cont_cliente, mes_filtro, ano_filtro)
            if res:
                registros.append(res)
                
        if registros:
            df = pd.DataFrame(registros)
            df = df.iloc[::-1].reset_index(drop=True) # Ordem cronológica correta
            
            df['data'] = df['data'].astype(str)
            df['conta debito'] = df['conta debito'].astype(str)
            df['conta crédito'] = df['conta crédito'].astype(str)
            
            colunas_ordenadas = ['data', 'conta debito', 'conta crédito', 'valor', 'descrição']
            df = df[colunas_ordenadas]
            
            st.markdown(f"### 👀 Prévia da Importação - Período: `{periodo_escolhido}`")
            st.dataframe(df, use_container_width=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            dados_excel = output.getvalue()
            
            nome_saida = f"{os.path.splitext(arquivo_carregado.name)[0]}_{periodo_escolhido.replace(' ', '_')}.xlsx"
            st.download_button(
                label=f"📥 Baixar Planilha do Excel ({periodo_escolhido})",
                data=dados_excel,
                file_name=nome_saida,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.info(f"Nenhum lançamento encontrado para o período {periodo_escolhido}.")
    else:
        st.error("Não conseguimos ler texto dentro deste PDF. Se ele for um PDF escaneado (imagem pura), você precisará rodar um OCR nele antes, ou podemos integrar um leitor de imagem (OCR) diretamente neste script.")
