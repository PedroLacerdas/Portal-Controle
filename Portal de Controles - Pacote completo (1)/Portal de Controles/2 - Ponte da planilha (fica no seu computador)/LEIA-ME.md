# API Planilha → App

Lê a planilha Excel do OneDrive e alimenta o app (Floculantes, e o mesmo serve para Britadores).
O que é lançado no tablet fica guardado num banco SQLite (`dados.db`, nesta pasta). A planilha só é **lida**, nunca alterada.

Custo: **zero**. Python, Flask, openpyxl, SQLite e Waitress são gratuitos e de código aberto.

```
Planilha no OneDrive ──(leitura a cada 5 min)──► API (Python) ◄──► app no tablet / navegador
                                                  └─ dados.db (lançamentos do app)
```

---

## 1. Instalar (uma vez)

1. Instale o **Python 3.11 ou mais novo**: https://www.python.org/downloads/
   Na instalação, marque **"Add python.exe to PATH"**.
2. Copie a pasta `api_planilha` para o computador que vai rodar a API.
   Use um computador que **fique ligado** e que **tenha o OneDrive sincronizado** com a pasta da planilha.
3. Dê dois cliques em **`iniciar.bat`**. Na primeira vez ele instala tudo sozinho (precisa de internet) e depois inicia a API.

Para conferir, abra no navegador: `http://localhost:8000/saude`
Deve aparecer algo como `{"erro": null, "linhas_lidas": 12, ...}`.

## 2. Configurar (`config.json`)

### Onde está a planilha
- **`"modo": "local"`** (recomendado): a API lê o arquivo da pasta do OneDrive sincronizada no computador.
  Em `"arquivo"`, coloque o caminho completo, com barras `/`. Para descobrir o caminho: clique com o botão direito no arquivo no Explorador → **Copiar como caminho**.
  Exemplo: `"C:/Users/Pedro.lacerda/OneDrive - Mineral do Brasil/Controles/Floculantes.xlsx"`
- **`"modo": "graph"`**: a API baixa a planilha direto da nuvem (veja a seção 5).

### Quais abas e colunas viram dados no app (`mapeamentos`)
Cada item liga **uma aba** da planilha a **uma coleção** do app:

| Campo | O que é |
|---|---|
| `aba` | nome da aba no Excel (ex.: `Turnos`) |
| `linha_cabecalho` | linha onde estão os títulos das colunas (normalmente 1) |
| `colecao` | coleção do app: `registros` (turnos), `entradas` (estoque), `testes` |
| `chave` | colunas que identificam a linha sem repetir (ex.: Data + Turno) |
| `colunas` | `"Título no Excel": {"campo": "nome no app", "tipo": "data" / "numero" / "texto" / "simnao"}` |

Campos que o app de Floculantes usa:

| Coleção | Campos |
|---|---|
| `registros` (turno) | `data`, `turno` (X/Y/Z), `litros`, `ton`, `conc` |
| `entradas` (estoque) | `data`, `kg`, `lote`, `coleta` (true/false), `coletaKg`, `obs` |
| `testes` | `data`, `produto`, `doseGt`, `conc`, `resultado`, `status` |

Os títulos das colunas não precisam ser exatos em acentos e maiúsculas: "Concentração", "CONCENTRACAO" e "concentração" são aceitos.
Números com vírgula ("9.100,5") e datas como texto ("21/10/2026") são convertidos automaticamente. Use o tipo `simnao` para colunas como "Houve coleta?" (aceita Sim/Não, S/N ou X).

**Dica:** mantenha cada aba como uma tabela simples, com a linha de títulos no topo e um registro por linha, sem células mescladas.

### Planilha no formato "Relatório de Produção e Operação" (uma aba por turno)
É o formato atual de Floculantes: abas como `21-10X`, `21-10Y`, `20-10Z`, cada uma com `Data:` e `Turno:` no cabeçalho, a coluna **Floculante (L)** e a coluna de toneladas, ambas com linha de **Total**. Abas `MODELO (...)` são ignoradas.

```json
{
  "tipo": "relatorio_turno",
  "colecao": "registros",
  "abas_padrao": "^\\d{2}-\\d{2}[XYZ]$",
  "rotulo_data": "Data:",
  "rotulo_turno": "Turno:",
  "coluna_volume": "Floculante (L)",
  "coluna_toneladas": "Rej.Baia",
  "toneladas_so_positivos": true,
  "concentracao": 0.1
}
```
- `coluna_volume` / `coluna_toneladas`: título da coluna na planilha. A API pega o valor da linha **Total**; se estiver vazia, soma as horas.
- `toneladas_so_positivos`: soma só as horas com valor positivo e ignora o Total da coluna (na Rej. Baia, as horas sem operação aparecem como -140 e distorcem o Total).
- `concentracao`: concentração da solução (%) usada para transformar litros em kg (a planilha não traz esse dado).
- Aba de turno ainda sem floculante lançado é ignorada até ter valores.

