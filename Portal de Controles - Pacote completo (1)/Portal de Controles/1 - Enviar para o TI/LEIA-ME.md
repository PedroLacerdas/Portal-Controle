# Portal de Controles no Azure

Site com o **Portal**, o **Controle de Britadores**, o **Controle de Floculantes**, o **Relatório de Turno** e o **Controle IBM**, com login de conta Microsoft, API em Python e banco **Azure Cosmos DB**. Os apps continuam funcionando **offline** nos tablets e sincronizam quando a rede volta.

```
Tablets / computadores ──https──► Azure Static Web Apps (plano Free)
                                    ├─ /             Portal
                                    ├─ /britadores/  app
                                    ├─ /floculantes/ app
                                    ├─ /relatorio/   Relatório de Turno
                                    ├─ /ibm/         Controle IBM
                                    ├─ /itm/         Controle ITM
                                    └─ /api/...      API Python  ──►  Azure Cosmos DB (plano gratuito)
Planilha no OneDrive ─► API do computador (ponte) ─► /api/floculantes/sync
```

Custo: **zero** se seguir os passos (plano Free do Static Web Apps, plano gratuito do Cosmos DB com limite de capacidade ligado e GitHub gratuito).
**Não precisa instalar nada no computador**: tudo é feito pelo navegador.

---

## Passo 1. Criar o banco (Azure Cosmos DB)

1. Entre em **portal.azure.com** → **Criar um recurso** → procure **Azure Cosmos DB** → **Criar** → escolha **Azure Cosmos DB for NoSQL**.
2. Aba **Básico**:
   - **Assinatura / Grupo de recursos**: os liberados pelo TI.
   - **Nome da conta**: por exemplo `cosmos-controles-mb` (só letras minúsculas, números e hífen).
   - **Local**: `Brazil South`.
   - **Modo de capacidade**: **Taxa de transferência provisionada**.
   - **Aplicar desconto do nível gratuito**: **Aplicar**. *(Se não aparecer, a assinatura já tem uma conta gratuita; peça ao TI.)*
   - **Limitar a taxa de transferência total da conta**: **marcado**. Isso garante que nunca haverá cobrança.
3. **Revisar + criar** → **Criar**. Leva alguns minutos.
4. Abra a conta criada → **Data Explorer** → **New Container**:
   - **Database id**: `controles` → marque **Share throughput across containers** → **Manual** → **400** RU/s.
   - **Container id**: `registros`
   - **Partition key**: `/sistema`
   - **OK**.
5. Vá em **Chaves** (Keys) e copie a **PRIMARY CONNECTION STRING**. Você vai usar no passo 3.
   **Não compartilhe essa chave** (não mande por e-mail ou chat).

## Passo 2. Colocar os arquivos no GitHub

O Azure publica o site direto de um repositório do GitHub.

1. Crie uma conta gratuita em **github.com** (pode usar o e-mail da empresa).
2. **New repository** → nome `controles-mb` → marque **Private** → **Create repository**.
3. Clique em **uploading an existing file** e **arraste o conteúdo desta pasta** (`index.html`, `staticwebapp.config.json`, as pastas `api`, `britadores`, `floculantes`, `relatorio`, `ibm` e `itm`). Arraste as pastas inteiras; o GitHub mantém a estrutura.
4. **Commit changes**.

## Passo 3. Criar o site (Azure Static Web Apps)

1. **portal.azure.com** → **Criar um recurso** → **Static Web App** → **Criar**.
2. Aba **Básico**:
   - **Grupo de recursos**: o mesmo do banco.
   - **Nome**: por exemplo `controles-mb`.
   - **Tipo de plano**: **Free**.
   - **Origem**: **GitHub** → **Entrar com o GitHub** → escolha a organização/conta, o repositório `controles-mb` e o branch `main`.
   - **Predefinições de build**: **Custom**
     - **Local do aplicativo**: `/`
     - **Local da API**: `api`
     - **Local de saída**: deixe em branco
3. **Revisar + criar** → **Criar**. O GitHub publica sozinho em 3 a 5 minutos (aba **Actions** do repositório mostra o andamento).
4. No Static Web App criado → **Configurações → Variáveis de ambiente** → adicione:

   | Nome | Valor |
   |---|---|
   | `COSMOS_CONEXAO` | a connection string copiada no passo 1 |
   | `API_TOKEN` | uma senha longa inventada por você (ex.: 30 letras e números). A ponte da planilha usa ela. |

   **Aplicar / Salvar**.
5. Na **Visão geral**, copie a **URL** (algo como `https://nome-aleatorio.azurestaticapps.net`).

**Teste**: abra `URL/api/saude`. Deve aparecer `"banco": "ok"`. Depois abra a URL: ela pede login com conta Microsoft e mostra o Portal.

