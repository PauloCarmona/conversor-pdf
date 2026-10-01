import os
import re
import pandas as pd
import streamlit as st

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
        linha_limpa = linha.strip().replace('|', ' ')
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
    Ignora lançamentos sem valor definido ou com valor igual a zero.
    """
    linha_limpa = linha.strip().replace('|', ' ')
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
        
    partes_linha = list(filter(None, linha_limpa.split()))
    if len(partes_linha) < 2:
        return None

    tipo = None
    valor_str = ""
    
    # Identifica indicador D ou C na linha varrendo as colunas
    for i, parte in enumerate(partes_linha):
        partes_clean = parte.strip().upper()
        if partes_clean in ['D', 'C']:
            tipo = partes_clean
            if i > 0:
                valor_str = partes_linha[i-1]
            break
        elif partes_clean.endswith('D') and ',' in partes_clean:
            tipo = 'D'
            valor_str = partes_clean[:-1]
            break
        elif partes_clean.endswith('C') and ',' in partes_clean:
            tipo = 'C'
            valor_str = partes_clean[:-1]
            break

    # Se o tipo ou valor não forem informados, passa para a próxima linha
    if not tipo or not valor_str:
        return None

    try:
        valor_limpo = valor_str.replace('.', '').replace(',', '.')
        valor_float = float(valor_limpo)
        
        # Ignora lançamentos com valor zerado
        if valor_float == 0:
            return None
    except ValueError:
        return None

    doc = "000000"
    for p in partes_linha:
        p_clean = p.replace('-', '').replace('/', '').strip()
        if p_clean.isdigit() and len(p_clean) == 6:
            doc = p_clean
            break

    sub_hora = r'\b\d{2}:\d{2}(:\d{2})?\b'
    elementos_remover = [doc, valor_str, tipo, 'D', 'C', '-', '–']
    
    palavras_desc = []
    for p in partes_linha:
        if re.search(sub_hora, p) or p in elementos_remover or any(dt in p for dt in [f"{dia_final}/{mes_linha:02d}", str(ano_linha)]):
            continue
        p_limpo = p.replace('*', '').strip()
        if p_limpo and p_limpo not in ['D', 'C', '-', '–']:
            palavras_desc.append(p_limpo)

    texto_complementar = " ".join(palavras_desc).strip()
    texto_complementar = re.sub(r'\s+', ' ', texto_complementar)
    texto_complementar = re.sub(r'\b\d{1,3}(\.\d{3})*,\d{2}\b', '', texto_complementar).strip()
    
    # Remove ponto e vírgula da descrição para evitar quebra de colunas no TXT
    descricao_final = f"{texto_complementar} (Doc: {doc})".replace(';', ' ')

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

    data_formatada = f"{dia_final}/{mes_linha:02d}/{ano_linha}"

    return {
        'data': data_formatada,
        'conta_debito': conta_debito,
        'conta_credito': conta_credito,
        'valor': valor_float,
        'descricao': descricao_final
    }

def gerar_conteudo_txt(registros):
    """
    Monta diretamente as linhas do arquivo TXT no formato exigido para importação:
    Data;ContaDebito;ContaCredito;Valor;Descricao
    Valor numérico formatado com 2 casas decimais, sem separador de milhar e com vírgula decimal.
    """
    linhas_txt = []
    for r in registros:
        valor_formatado = f"{r['valor']:.2f}".replace('.', ',')
        linha = f"{r['data']};{r['conta_debito']};{r['conta_credito']};{valor_formatado};{r['descricao']}"
        linhas_txt.append(linha)
    
    return "\r\n".join(linhas_txt)

# --- PAINEL VISUAL STREAMLIT ---
st.page_link("painel.py", label="Voltar ao painel", icon="🏠")
st.title("📊 Conversor Contábil TXT")
st.markdown("Arraste extratos bancários em formato **Bloco de Notas (.txt)** para processamento contábil local.")

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

# Seletor de Arquivo TXT Único
arquivo_carregado = st.file_uploader(
    "Selecione um arquivo TXT de extrato para analisar", 
    type=["txt"],
    accept_multiple_files=False
)

if not arquivo_carregado and "resultado" in st.session_state:
    del st.session_state.resultado

if arquivo_carregado:
    if isinstance(arquivo_carregado, list):
        arquivo_carregado = arquivo_carregado[0] if len(arquivo_carregado) > 0 else None

    if arquivo_carregado:
        linhas = []
        
        try:
            string_data = arquivo_carregado.read().decode("utf-8", errors="ignore")
            linhas = string_data.split('\n')
        except Exception as e:
            st.error(f"Erro ao ler o arquivo TXT: {e}")
            st.stop()
        
        periodos_disponiveis = pre_analisar_meses(linhas)
        
        if periodos_disponiveis:
            opcoes_selecao = [f"{MESES_NOME[p[0]]} de {p[1]}" for p in periodos_disponiveis]
            
            if len(periodos_disponiveis) > 1:
                st.warning(f"⚠️ Atenção: Detectamos lançamentos de **{len(periodos_disponiveis)} meses diferentes** no extrato!")
            
            periodo_escolhido = st.selectbox(
                "📅 Qual mês você deseja converter e exportar agora?",
                options=opcoes_selecao
            )
            
            executar = st.button("▶️ Executar conversão", key="btn_executar", type="primary")

            if executar:
                index_escolhido = opcoes_selecao.index(periodo_escolhido)
                mes_filtro, ano_filtro = periodos_disponiveis[index_escolhido]
                
                registros = []
                for linha in linhas:
                    res = processar_linha_caixa(
                        linha, cont_banco, cont_fornecedor, cont_cliente,
                        mes_filtro, ano_filtro, st.session_state.mapeamento
                    )
                    if res:
                        registros.append(res)

                if registros:
                    # Exibe a prévia na tela com a coluna Valor formatada com vírgula
                    df_preview = pd.DataFrame(registros)
                    df_preview.columns = ['Data', 'Conta Débito', 'Conta Crédito', 'Valor', 'Descrição']
                    df_preview['Valor'] = df_preview['Valor'].apply(lambda v: f"{v:.2f}".replace('.', ','))
                    
                    st.dataframe(df_preview, use_container_width=True)
                    
                    # Gera a string do arquivo TXT final
                    conteudo_txt = gerar_conteudo_txt(registros)
                    txt_bytes = conteudo_txt.encode('utf-8-sig')
                    
                    col_down1, col_down2 = st.columns(2)
                    
                    with col_down1:
                        st.download_button(
                            label="📥 Descarregar Arquivo .TXT de Importação",
                            data=txt_bytes,
                            file_name=f"extrato_importacao_{mes_filtro:02d}_{ano_filtro}.txt",
                            mime="text/plain",
                            type="primary",
                            use_container_width=True
                        )
                        
                    with col_down2:
                        st.download_button(
                            label="📄 Descarregar CSV Para Conferência",
                            data=txt_bytes,
                            file_name=f"extrato_conferencia_{mes_filtro:02d}_{ano_filtro}.csv",
                            mime="text/csv",
                            use_container_width=True
                        )
                else:
                    st.warning("Nenhum lançamento válido foi encontrado para o período selecionado.")