### Enviar para a nuvem (Portal no Azure)
Se o Portal de Controles estiver publicado no Azure, preencha no `config.json`:
```json
"nuvem": { "url": "https://SEU-SITE.azurestaticapps.net/api/floculantes", "token": "mesma senha do API_TOKEN" }
```
A cada leitura da planilha, os turnos novos ou alterados são enviados para a nuvem (a API faz isso sozinha, mesmo sem ninguém acessar). O status aparece em `/saude`, no item `nuvem`.
Para o app de Britadores usar esta API local, coloque `/britadores` no fim do endereço (ex.: `http://192.168.2.66:8000/britadores`); assim os dados dos dois apps não se misturam.

### Planilha Mestre (Britadores e Floculantes)
O `config.json` já vem com as abas da **Planilha Mestre - Controles.xlsx** mapeadas (Granulometria, Eventos Britadores, Estoque, Testes e Turnos).
- `"arquivo"` pode ser uma **lista** de caminhos: um para os relatórios de turno, outro para a Planilha Mestre.
- `"arquivo_contem"` diz de qual arquivo cada aba é lida.
- `"ativo": false` desliga um mapeamento (a aba Turnos da mestre vem desligada porque os turnos já saem do Relatório de turno).
- Linhas com a palavra **EXEMPLO** e linhas sem os campos-chave (data, britador, teste...) são ignoradas.
- Cada mapeamento só apaga do app os registros que ele mesmo criou.

### Outras opções
- `intervalo_leitura_seg`: de quanto em quanto tempo a planilha é relida (padrão 300 = 5 min).
- `porta`: porta da API (padrão 8000).
- `token_app`: senha opcional. Se preencher, coloque a mesma em `SERVIDOR.token` no app.

## 3. Ligar o app à API

No `index.html` do app, no bloco `SERVIDOR`:

```js
const SERVIDOR = {
  url: "https://endereco-da-api",   // o endereço da API (veja a seção 4)
  token: "",                         // igual ao token_app, se usar
  intervaloSeg: 60
};
```

## 4. HTTPS (importante)

O app é publicado em **https** (é o que permite abrir offline). Um site https **não consegue chamar uma API em http** (o navegador bloqueia). Então a API precisa ter um endereço https. Opções sem custo:

1. **TI da empresa**: pedir um endereço interno com certificado (por exemplo, `https://api-controles.empresa.local`) apontando para o computador da API. É o caminho mais adequado em ambiente corporativo.
2. **Cloudflare Tunnel** (gratuito): cria um endereço https público para a API sem abrir portas no firewall. Confirme com o TI antes, porque expõe a API na internet. Nesse caso, **preencha o `token_app`**.

Para testes no próprio computador, `http://localhost:8000` funciona com o app aberto também em `http://localhost`.

## 5. Modo "graph" (opcional, sem pasta sincronizada)

Use só se o computador da API **não** tiver o OneDrive sincronizado.

1. No portal do Azure (https://entra.microsoft.com) → **Registros de aplicativo** → **Novo registro**. É gratuito, mas em empresa normalmente precisa do TI.
2. Anote o **ID do aplicativo (cliente)** e o **ID do diretório (locatário)** e cole em `graph.client_id` e `graph.tenant_id`.
3. Em **Autenticação**, ative **"Permitir fluxos de cliente público"**.
4. Em **Permissões de API**, adicione **Microsoft Graph → Delegada → Files.Read**.
5. Em `graph.caminho_no_onedrive`, coloque o caminho a partir da raiz do seu OneDrive (ex.: `Controles/Floculantes.xlsx`).
6. Uma única vez, rode `.venv\Scripts\python app.py --login` e entre com sua conta Microsoft no endereço mostrado.
7. Mude `"modo"` para `"graph"` e inicie com `iniciar.bat`.

## 6. Como funciona a sincronização

- **Planilha → app:** linhas novas ou alteradas aparecem no app na próxima sincronização. Linhas apagadas da planilha somem do app.
- **App → banco:** o que é lançado no tablet é gravado no `dados.db` e enviado aos outros aparelhos. A planilha **não** é alterada.
- **Mesma linha editada nos dois lados:** se alguém corrigir no app um registro que veio da planilha, a correção vale até a linha da planilha mudar de novo. Nesse caso, a planilha vence.
- **Backup:** copie o arquivo `dados.db` de tempos em tempos (ele guarda tudo o que foi lançado no app).

## 7. Deixar rodando sempre

Para a API iniciar junto com o Windows: tecle `Win + R`, digite `shell:startup` e coloque ali um **atalho** para o `iniciar.bat`.
Em servidor, o TI pode configurar como serviço (por exemplo, com o NSSM, também gratuito).

## Problemas comuns

| Mensagem em `/saude` | O que fazer |
|---|---|
| `FileNotFoundError` | Confira o caminho em `local.arquivo` e se o OneDrive terminou de sincronizar. |
| `Aba "X" não encontrada` | O nome da aba no `config.json` está diferente do Excel. |
| `Coluna "X" não encontrada` | O título da coluna ou a `linha_cabecalho` está diferente. |
| `PermissionError` | A planilha está aberta e bloqueada. Feche-a ou aguarde o OneDrive. |
