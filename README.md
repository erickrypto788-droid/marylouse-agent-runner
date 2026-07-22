# Telegram Affiliate Agent

Agente para buscar produtos de afiliados, selecionar as melhores ofertas, criar uma descrição curta com IA e publicar automaticamente em um canal do Telegram.

> Status deste pacote: pronto para MVP. O agente já roda em modo simulação, tem anti-duplicidade em SQLite, scoring, copy com IA/fallback e postagem via Telegram Bot API. Você só precisa colocar suas credenciais e ajustar o `config.yaml`.

---

## O que ele faz

1. Busca produtos nos marketplaces configurados.
2. Normaliza título, preço, preço antigo, imagem, link e métricas.
3. Filtra ofertas ruins ou incompletas.
4. Calcula score de prioridade.
5. Gera link final de afiliado/tracking quando configurado.
6. Cria copy curta para Telegram usando IA, ou fallback sem IA.
7. Publica no Telegram com imagem quando possível.
8. Salva histórico local para não repetir o mesmo produto.

---

## Marketplaces suportados

| Marketplace | Status no agente | Observação |
|---|---:|---|
| Mercado Livre | Implementado | Usa busca `/sites/MLB/search`. Se seu ambiente retornar 403, configure `ML_ACCESS_TOKEN`. |
| Amazon | Implementado | Usa Product Advertising API PA-API 5.0. Requer credenciais aprovadas. |
| Shopee | Implementado | Usa Affiliate Open API GraphQL. Requer App ID e Secret. |
| AliExpress | Implementado | Usa Affiliate API com assinatura SHA256. Requer App Key, Secret e Tracking ID. |
| CSV | Implementado | Útil para começar hoje com produtos exportados dos painéis. |

---

## Instalação local

```bash
cd telegram-affiliate-agent
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Copie os arquivos de configuração:

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

Edite `.env` e `config.yaml`.

---

## Configuração mínima para testar

O projeto vem com `data/products.example.csv`. Então você pode testar sem credenciais:

```bash
python run.py --once --dry-run
```

Ele vai mostrar as mensagens que seriam postadas, mas **não publica no Telegram**.

---

## Como publicar no Telegram

1. Fale com `@BotFather` no Telegram.
2. Crie um bot.
3. Copie o token para `.env`:

```env
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=@seu_canal
DRY_RUN=false
```

4. Adicione o bot como administrador do canal.
5. Rode:

```bash
python run.py --once --post
```

---

## Usando IA para criar a copy

No `.env`:

```env
OPENAI_API_KEY=sua_chave
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

Se `OPENAI_API_KEY` ficar vazio, o agente usa um texto automático simples sem IA.

---

## Configuração dos marketplaces

No `config.yaml`, ative/desative cada marketplace:

```yaml
marketplaces:
  mercadolivre:
    enabled: true
    keywords:
      - "fone bluetooth"
      - "ssd"

  amazon:
    enabled: false

  shopee:
    enabled: false

  aliexpress:
    enabled: false

  csv:
    enabled: true
    path: "data/products.example.csv"
```

### Amazon

Preencha no `.env`:

```env
AMAZON_ACCESS_KEY=
AMAZON_SECRET_KEY=
AMAZON_PARTNER_TAG=seutag-20
AMAZON_HOST=webservices.amazon.com.br
AMAZON_REGION=us-east-1
AMAZON_MARKETPLACE=www.amazon.com.br
```

Depois ative:

```yaml
amazon:
  enabled: true
  keywords:
    - "air fryer"
    - "fone bluetooth"
  search_index: "All"
  item_count: 10
```

### Shopee

Preencha no `.env`:

```env
SHOPEE_APP_ID=
SHOPEE_SECRET=
SHOPEE_ENDPOINT=https://open-api.affiliate.shopee.com.br/graphql
```

Ative:

```yaml
shopee:
  enabled: true
  keywords:
    - "fone bluetooth"
  limit_per_keyword: 20
  list_type: 2
  sort_type: 2
```

### AliExpress

Preencha no `.env`:

```env
ALIEXPRESS_APP_KEY=
ALIEXPRESS_SECRET=
ALIEXPRESS_TRACKING_ID=
ALIEXPRESS_ENDPOINT=https://api-sg.aliexpress.com/sync
```

Ative:

```yaml
aliexpress:
  enabled: true
  keywords:
    - "smartwatch"
  target_currency: "BRL"
  target_language: "PT"
  ship_to_country: "BR"
```

### Mercado Livre

```env
ML_SITE_ID=MLB
ML_ACCESS_TOKEN=
```

Se a busca pública funcionar no seu ambiente, deixe `ML_ACCESS_TOKEN` vazio. Se retornar 403, gere token no app do Mercado Livre e preencha.

---

## Links de afiliado e tracking

O agente preserva links de afiliado que já vêm das APIs, como `offerLink` da Shopee e `promotion_link` do AliExpress.

Para marketplaces sem conversão automática, você pode configurar templates em `config.yaml`:

```yaml
tracking:
  affiliate_templates:
    mercadolivre: "https://seu-gerador.com/deeplink?url={encoded_url}&subid={subid}"
    amazon: "{url}"
```

Variáveis disponíveis:

- `{url}`
- `{encoded_url}`
- `{product_id}`
- `{marketplace}`
- `{subid}`
- `{title}`
- `{encoded_title}`

---

## Anti-spam e anti-duplicidade

O agente salva o histórico em SQLite:

```env
SQLITE_PATH=data/agent.sqlite3
```

E evita repostar produtos nos últimos dias:

```yaml
agent:
  recent_duplicate_days: 10
```

---

## Agendamento com n8n

Arquivo pronto para importar:

```text
n8n/workflow_run_agent.json
```

Ele usa:

- Schedule Trigger;
- Execute Command;
- comando: `cd /home/node/telegram-affiliate-agent && python run.py --once`.

Importante: isso funciona melhor em **n8n self-hosted**. No n8n Cloud, hospede o agente em um servidor e troque o nó Execute Command por HTTP Request.

---

## Agendamento sem n8n

Cron a cada 1 hora:

```bash
0 * * * * cd /caminho/telegram-affiliate-agent && /caminho/telegram-affiliate-agent/.venv/bin/python run.py --once >> logs/agent.log 2>&1
```

---

## Docker

Build e execução:

```bash
docker compose run --rm affiliate-agent
```

Para postar de verdade, edite `.env` com `DRY_RUN=false` e as credenciais do Telegram.

---

## Próximos ajustes recomendados

1. Trocar `data/products.example.csv` por produtos reais ou ativar APIs.
2. Definir palavras-chave por nicho.
3. Ajustar filtros de preço e desconto.
4. Configurar templates de deeplink onde necessário.
5. Rodar 2 ou 3 dias em `DRY_RUN=true` para validar qualidade das mensagens.
6. Só depois ativar `DRY_RUN=false`.

---

## Comando rápido

```bash
cp .env.example .env
cp config.example.yaml config.yaml
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py --once --dry-run
```
