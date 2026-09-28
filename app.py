import os
import re
import io
import pandas as pd
import streamlit as st

# Configuração inicial da página do Streamlit
st.set_page_config(
    page_title="Conversor Contábil - ERP",
    page_icon="📊",
    layout="wide"
)

def processar_linha_caixa(linha):
    """
    Trata cada linha do extrato brutos da Caixa Econômica,
    aplica filtros e as condicionais de amarração de Débito/Crédito.
    """
    padrao_data = r'^(\d{2}/\d{2}/\d{4})'
    if not re.search(padrao_data, linha):
        return None
        
    partes = list(filter(None, linha.split()))
    if len(partes) < 4:
        return None
        
    data = partes[0]
    texto_linha = " ".join(partes)
    
    # Filtra linhas redundantes de saldo
    if "SALDO DIA" in texto_linha or "SALDO ANTERIOR" in texto_linha:
        return None
        
    # Isola o tipo (D/C) e o valor
    tipo = None
    if partes[-1] in ['D', 'C']:
        tipo = partes[-1]
        valor_str = partes[-2]
    elif partes[-2] in ['D', 'C']:
        tipo = partes[-2]
        valor_str = partes[-3]
    else:
        if 'D' in partes[-1] and ',' in partes[-1]:
            tipo = 'D'
            valor_str = partes[-1].replace('D', '')
        elif 'C' in partes[-1] and ',' in partes[-1]:
            tipo = 'C'
            valor_str = partes[-1].replace('C', '')
        else:
            return None

    try:
        valor_limpo = valor_str.replace('.', '').replace(',', '.')
        valor_float = float(valor_limpo)
    except ValueError:
        return None

    # Captura o número do documento (padrão 6 dígitos Caixa)
    doc = "000000"
    for p in partes[1:5]:
        if p.isdigit() and len(p) == 6:
            doc = p
            break

    # Monta a descrição inteligível
    desc_partes = [p for p in partes if p not in [data, doc, valor_str, tipo] and not re.match(r'^\d{2}:\d{2}:\d{2}\$', p)]
    if len(desc_partes) > 0 and desc_partes[-1] in ['C', 'D']:
        desc_partes.pop()
    
    descricao_final = f"{' '.join(desc_partes)} (Doc: {doc})"

    # CRITÉRIO CONTÁBIL:
    # Se valor negativo (D): Débito = 848 / Crédito = 6
    # Se valor positivo (C): Débito = 6 / Crédito = 861
    if tipo == 'D':
        conta_debito = "848"
        conta_credito = "6"
    else:
        conta_debito = "6"
        conta_credito = "861"

    # Formata a casa decimal utilizando vírgula conforme exigido pelo ERP
    valor_com_virgula = f"{valor_float:.2f}".replace('.', ',')

    return {
        'data': data,
        'conta debito': conta_debito,
        'conta crédito': conta_credito,
        'valor': valor_com_virgula,
        'descrição': descricao_final
    }

# --- INTERFACE VISUAL STREAMLIT ---
st.title("📊 Conversor de Extratos para ERP Contábil")
st.markdown("""
Esta aplicação processa os arquivos de texto (`.txt`) extraídos do OCR dos seus PDFs de imagem da Caixa, 
limpa as linhas informativas, reordena de forma cronológica e amarra as contas contábeis automaticamente.
""")

st.sidebar.header("Regras Aplicadas")
st.sidebar.info("""
- **Saídas (Negativos):** D = 848 | C = 6
- **Entradas (Positivos):** D = 6 | C = 861
- **Data:** Texto corrido (`dd/mm/aaaa`)
- **Decimais:** Separados por vírgula ( `,` )
""")

# Componente nativo do Streamlit para upload de arquivos
arquivos_carregados = st.file_uploader(
    "Arraste ou selecione os arquivos de texto (.txt) gerados pelo OCR do extrato", 
    type=["txt"], 
    accept_multiple_files=True
)

if arquivos_carregados:
    st.success(f"{len(arquivos_carregados)} arquivo(s) carregado(s) com sucesso!")
    
    for arquivo in arquivos_carregados:
        st.subheader(f"📄 Processando: {arquivo.name}")
        
        # Lê o conteúdo do arquivo enviado
        string_data = arquivo.read().decode("utf-8")
        linhas = string_data.split('\n')
        
        registros = []
        for linha in linhas:
            res = processar_linha_caixa(linha.strip())
            if res:
                registros.append(res)
                
        if registros:
            # Estrutura no Pandas
            df = pd.DataFrame(registros)
            
            # Inverte para ordem cronológica (do mais antigo ao mais recente)
            df = df.iloc[::-1].reset_index(drop=True)
            
            # Força as colunas para formato string/texto
            df['data'] = df['data'].astype(str)
            df['conta debito'] = df['conta debito'].astype(str)
            df['conta crédito'] = df['conta crédito'].astype(str)
            
            colunas_ordenadas = ['data', 'conta debito', 'conta crédito', 'valor', 'descrição']
            df = df[colunas_ordenadas]
            
            # Exibe a prévia dos dados tratados na interface
            st.dataframe(df, use_container_width=True)
            
            # Cria o buffer do Excel em memória para disponibilizar para download
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            dados_excel = output.getvalue()
            
            # Botão de download dinâmico gerado pelo Streamlit
            nome_saida = f"{os.path.splitext(arquivo.name)[0]}_pronto_ERP.xlsx"
            st.download_button(
                label=f"📥 Baixar Planilha do Excel para {arquivo.name}",
                data=dados_excel,
                file_name=nome_saida,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            st.markdown("---")
        else:
            st.warning(f"Nenhum lançamento válido foi identificado dentro de {arquivo.name}. Verifique a qualidade do OCR.")