## Passo 4. Quem pode entrar (recomendado)

Do jeito que vem, **qualquer conta Microsoft** que fizer login entra (inclusive contas pessoais). Para liberar só para a equipe:

1. No Static Web App → **Gerenciamento de função** (Role management) → **Convidar**:
   - **Provedor**: Microsoft Entra ID; **Detalhes do convidado**: o e-mail da pessoa; **Função**: `controles`.
   - Mande o link gerado para a pessoa abrir uma vez. Repita para cada usuário (e para a conta usada nos tablets).
2. No GitHub, edite o arquivo `staticwebapp.config.json` e troque, na última rota, `"authenticated"` por `"controles"`:
   ```json
   { "route": "/*", "allowedRoles": ["controles"] }
   ```
3. Em **Variáveis de ambiente**, adicione `PAPEL_EXIGIDO` = `controles`.

Assim só quem foi convidado vê o site e consegue gravar dados.

## Passo 5. Ligar a planilha (ponte)

No computador onde a API da planilha já roda, abra o `config.json` da pasta `api_planilha` e preencha o bloco `nuvem`:

```json
"nuvem": {
  "url": "https://SEU-SITE.azurestaticapps.net/api/floculantes",
  "token": "a mesma senha colocada em API_TOKEN"
},
```

Feche e abra o `iniciar.bat`. A cada leitura da planilha (5 min), os turnos novos ou alterados são enviados para a nuvem. Confira em `http://localhost:8000/saude`: o item `nuvem` deve mostrar `enviado_em` com a hora e `erro: null`.

## Passo 6. Usar nos tablets e computadores

1. Abra a URL do site no Chrome ou Edge e faça login.
2. Abra **Controle de Britadores**, **Controle de Floculantes** e **Controle IBM** uma vez **com internet** (isso guarda o app no aparelho).
3. No tablet: menu do navegador → **Adicionar à tela inicial / Instalar app**.
4. Depois disso, os apps abrem e salvam **sem internet**. Quando a rede volta, sincronizam sozinhos (a cada 2 minutos ou pelo botão **Sincronizar**).
5. Se o status mostrar **"Entre de novo para sincronizar"**, toque nele para refazer o login. Nada lançado é perdido: fica guardado no aparelho até sincronizar.

> Os dados de teste que estão nos apps abertos pelo arquivo (`index.html` local) ficam só naquele navegador e **não** passam para o site novo. Se precisar deles, use **Exportar CSV** antes.

## Relatório de Turno

O app **Relatório de Turno** (pasta `relatorio/`) guarda os relatórios no próprio navegador ou no **Firebase**, se existir o arquivo `relatorio/firebase-config.js` com a configuração do projeto (o mesmo usado hoje pela equipe). Sem esse arquivo, o app funciona e mostra o aviso "Firebase ainda não configurado".
Em **Relatórios salvos → Importar planilhas (.xlsx)** ele importa o relatório mensal da sala de controle (uma aba por turno), no layout novo ou no antigo (até jan/2026).
O Excel que ele gera (**Baixar em Excel**) pode ser importado no **Controle de Floculantes** (botão **Importar planilha**) ou lido pela ponte da planilha.

## Atualizar o site depois

Edite ou substitua os arquivos no GitHub (**Add file → Upload files**). O Azure publica a nova versão sozinho em poucos minutos.
Ao mudar um app, aumente o número em `const CACHE = "...-v2"` no `sw.js` dele (v3, v4...), para os tablets baixarem a versão nova.

## Limites dos planos gratuitos

- **Cosmos DB gratuito**: 1000 RU/s e 25 GB por conta, sem prazo, com SLA. Com 400 RU/s compartilhados e o limite da conta ligado, não há cobrança. O volume destes apps é muito pequeno perto disso.
- **Static Web Apps Free**: sem SLA e com limites de banda e tamanho. Se virar sistema oficial do setor, o TI pode mudar para o plano **Standard** em **Configurações → Plano de hospedagem**, sem refazer nada.

## Estrutura

```
index.html                  Portal (lista de controles + usuário logado)
staticwebapp.config.json    login obrigatório, rotas e versão do Python da API
britadores/                 app de britadores (index.html, sw.js, manifest.json)
floculantes/                app de floculantes
relatorio/                  app Relatório de Turno (lança o turno, gera o Excel e o PDF)
ibm/                        Controle IBM (desgaste no fluxograma da britagem)
itm/                        Controle ITM (vazão dos fluxos x capacidade dos equipamentos)
api/                        API Python (Azure Functions)
  mudancas/   GET  /api/{britadores|floculantes|ibm|itm}/mudancas?desde=...
  sync/       POST /api/{britadores|floculantes|ibm|itm}/sync
  saude/      GET  /api/saude
  shared_code/banco.py      acesso ao Cosmos DB e regras de acesso
```
