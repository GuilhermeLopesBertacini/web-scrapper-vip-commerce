Web Scrapper VIP Commerce
==========================

Scrapper para baixar imagens de produtos do portal VIP Commerce usando a API Urbanic.

```
src/
├── pipelines/
│   ├── api/            ← Pipeline Novo (recomendado)
│   │   ├── download_images_api.py
│   │   └── upload_files.py
│   └── legacy/         ← Pipeline Antigo / Selenium (legado)
│       ├── main.py
│       ├── fetch_products_map.py
│       ├── download_images.py
│       └── compare_images.py
└── utils/
    └── config.py       ← configurações compartilhadas
```

Índice
------

- **Pipeline Novo (Recomendado)**: `src/pipelines/api/`
- Pipeline Antigo (Legado): `src/pipelines/legacy/`
- Configuração

---

## 🚀 Método Novo (Recomendado): API-based Downloader

**Vantagens:**
- ✅ Muito mais rápido (sem overhead de navegador)
- ✅ Roda em qualquer VM (sem necessidade de GUI/Chrome)
- ✅ Dependências mínimas (apenas requests, tqdm, urllib3)
- ✅ Mais confiável (dados diretos da API)

### Requisitos

Apenas Python 3.7+ e as dependências mínimas:

```bash
pip install -r requirements-minimal.txt
```

### Como rodar

```bash
# 1. Baixar imagens novas (compara com o GCP automaticamente)
python3 -m src.pipelines.api.download_images_api

# 2. (Opcional) Fazer upload para o GCP
python3 -m src.pipelines.api.upload_files
```

O script de download:
1. Busca todos os produtos da API Urbanic (com paginação automática)
2. Lista imagens já existentes no GCP e calcula a diferença
3. Baixa em paralelo **apenas as imagens novas** (8 workers) para `src/assets/raw_images/`
4. Nomeia cada imagem pelo `codigo_erp.jpg`

### Configuração

Edite as constantes no topo de `src/pipelines/api/download_images_api.py`:
- `PREFERRED_IMAGE_SIZE = 250` — tamanho preferido (250, 500, 144, 60)
- `MAX_WORKERS = 8` — número de downloads paralelos
- `API_ENDPOINT` — URL da API (já configurado via `.env`)

---

## 📦 Método Antigo (Legado): Selenium-based Scraper

**⚠️ Apenas para referência.** Use o método API acima, que é muito superior.

### Requisitos (bibliotecas do sistema)

O Chrome headless (ou a build do Chromium) com o chromedriver precisa das bibliotecas abaixo em sistemas Debian/Ubuntu. Execute como root/ sudo:

```
sudo apt-get update && sudo apt-get install -y \
    libglib2.0-0t64 \
    libnss3 \
    libfontconfig1 \
    libx11-6 \
    libx11-xcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxi6 \
    libxtst6 \
    libasound2t64 \
    libatk1.0-0t64 \
    libatk-bridge2.0-0t64 \
    libcups2t64 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0t64 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libxfixes3 \
    libxrandr2 \
    libxss1 \
    at-spi2-core
```

Observação: nomes das bibliotecas podem variar entre distribuições/versões — use o package manager da sua distro quando necessário.

### Estrutura de assets (Selenium legado)

O projeto espera encontrar os binários do Chrome/Chromium e do Chromedriver dentro da pasta `src/assets` (já organizada no repo). A estrutura deve ser:

- `src/assets/chrome-linux64/chrome` — executável do Chrome/Chromium (marcar como executável)
- `src/assets/chromedriver-linux64/chromedriver` — binário do chromedriver compatível (marcar como executável)
- `src/assets/data/product_map.json` — mapa de produtos (chave: product_id, valor: codigo_erp)
- `src/assets/raw_images/` — pasta onde as imagens baixadas serão salvas (criada automaticamente)

Certifique-se de que os binários têm permissão de execução:

```
chmod +x src/assets/chrome-linux64/chrome src/assets/chromedriver-linux64/chromedriver
```

### Como rodar (Selenium legado)

```bash
pip install -r requirements.txt

# Etapa 1: gerar o mapa de produtos
python3 -m src.pipelines.legacy.fetch_products_map

# Etapa 2: baixar as imagens via Selenium
python3 -m src.pipelines.legacy.download_images

# Ou executar as duas etapas de uma vez:
python3 -m src.pipelines.legacy.main
```

---

## 📝 Notas

O código carrega algumas constantes de `src/utils/config.py`. O mais importante é o `DOMAIN_KEY` (o domínio base do site). Você pode configurá-lo de duas formas:

1) Usando um arquivo `.env` na raiz do projeto (recomendado):

```
# .env (exemplo)
DOMAIN_KEY=supervillesupermercado.com.br
# AUTH_TOKEN=...
# API_BASE_URL=...
```

## 📊 Performance

Resultados típicos (~9000 produtos):
- **Método API**: ~2-5 minutos (depende da banda e workers)
- **Método Selenium (legado)**: ~30-60 minutos